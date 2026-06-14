# -*- coding: utf-8 -*-
"""
Pydantic input/output models ? all Skills must use these.

All AI-related enums/literals use pre-constructed string constants to
avoid encoding issues across platforms.
"""

from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")

# ?? AI judgement literals ?????????????????????????????????????
# Use constants to avoid platform encoding quirks with Chinese Unicode
_REASONABLE = "\u5408\u7406"      # ??
_UNREASONABLE = "\u4e0d\u5408\u7406"  # ???


# ?? P0: AI intermediate results ??????????????????????????????

class AiValidationResult(BaseModel):
    """Standardised output of AI common-sense validation."""

    model_config = ConfigDict(frozen=True)

    result: Literal[
        "\u5408\u7406",
        "\u4e0d\u5408\u7406",
    ] = Field(..., description="AI judgement: reasonable / unreasonable")

    reason: str = Field(default="", description="AI reasoning (max 500 chars)")

    @field_validator("reason")
    @classmethod
    def _truncate_reason(cls, v: str) -> str:
        return v[:500]


class AiReselectionResult(BaseModel):
    """Standardised output of AI reselection."""

    model_config = ConfigDict(frozen=True)

    result: str = Field(
        ..., description="Reselected value, or '\u4e0d\u5408\u7406' if still unreasonable"
    )
    reason: str = Field(default="", description="AI reasoning (max 500 chars)")

    @field_validator("reason")
    @classmethod
    def _truncate_reason(cls, v: str) -> str:
        return v[:500]


# ?? P1: DeepSeek client models ???????????????????????????????

class DeepSeekChatResponse(BaseModel):
    """Validated OpenAI Chat Completions response wrapper."""

    content: str = Field(default="")
    finish_reason: str | None = Field(default=None)
    prompt_tokens: int | None = Field(default=None)
    completion_tokens: int | None = Field(default=None)


# ?? P1: Log entry ????????????????????????????????????????????

class LogEntry(BaseModel):
    """Single JSONL log entry schema.

    All fields defaulted so legacy / partial reads won't fail.
    """

    trace_id: str = Field(default="")
    skill_name: str = Field(default="")
    timestamp: str = Field(default="")
    is_failure: bool = Field(default=False)
    input_summary: dict[str, Any] = Field(default_factory=dict)
    rule_output: dict[str, Any] = Field(default_factory=dict)
    ai_validation: dict[str, Any] | None = Field(default=None)
    ai_reselection: dict[str, Any] | None = Field(default=None)
    final_output: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    elapsed_ms: float = Field(default=0.0)


# ?? P2: Fallback config ??????????????????????????????????????

class FallbackConfigModel(BaseModel):
    """Validated fallback configuration."""

    validate_timeout_seconds: float = Field(default=3.0, gt=0)
    reselect_timeout_seconds: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=1, ge=0, le=5)
    circuit_breaker_threshold: int = Field(default=3, ge=1)
    circuit_breaker_cooldown_seconds: float = Field(default=60.0, gt=0)
    conservative_mode: bool = Field(default=False)
    enabled: bool = Field(default=True)


# ?? P2: Evolve proposal ??????????????????????????????????????

class EvolveProposalModel(BaseModel):
    """Serializable evolve proposal."""

    rules_changes: dict[str, Any] = Field(default_factory=dict)
    prompt_changes: dict[str, Any] = Field(default_factory=dict)
    rules_text: str | None = Field(default=None)
    prompt_text: str | None = Field(default=None)
    analysis_raw: str = Field(default="")
    failure_count: int = Field(default=0)
    applied: bool = Field(default=False)
    rolled_back: bool = Field(default=False)


# ?? P3: Skill-specific result sub-models (example) ?????????

class NicknameSkillResult(BaseModel):
    """nickname-selector Skill result sub-structure."""

    nickname: str = Field(default="", description="Selected nickname")
    source: str = Field(default="rule", description="rule | ai")
    candidates: list[str] = Field(default_factory=list)
    band_id: str = Field(default="")
    screenshot_id: str = Field(default="")


# ?? Core framework models (existing) ????????????????????????

class SkillOutput(BaseModel):
    """All Skills must return this structure."""

    source: str = Field(..., description="rule | ai")
    result: dict = Field(..., description="Business result (per-Skill schema)")
    ai_validated: bool = False
    ai_reselected: bool = False
    warnings: list[str] = Field(default_factory=list)


class SkillInput(BaseModel, Generic[T]):
    """All Skills must receive this structure."""

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    input_data: T = Field(..., description="Business input data")
