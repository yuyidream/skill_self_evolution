"""
DeepSeek 客户端封装 — 超时/重试/熔断，兼容 OpenAI Chat Completions API。
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from skill_self_evolution.config import get_deepseek_config

logger = logging.getLogger(__name__)


@dataclass
class DeepSeekResponse:
    """简化的 AI 响应模型，不依赖项目内部 Pydantic。"""

    content: str
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


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


class DeepSeekClient:
    """DeepSeek OpenAI 兼容客户端，内置超时/重试/熔断。

    环境感知：local → api.deepseek.com, test/prod → api.modelarts-maas.com/v2
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        timeout: float = 60.0,
        max_retries: int = 1,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        cfg = get_deepseek_config(api_key=api_key, api_base=api_base, model=model)
        self._api_key = cfg.api_key
        self._api_base = cfg.api_base.rstrip("/")
        self._model = cfg.model
        self._timeout = timeout
        self._max_retries = max_retries
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._chat_url = f"{self._api_base}/chat/completions"

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._circuit_breaker

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float | None = None,
    ) -> DeepSeekResponse:
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
    ) -> DeepSeekResponse:
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

        async with httpx.AsyncClient(timeout=timeout, http2=False, trust_env=False) as client:
            resp = await client.post(self._chat_url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        return DeepSeekResponse(
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
        # 尝试提取 JSON（可能包裹在 ```json ... ``` 中）
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("DeepSeek 响应非 JSON: %s", content[:200])
            return {}
