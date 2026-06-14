"""
AI 降级策略 — 乐观/保守模式 + 熔断检查。

统一降级总原则：
- 输入非法 → 框架层直接返回 400，不执行业务逻辑
- AI 验证失败/超时 → 标记跳过，采信规则结果
- AI 重选失败/超时 → 直接返回规则原始结果
- AI 全局熔断 → 全链路跳过 AI，纯走规则
- 保守降级模式 → 可选开关：AI 不可用时标记「需人工复核」而非直接通过
- warnings → 仅用于日志和监控，不阻断流程
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel, Field

from skill_self_evolution.deepseek import CircuitBreaker

logger = logging.getLogger(__name__)


class FallbackMode(str, Enum):
    OPTIMISTIC = "optimistic"
    CONSERVATIVE = "conservative"


@dataclass
class FallbackConfig:
    """降级配置，来源 rules_config.yaml 的 ai_fallback 段。

    注：此结构保持 @dataclass（非 Pydantic），原因：
    - 构造来源已通过 FallbackConfigModel（Pydantic）校验
    - 内嵌在 FallbackStrategy 中，无独立序列化需求
    """

    validate_timeout_seconds: float = 3.0
    reselect_timeout_seconds: float = 5.0
    max_retries: int = 1
    circuit_breaker_threshold: int = 3
    circuit_breaker_cooldown_seconds: float = 60.0
    conservative_mode: bool = False
    enabled: bool = True


class FallbackResult(BaseModel):
    """降级处理结果（Pydantic 校验）。"""

    skip_ai: bool = Field(default=False, description="是否应跳过 AI 步骤")
    reason: str = Field(default="", description="降级原因")
    warnings: list[str] = Field(default_factory=list, description="降级时的警告信息")
    needs_review: bool = Field(default=False, description="AI 不可用时是否标记需人工复核")


class FallbackStrategy:
    """AI 降级策略管理器。

    使用方式：
        strategy = FallbackStrategy(config, circuit_breaker)
        result = strategy.on_validate_failure(error)
        if result.skip_ai:
            return fallback_output
    """

    def __init__(self, config: FallbackConfig, circuit_breaker: CircuitBreaker):
        self.config = config
        self.circuit_breaker = circuit_breaker

    @property
    def mode(self) -> FallbackMode:
        return FallbackMode.CONSERVATIVE if self.config.conservative_mode else FallbackMode.OPTIMISTIC

    @property
    def is_circuit_open(self) -> bool:
        return self.circuit_breaker.is_open

    def check_before_ai(self) -> FallbackResult:
        """在调用 AI 之前检查是否应跳过。"""
        warnings: list[str] = []

        if not self.config.enabled:
            return FallbackResult(skip_ai=True, reason="AI 全局已禁用", warnings=warnings)

        if self.circuit_breaker.is_open:
            msg = "AI 熔断中，跳过本步骤"
            warnings.append(msg)
            return FallbackResult(
                skip_ai=True,
                reason=msg,
                warnings=warnings,
                needs_review=self.mode == FallbackMode.CONSERVATIVE,
            )

        return FallbackResult(skip_ai=False)

    def on_validate_failure(self, error: Exception | None = None) -> FallbackResult:
        """AI 验证失败/超时时的降级处理。"""
        warnings: list[str] = []
        reason = f"AI 验证不可用: {error}" if error else "AI 验证不可用"

        if self.mode == FallbackMode.CONSERVATIVE:
            warnings.append("需人工复核: AI验证不可用")
            return FallbackResult(
                skip_ai=True,
                reason=reason,
                warnings=warnings,
                needs_review=True,
            )

        # 乐观模式：默认"验证通过"
        return FallbackResult(skip_ai=True, reason=reason, warnings=warnings)

    def on_reselect_failure(self, error: Exception | None = None) -> FallbackResult:
        """AI 重选失败/超时时的降级处理。"""
        warnings: list[str] = []
        reason = f"AI 重选不可用: {error}" if error else "AI 重选不可用"

        if self.mode == FallbackMode.CONSERVATIVE:
            warnings.append("需人工复核: AI重选不可用")
            return FallbackResult(
                skip_ai=True,
                reason=reason,
                warnings=warnings,
                needs_review=True,
            )

        # 乐观模式：返回规则原始结果
        return FallbackResult(skip_ai=True, reason=reason, warnings=warnings)
