"""
DeepSeek 客户端封装 — 超时/重试/熔断/流式，兼容 OpenAI Chat Completions API。

统一客户端：合并 backend DeepSeekClient（流式、URL 规范化、MaaS 兼容）+
skill-engine DeepSeekClient（熔断、重试、JSON 解析）。
"""

import asyncio
import json
from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from skill_self_evolution.config import get_deepseek_config
from skill_self_evolution.models import DeepSeekChatResponse


# ── URL 规范化 ──

def normalize_deepseek_api_base(raw: str | None) -> str:
    """规范化 OpenAI 兼容的根地址，避免 CI / .env 中残留 BOM、缺 scheme、缺主机名。"""
    s0 = raw if raw is not None else ""
    s = unicodedata.normalize("NFKC", str(s0)).strip().strip("\ufeff").strip()
    if not s:
        return "https://api.deepseek.com/v1"
    if "://" not in s:
        s = "https://" + s.lstrip("/")
    p = urlparse(s)
    host = (p.hostname or "").strip()
    if not host:
        logger.warning("normalize_deepseek_api_base: 无有效主机名 (%r)，回退 https://api.deepseek.com/v1", raw)
        return "https://api.deepseek.com/v1"
    b = s.rstrip("/")
    if not b.endswith(("/v1", "/v2")):
        b += "/v1"
    return b


# ── 流式响应块 ──

@dataclass
class StreamChunk:
    """流式响应块。"""

    delta: str = ""
    finish_reason: str | None = None


# ── 熔断器 ──

class CircuitBreaker:
    """简单熔断器：连续失败 N 次后冷却 M 秒。"""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 60.0):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._open = False

    @property
    def is_open(self) -> bool:
        if not self._open:
            return False
        if time.monotonic() - self._last_failure_time >= self.cooldown_seconds:
            self._open = False
            self._failure_count = 0
            logger.info("熔断器冷却完毕，恢复请求")
            return False
        return True

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.threshold and not self._open:
            self._open = True
            logger.warning("熔断器触发：连续 %d 次失败，冷却 %d 秒", self._failure_count, self.cooldown_seconds)

    def record_success(self) -> None:
        self._failure_count = 0
        if self._open:
            self._open = False
            logger.info("熔断器关闭（请求成功）")


# ── 统一客户端 ──

class DeepSeekClient:
    """DeepSeek OpenAI 兼容客户端，内置超时/重试/熔断/流式支持。

    环境感知：local → api.deepseek.com, test/prod → api.modelarts-maas.com/v2

    构造方式：
        # keyword args（推荐）
        client = DeepSeekClient(api_key="sk-...", api_base="https://...", model="...")
        # 或 config dict（backend 兼容）
        client = DeepSeekClient({"api_key": "sk-..."}, timeout=120)
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        timeout: float = 60.0,
        max_retries: int = 1,
        circuit_breaker: CircuitBreaker | None = None,
        **kwargs: Any,
    ):
        # 兼容 config dict + **kwargs 合并模式（backend 原有风格）
        merged: dict[str, Any] = dict(config or {})
        merged.update(kwargs)
        _ak = merged.get("api_key", api_key) or api_key
        _ab = merged.get("api_base", api_base) or api_base
        _md = merged.get("model", model) or model

        cfg = get_deepseek_config(api_key=_ak, api_base=_ab, model=_md)
        self._api_key = cfg.api_key
        self._api_base = normalize_deepseek_api_base(cfg.api_base)
        self._model = cfg.model
        self._timeout = float(merged.get("timeout", timeout) or timeout)
        self._max_retries = int(merged.get("max_retries", max_retries) or max_retries)
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._chat_url = f"{self._api_base}/chat/completions"

    # ── 属性 ──

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit_breaker

    @property
    def api_base(self) -> str:
        return self._api_base

    @property
    def model(self) -> str:
        return self._model

    # ── 请求 ──

    def _make_timeout(self, read_timeout: float | None = None) -> httpx.Timeout:
        """统一超时；华为云 MaaS 对 HTTP/2 兼容性差用 http2=False；MaaS 连接超时 45s 避免 ConnectTimeout。"""
        read_t = float(read_timeout or self._timeout)
        connect_t = 45.0 if "modelarts-maas" in (self._api_base or "") else 15.0
        return httpx.Timeout(read_t, connect=connect_t, read=read_t)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> DeepSeekChatResponse:
        """发送非流式 chat 请求，支持自动重试。

        Raises:
            RuntimeError: 熔断器开启或所有重试均失败
        """
        if self._circuit_breaker.is_open:
            raise RuntimeError("熔断器已开启，拒绝请求")

        last_error: Exception | None = None
        effective_timeout = timeout or self._timeout

        for attempt in range(self._max_retries + 1):
            try:
                result = await self._do_chat(messages, temperature, max_tokens, effective_timeout)
                self._circuit_breaker.record_success()
                return result
            except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
                last_error = e
                logger.warning("DeepSeek 请求失败 (attempt %d/%d): %s", attempt + 1, self._max_retries + 1, e)
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                continue

        self._circuit_breaker.record_failure()
        raise RuntimeError(f"DeepSeek 请求全部失败 (重试 {self._max_retries} 次): {last_error}") from last_error

    async def _do_chat(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> DeepSeekChatResponse:
        if not self._api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY 未配置。"
                "进化旁路（SkillExecutor / Evolver）依赖此环境变量；"
                "请在 docker-compose 或 .env 中设置 DEEPSEEK_API_KEY"
            )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=self._make_timeout(timeout), http2=False, trust_env=False) as client:
            resp = await client.post(self._chat_url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        return DeepSeekChatResponse(
            content=choice.get("message", {}).get("content", ""),
            finish_reason=choice.get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """发送请求并将响应解析为 JSON dict。解析失败时返回空 dict。"""
        resp = await self.chat(messages, temperature, max_tokens, timeout)
        content = resp.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("DeepSeek 响应非 JSON: %s", content[:200])
            return {}

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """发送流式 chat 请求，逐个产出增量块。

        Yields:
            StreamChunk: 每个流式响应块（delta + finish_reason）
        """
        if self._circuit_breaker.is_open:
            raise RuntimeError("熔断器已开启，拒绝请求")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._make_timeout(timeout), http2=False, trust_env=False
            ) as client:
                async with client.stream("POST", self._chat_url, headers=headers, json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                        yield StreamChunk(
                            delta=delta.get("content", ""),
                            finish_reason=chunk_data.get("choices", [{}])[0].get("finish_reason"),
                        )
            self._circuit_breaker.record_success()
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.RequestError) as e:
            self._circuit_breaker.record_failure()
            raise RuntimeError(f"DeepSeek 流式请求失败: {e}") from e
