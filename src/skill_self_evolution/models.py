"""
Pydantic 输入输出模型 — 所有 Skill 必须使用。
"""

from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

T = TypeVar("T")


class SkillOutput(BaseModel):
    """所有 Skill 输出必须继承的结构。

    Attributes:
        source: 结果来源 "rule" 或 "ai"
        result: 业务结果 dict，各 Skill 可自定义内部结构
        ai_validated: AI 是否执行了常识验证（含降级默认通过）
        ai_reselected: AI 是否执行了重新选择/提取
        warnings: 仅用于日志和监控的警告信息，不阻断流程
    """

    source: str = Field(..., description="rule | ai")
    result: dict = Field(
        ..., description="业务结果。各 Skill 差异大，暂不强校验内部结构"
    )
    ai_validated: bool = False
    ai_reselected: bool = False
    warnings: list[str] = Field(
        default_factory=list, description="仅用于日志和监控，不阻断流程"
    )


class SkillInput(BaseModel, Generic[T]):
    """所有 Skill 输入必须继承。T 为各 Skill 自定义的 InputData 子类。

    Attributes:
        trace_id: 链路追踪 ID，未传入时框架自动生成 uuid4
        input_data: 业务输入数据，类型由 Skill 定义
    """

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    input_data: T = Field(..., description="业务输入数据")
