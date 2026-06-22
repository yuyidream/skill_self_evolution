# -*- coding: utf-8 -*-
"""
Pydantic input/output models — all Skills must use these.

All AI-related enums/literals use pre-constructed string constants to
avoid encoding issues across platforms.
"""

from typing import Any, Generic, Literal, Optional, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

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

    result: Any = Field(
        ..., description="Reselected value (dict / str), or '\u4e0d\u5408\u7406' if still unreasonable"
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
    session_date: str = Field(
        default="",
        description="Session 真实日期（从 session 目录路径解析的 YYYY-MM-DD），"
        "用于训练集按真实日期排除（而非日志写入时间）。",
    )
    is_failure: bool = Field(default=False)
    no_valid_alternative: bool = Field(
        default=False,
        description="PRD §B.1: True when AI reselection failed because no reasonable "
        "alternative exists in the candidate pool (rules incorrectly filtered out "
        "the correct answer).",
    )
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
    training_set_size: int = Field(default=0)
    validation_set_size: int = Field(default=0)
    version_before: int | None = Field(default=None, description="进化前 rules_config 版本号")
    version_after: int | None = Field(default=None, description="进化后 rules_config 版本号")
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


# ── Session 目录输入 ──

class SessionInput(BaseModel):
    """session 目录定位信息。用于 executor 从 session 目录加载候选块。"""

    model_config = ConfigDict(extra="allow")

    session_dir: str = Field(
        default="",
        description="session 目录的绝对路径（含 debug_session_derived.json 和 speaker JSON）",
    )
    screenshot_id: str = Field(default="", description="目标截图 ID")


# ── Candidate file — 调用方传入的候选人 JSON ──

class CandidateInput(BaseModel):
    """调用方准备好的候选人 JSON 文件格式。

    示例 JSON 文件内容：
        {"candidates": ["张三", "李四", "王五"]}

    SkillExecutor 会校验此格式再送入规则引擎。
    """

    candidates: list[str] = Field(
        ...,
        min_length=1,
        description="候选文本列表，至少一条",
    )


# ═══════════════════════════════════════════════════
#  P0: 外部输入模型 — 调用方传入，框架入口校验
# ═══════════════════════════════════════════════════

# ── rejection_rules 单条规则 ──

class RejectionRuleItem(BaseModel):
    """单条声明式拒绝规则。rule_runner 按序遍历执行。"""

    model_config = ConfigDict(extra="allow")

    type: Literal["regex", "prefix", "length", "geometry"] = Field(
        ..., description="规则类型：正则 / 前缀 / 长度 / 几何约束"
    )
    action: Literal["drop", "remove_prefix"] = Field(
        default="drop", description="命中后动作"
    )
    pattern: str = Field(default="", description="regex 类型的正则模式")
    keywords: list[str] = Field(default_factory=list, description="prefix 类型的关键词列表")
    min: int = Field(default=0, ge=0, description="length 类型的最小长度")
    max: int = Field(default=999, ge=0, description="length 类型的最大长度")
    description: str = Field(default="", description="规则用途说明")


# ── OCR block 与几何规则 ──

class OcrBlock(BaseModel):
    """OCR 识别出的单个文本块，含几何信息。

    debug_session_derived.json 中 blocks[] 的单条记录。
    """

    model_config = ConfigDict(extra="allow")

    text: str = Field(..., description="OCR 文本")
    bbox_xyxy: list[float] = Field(
        default_factory=lambda: [0, 0, 0, 0],
        description="边界框 [x1, y1, x2, y2]",
    )
    class_: str = Field(
        default="",
        alias="class",
        description="分类标签：nickname_candidate / bubble_text / drop",
    )
    confidence: float = Field(default=0.0, ge=0, le=1, description="OCR 置信度")
    band: str = Field(default="", description="所属 band ID")

    @property
    def width(self) -> float:
        return max(0.0, self.bbox_xyxy[2] - self.bbox_xyxy[0])

    @property
    def height(self) -> float:
        return max(0.0, self.bbox_xyxy[3] - self.bbox_xyxy[1])

    @property
    def center_x(self) -> float:
        return (self.bbox_xyxy[0] + self.bbox_xyxy[2]) / 2

    @property
    def center_y(self) -> float:
        return (self.bbox_xyxy[1] + self.bbox_xyxy[3]) / 2

    @property
    def left(self) -> float:
        return self.bbox_xyxy[0]

    @property
    def top(self) -> float:
        return self.bbox_xyxy[1]

    @property
    def right(self) -> float:
        return self.bbox_xyxy[2]

    @property
    def bottom(self) -> float:
        return self.bbox_xyxy[3]


class GeometryRuleParams(BaseModel):
    """几何规则的预计算参数。由 rule_runner 在进入 geometry 规则链前算好。"""

    model_config = ConfigDict(extra="allow")

    screen_width: float = Field(default=0, description="屏幕宽度（px）")
    screen_height: float = Field(default=0, description="屏幕高度（px）")
    midline_y: float = Field(default=0, description="屏幕中线 y 坐标")
    avatar_column_left: float = Field(default=0, description="头像列左边界")
    avatar_column_right: float = Field(default=0, description="头像列右边界")
    char_height_median: float = Field(default=0, description="当前帧字符高度中位数（px）")


class BlockCandidate(BaseModel):
    """从 session 目录提取的候选块，带 OcrBlock 完整信息。"""

    model_config = ConfigDict(extra="allow")

    block: OcrBlock = Field(..., description="OCR 文本块")
    source_file: str = Field(default="", description="来源文件（debug_session_derived.json）")
    is_pipeline_selected: bool = Field(
        default=False,
        description="管线是否选中此 block 的 text 为最终昵称",
    )


# ── correctness_criteria 子段 ──

class BadCategory(BaseModel):
    """一个『坏类别』（安全横幅 / 简历碎片等）。"""

    model_config = ConfigDict(extra="allow")

    name: str = Field(..., description="类别名称")
    description: str = Field(default="", description="类别说明")
    patterns: list[str] = Field(default_factory=list, description="匹配正则列表")


class VerificationCondition(BaseModel):
    """一条正确性判据条件。"""

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="条件 ID（如 card_binding）")
    description: str = Field(default="", description="条件描述")
    checkable_in_skill: bool = Field(default=False, description="是否可在 Skill 内独立校验")
    note: str = Field(default="", description="备注")


class CorrectnessCriteriaModel(BaseModel):
    """正确性判据段 — Evolver 可优化此段内容。"""

    model_config = ConfigDict(extra="allow")

    bad_categories: list[BadCategory] = Field(default_factory=list)
    verification_conditions: list[VerificationCondition] = Field(default_factory=list)


# ── nickname_thresholds ──

class NicknameThresholdsModel(BaseModel):
    """昵称规则阈值。"""

    model_config = ConfigDict(extra="allow")

    min_confidence: float = Field(default=0.7, ge=0, le=1)
    nickname_max_chars: int = Field(default=30, ge=1)
    nickname_max_char_height_ratio: float = Field(default=1.2, gt=0)
    screen_midline_ratio: float = Field(default=0.5, ge=0, le=1)
    nickname_max_x1_ratio: float = Field(default=0.30, ge=0, le=1)


# ── rules_config 总模型 ──

class RulesConfigModel(BaseModel):
    """rules_config.yaml 完整校验模型。

    入口校验：
        RulesConfigModel.model_validate(rules_dict)
    失败 → ValidationError（调用方收到清晰错误信息）。
    """

    model_config = ConfigDict(extra="allow")

    correctness_criteria: CorrectnessCriteriaModel = Field(
        default_factory=CorrectnessCriteriaModel
    )
    rejection_rules: list[RejectionRuleItem] = Field(default_factory=list)
    nickname_thresholds: NicknameThresholdsModel = Field(
        default_factory=NicknameThresholdsModel
    )
    ai_fallback: FallbackConfigModel = Field(default_factory=FallbackConfigModel)


# ── prompt_config 总模型 ──

class PromptConfigModel(BaseModel):
    """prompt.yaml 完整校验模型。"""

    model_config = ConfigDict(extra="allow")

    system_prompt: str = Field(default="", description="AI 角色设定")
    user_template_validate: str = Field(default="", description="AI 验证阶段的 User 模板")
    user_template_reselect: str = Field(default="", description="AI 重选阶段的 User 模板")


# ── evolve.toml 子段 ──

class EvolveAutoModifyRulesConfigModel(BaseModel):
    """auto_modify.rules_config 段。"""

    model_config = ConfigDict(extra="allow")

    mode: str = Field(default="full", description="修改模式")
    max_change_percent: float = Field(default=20, ge=0, le=100, description="单次数值变更上限 %")
    scripts: bool = Field(default=False, description="是否允许 Evolver 提出需改代码的规则")


class EvolveAutoModifyModel(BaseModel):
    """auto_modify 段。"""

    model_config = ConfigDict(extra="allow")

    rules_config: EvolveAutoModifyRulesConfigModel | bool = Field(
        default_factory=lambda: EvolveAutoModifyRulesConfigModel(),
        description="rules_config 自动修改开关（bool 或详细配置 dict）",
    )
    prompt: bool = Field(default=False, description="prompt 自动修改开关")


class EvolveGuardModel(BaseModel):
    """guard 段 — benchmark 安全网 + 进化阈值。"""

    model_config = ConfigDict(extra="allow")

    require_benchmark_pass: bool = Field(
        default=True, description="是否要求 benchmark 通过才保留变更"
    )
    min_failure_count: int = Field(
        default=10, ge=1, description="触发进化所需的最小失败案例数"
    )
    max_cases_per_batch: int = Field(
        default=20, ge=1, le=100, description="单次发送给 Evolver AI 的最大案例数"
    )
    dry_run: bool = Field(
        default=False, description="dry_run 模式：仅分析不写入"
    )


class EvolveSectionModel(BaseModel):
    """evolve.* 段。"""

    model_config = ConfigDict(extra="allow")

    auto_modify: EvolveAutoModifyModel = Field(default_factory=EvolveAutoModifyModel)
    guard: EvolveGuardModel = Field(default_factory=EvolveGuardModel)


class EvolveSkillSectionModel(BaseModel):
    """skill.* 段。"""

    model_config = ConfigDict(extra="allow")

    ai_role: str = Field(default="correction", description="correction | enhancement")


# ── evolve.toml 总模型 ──

class EvolveTomlModel(BaseModel):
    """evolve.toml 完整校验模型。"""

    model_config = ConfigDict(extra="allow")

    skill: EvolveSkillSectionModel = Field(default_factory=EvolveSkillSectionModel)
    evolve: EvolveSectionModel = Field(default_factory=EvolveSectionModel)


# ── evolve_prompt.yaml ──

class EvolvePromptYamlModel(BaseModel):
    """Evolver AI 分析用提示词模板。"""

    model_config = ConfigDict(extra="allow")

    system: str = Field(default="", description="AI 角色设定")
    analyze_template: str = Field(default="", description="失败案例分析模板（含占位符）")


# ═══════════════════════════════════════════════════
#  P1: 框架内部数据传递
# ═══════════════════════════════════════════════════

class RuleResultDict(BaseModel):
    """规则引擎输出结构。executor 内部拼装，写入 JSONL。"""

    model_config = ConfigDict(extra="allow")

    candidates: list[str] = Field(default_factory=list, description="规则过滤后的候选列表")
    result: str = Field(default="", description="规则选定的最终值")


# ═══════════════════════════════════════════════════
#  P2: 门禁 / 代码检查 — 从 dataclass 迁移到 Pydantic
# ═══════════════════════════════════════════════════

class CodeIssueModel(BaseModel):
    """AST 静态检查发现的问题。"""

    model_config = ConfigDict(frozen=False)

    rule: str = Field(..., description="规则名（如 no_bare_except）")
    level: str = Field(..., description="error | warning")
    message: str = Field(..., description="问题描述")
    file: str = Field(default="")
    line: int = Field(default=0, ge=0)
    col: int = Field(default=0, ge=0)


class FunctionContextModel(BaseModel):
    """从 AST 自动提取的函数上下文。"""

    name: str = Field(..., description="函数名")
    file: str = Field(default="")
    is_method: bool = Field(default=False, description="是否有 self/cls 参数")
    params: list[str] = Field(default_factory=list, description="参数名列表")
    local_vars: list[str] = Field(
        default_factory=list, description="函数体内赋值的变量（去重，保持声明顺序）"
    )
    lineno: int = Field(default=0, ge=0)
    end_lineno: int = Field(default=0, ge=0)

    @computed_field
    @property
    def self_forbidden(self) -> bool:
        """模块级函数禁止使用 self。"""
        return not self.is_method

    def context_for_prompt(self) -> str:
        """生成注入 AI prompt 的上下文文本。"""
        lines = [
            f"Target function: {self.name} (module-level, {'has self' if self.is_method else 'NO self'})",
            f"Parameters: {', '.join(self.params)}",
        ]
        if self.local_vars:
            lines.append(f"Available variables before target region: {', '.join(self.local_vars)}")
        if self.self_forbidden:
            lines.append("FORBIDDEN: self (module-level function)")
            lines.append("FORBIDDEN: self.config, self.xxx — no self available")
        return "\n".join(lines)


class LayerResultModel(BaseModel):
    """单层门禁结果。"""

    layer: int = Field(..., ge=1, le=4, description="层号 1-4")
    layer_name: str = Field(..., description="层名称")
    passed: bool = Field(..., description="本层是否通过")
    issues: list[CodeIssueModel] = Field(default_factory=list, description="代码质量问题列表")
    output: str = Field(default="", description="pytest 输出 / 错误信息")
    elapsed_ms: float = Field(default=0, ge=0)


class GateResultModel(BaseModel):
    """完整 4 层门禁结果。"""

    passed: bool = Field(..., description="全部通过？")
    layers: list[LayerResultModel] = Field(default_factory=list, description="各层结果")
    feedback: str = Field(default="", description="失败时喂回 AI 的错误信息")
    total_elapsed_ms: float = Field(default=0, ge=0)

    @computed_field
    @property
    def failed_layer(self) -> Optional[int]:
        """第一个失败层的层号，全部通过返回 None。"""
        for lr in self.layers:
            if not lr.passed:
                return lr.layer
        return None
