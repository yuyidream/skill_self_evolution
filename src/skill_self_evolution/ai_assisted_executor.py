"""
AiAssistedExecutor — 通用 AI 辅助执行基类。

提供「验证 + 重选」的通用流程模板，Skill 只需定义：
  - ai_validate()：AI 常识判断（correction 角色） → AiValidationResult
  - ai_reselect()：AI 重新选择/提取（correction 角色） → AiReselectionResult
  - ai_enhance()：AI 增强（enhancement 角色） → dict | None

框架自动处理：降级、熔断、is_failure 计算、JSONL 日志。
"""

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)
import time
from abc import ABC, abstractmethod
from typing import Any

from skill_self_evolution.context import set_trace_id
from skill_self_evolution.fallback import FallbackConfig, FallbackResult, FallbackStrategy
from skill_self_evolution.loader import SkillModule
from skill_self_evolution.logger import SkillLogger
from skill_self_evolution.models import (
    AiReselectionResult,
    AiValidationResult,
    SkillInput,
    SkillOutput,
)


class AiAssistedExecutor(ABC):
    """AI 辅助执行基类。

    子类只需实现 2-3 个抽象方法，框架自动处理流程编排和降级。
    """

    @abstractmethod
    async def ai_validate(
        self,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
    ) -> AiValidationResult:
        """AI 常识判断（correction 角色）。

        Returns:
            AiValidationResult: result=合理/不合理 + reason
        """

    @abstractmethod
    async def ai_reselect(
        self,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
    ) -> AiReselectionResult:
        """AI 重新选择/提取（correction 角色）。

        Returns:
            AiReselectionResult: result=重选值（或"不合理"） + reason
        """

    async def ai_enhance(
        self,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
    ) -> dict | None:
        """AI 增强（enhancement 角色）。默认不增强，子类按需覆盖。"""
        return None

    async def run_correction_flow(
        self,
        skill: SkillModule,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
        fallback: FallbackStrategy,
    ) -> SkillOutput:
        """correction 角色完整流程：验证 → 重选。"""
        t0 = time.monotonic()
        warnings: list[str] = list(rule_output.warnings) if rule_output.warnings else []

        # 1. 熔断检查
        fb_check = fallback.check_before_ai()
        if fb_check.skip_ai:
            warnings.extend(fb_check.warnings)
            elapsed = (time.monotonic() - t0) * 1000
            rule_output.warnings = warnings
            self._log(skill, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
            return rule_output

        # 2. AI 验证
        ai_validation: AiValidationResult | None = None
        try:
            ai_validation = await self.ai_validate(skill_input, rule_output, prompt_config)
            rule_output.ai_validated = True
        except Exception as e:
            logger.warning("Skill [%s] AI 验证异常: %s", skill.skill_name, e)
            fb_result = fallback.on_validate_failure(e)
            warnings.extend(fb_result.warnings)
            if fb_result.skip_ai:
                elapsed = (time.monotonic() - t0) * 1000
                rule_output.ai_validated = False
                rule_output.warnings = warnings
                is_failure = self._is_failure(skill.ai_role, rule_output, None, None)
                self._log(skill, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
                return rule_output

        # 3. 验证不合理 → 重选
        if ai_validation and ai_validation.result == "不合理":
            fb_reselect = fallback.check_before_ai()
            if fb_reselect.skip_ai:
                warnings.extend(fb_reselect.warnings)
                elapsed = (time.monotonic() - t0) * 1000
                is_failure = self._is_failure(skill.ai_role, rule_output, ai_validation, None)
                rule_output.warnings = warnings
                self._log(skill, skill_input, rule_output, ai_validation, None, rule_output, warnings, elapsed)
                return rule_output

            try:
                ai_reselection = await self.ai_reselect(skill_input, rule_output, prompt_config)
                if ai_reselection and ai_reselection.result != "不合理":
                    final_result = ai_reselection.result
                    final_output = SkillOutput(
                        source="ai",
                        result=final_result if isinstance(final_result, dict) else {"value": final_result},
                        ai_validated=True,
                        ai_reselected=True,
                        warnings=warnings,
                    )
                    elapsed = (time.monotonic() - t0) * 1000
                    is_failure = self._is_failure(skill.ai_role, rule_output, ai_validation, ai_reselection)
                    self._log(skill, skill_input, rule_output, ai_validation, ai_reselection, final_output, warnings, elapsed)
                    return final_output
                else:
                    warnings.append("AI 重选后仍不合理")
                    rule_output.ai_reselected = True
            except Exception as e:
                logger.warning("Skill [%s] AI 重选异常: %s", skill.skill_name, e)
                fb_result2 = fallback.on_reselect_failure(e)
                warnings.extend(fb_result2.warnings)

        # 4. 验证合理或重选失败 → 返回规则结果
        rule_output.warnings = warnings
        elapsed = (time.monotonic() - t0) * 1000
        is_failure = self._is_failure(skill.ai_role, rule_output, ai_validation, None)
        self._log(skill, skill_input, rule_output, ai_validation, None, rule_output, warnings, elapsed)
        return rule_output

    async def run_enhancement_flow(
        self,
        skill: SkillModule,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
        fallback: FallbackStrategy,
    ) -> SkillOutput:
        """enhancement 角色流程：规则 + AI 增强。"""
        t0 = time.monotonic()
        warnings: list[str] = list(rule_output.warnings) if rule_output.warnings else []

        fb_check = fallback.check_before_ai()
        if fb_check.skip_ai:
            warnings.extend(fb_check.warnings)
            elapsed = (time.monotonic() - t0) * 1000
            rule_output.warnings = warnings
            self._log(skill, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
            return rule_output

        try:
            ai_result = await self.ai_enhance(skill_input, rule_output, prompt_config)
            merged = {**rule_output.result} if isinstance(rule_output.result, dict) else {}
            if ai_result:
                merged.update(ai_result)
            final_output = SkillOutput(
                source=rule_output.source,
                result=merged,
                ai_validated=True,
                ai_reselected=False,
                warnings=warnings,
            )
            elapsed = (time.monotonic() - t0) * 1000
            self._log(skill, skill_input, rule_output, None, None, final_output, warnings, elapsed)
            return final_output
        except Exception as e:
            logger.warning("Skill [%s] AI 增强异常: %s", skill.skill_name, e)
            elapsed = (time.monotonic() - t0) * 1000
            rule_output.warnings = warnings
            self._log(skill, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
            return rule_output

    @staticmethod
    def _is_failure(
        ai_role: str,
        rule_output: SkillOutput,
        ai_validation: AiValidationResult | None,
        ai_reselection: AiReselectionResult | None,
    ) -> bool:
        """根据 ai_role 计算 is_failure（Pydantic 属性访问）。"""
        if ai_role == "enhancement":
            return False
        if ai_role == "correction":
            if ai_validation and ai_validation.result == "不合理":
                return True
            if ai_reselection and ai_reselection.result == "不合理":
                return True
        return False

    def _log(
        self,
        skill: SkillModule,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        ai_validation: AiValidationResult | None,
        ai_reselection: AiReselectionResult | None,
        final_output: SkillOutput,
        warnings: list[str],
        elapsed_ms: float,
    ) -> None:
        """写入 JSONL 日志（Pydantic LogEntry 校验）。"""
        try:
            log_writer = SkillLogger(skill.skill_name)
            if skill.summarize_input:
                input_summary = skill.summarize_input(skill_input.input_data)
            elif isinstance(skill_input.input_data, dict):
                keys = list(skill_input.input_data.keys())[:5]
                input_summary = {k: str(skill_input.input_data[k])[:100] for k in keys}
            else:
                input_summary = {"type": type(skill_input.input_data).__name__}

            log_writer.log_execution(
                trace_id=skill_input.trace_id or "",
                is_failure=(ai_validation is not None and ai_validation.result == "不合理"),
                input_summary=input_summary,
                rule_output=rule_output.result,
                ai_validation=ai_validation.model_dump() if ai_validation else None,
                ai_reselection=ai_reselection.model_dump() if ai_reselection else None,
                final_output=final_output.result,
                warnings=warnings,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            logger.warning("Skill 日志记录失败: %s", e)
