"""
SkillExecutor — Skill 执行引擎主类。

流程：
1. Pydantic 输入校验
2. trace_id 生成 + contextvars 注入
3. 加载 evolve.toml（获取 ai_role）
4. 加载 skill.md + run.py（磁盘）
5. 加载 rules_config + prompt（MySQL）
6. execute() → AI 常识判断 → 合理则过 / 不合理则 AI 从原始数据重选
7. 写 JSONL 日志（根据 ai_role 自动计算 is_failure）
"""

import asyncio
from loguru import logger
import time
from pathlib import Path
from typing import Any

from skill_self_evolution.context import set_trace_id
from skill_self_evolution.deepseek import CircuitBreaker, DeepSeekClient
from skill_self_evolution.fallback import FallbackConfig, FallbackStrategy
from skill_self_evolution.loader import SkillLoader, SkillModule
from skill_self_evolution.logger import SkillLogger
from skill_self_evolution.models import (
    AiReselectionResult,
    AiValidationResult,
    FallbackConfigModel,
    SkillInput,
    SkillOutput,
)


class SkillExecutor:
    """Skill 执行引擎。

    使用方式：
        executor = SkillExecutor(db_config=...)
        output = await executor.run("nickname-selector", input_data)
    """

    def __init__(
        self,
        skill_base_dir: Path | None = None,
        deepseek_api_key: str = "",
        deepseek_api_base: str = "https://api.deepseek.com/v1",
        deepseek_model: str = "deepseek-v4-flash",
    ):
        """
        Args:
            skill_base_dir: Skill 根目录（默认 backend/config/services/skill/）
            deepseek_api_key: DeepSeek API Key
            deepseek_api_base: DeepSeek API 基础地址
            deepseek_model: 模型名称
        """
        self._loader = SkillLoader(skill_base_dir)
        self._deepseek = DeepSeekClient(
            api_key=deepseek_api_key,
            api_base=deepseek_api_base,
            model=deepseek_model,
        )

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """获取全局熔断器，可在外部调整阈值。"""
        return self._deepseek.circuit_breaker

    def load_skill(self, skill_name: str) -> SkillModule:
        """预加载 Skill（可选，run() 会自动加载）。"""
        return self._loader.load(skill_name)

    async def run(
        self,
        skill_name: str,
        input_data: Any,
        *,
        rules_config: dict | None = None,
        prompt_config: dict | None = None,
        trace_id: str | None = None,
    ) -> SkillOutput:
        """执行 Skill 主流程。

        Args:
            skill_name: Skill 名称（如 "nickname-selector"）
            input_data: 业务输入数据（dict 或 Pydantic model）
            rules_config: rules_config.yaml 解析后的 dict（可选，默认从 MySQL 加载）
            prompt_config: prompt.yaml 解析后的 dict（可选，默认从 MySQL 加载）
            trace_id: 外部传入的 trace_id（可选，未传入则使用 input_data 中的或自动生成）

        Returns:
            SkillOutput: 执行结果
        """
        start_time = time.monotonic()

        # 1. 加载 Skill 模块
        skill = self._loader.load(skill_name)

        # 2. 确定 trace_id
        effective_trace_id = (
            trace_id
            or (getattr(input_data, "trace_id", None))
            or str(__import__("uuid").uuid4())
        )
        set_trace_id(effective_trace_id)

        # 3. 构建 SkillInput（Pydantic 校验入口）
        if isinstance(input_data, dict):
            skill_input = SkillInput(trace_id=effective_trace_id, input_data=input_data)
        else:
            skill_input = SkillInput(trace_id=effective_trace_id, input_data=input_data)

        warnings: list[str] = []

        # 4. 加载降级配置（Pydantic 校验）
        fallback_cfg = self._build_fallback_config(rules_config or {})
        fallback = FallbackStrategy(fallback_cfg, self._deepseek.circuit_breaker)

        # 5. 合并配置传给 execute()
        merged_config = {
            "rules_config": rules_config or {},
            "prompt_config": prompt_config or {},
        }

        # 6. 执行规则阶段
        try:
            rule_output = skill.execute(skill_input, merged_config)
            if not isinstance(rule_output, SkillOutput):
                rule_output = SkillOutput(
                    source="rule",
                    result=rule_output if isinstance(rule_output, dict) else {"value": rule_output},
                )
        except Exception as e:
            logger.exception("Skill [%s] 规则执行异常", skill_name)
            elapsed = (time.monotonic() - start_time) * 1000
            output = SkillOutput(
                source="rule",
                result={"error": str(e)},
                warnings=[f"规则执行异常: {e}"],
            )
            self._log(skill, effective_trace_id, True, skill_input, output, None, None, output, warnings, elapsed)
            return output

        ai_validation: AiValidationResult | None = None
        ai_reselection: AiReselectionResult | None = None

        # 7. AI 处理阶段
        if skill.ai_role == "correction":
            # 纠错型：AI 常识判断 → 不合理则重选
            fb_check = fallback.check_before_ai()
            if fb_check.skip_ai:
                warnings.extend(fb_check.warnings)
                rule_output.ai_validated = False
                rule_output.warnings = warnings
                elapsed = (time.monotonic() - start_time) * 1000
                is_failure = self._compute_is_failure(skill.ai_role, rule_output, None, None)
                self._log(skill, effective_trace_id, is_failure, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
                return rule_output

            # 7a. AI 验证（Pydantic 输出）
            try:
                ai_validation = await self._ai_validate(skill, rule_output, prompt_config)
                rule_output.ai_validated = True
            except Exception as e:
                logger.warning("Skill [%s] AI 验证异常: %s", skill_name, e)
                fb_result = fallback.on_validate_failure(e)
                warnings.extend(fb_result.warnings)
                if fb_result.skip_ai:
                    elapsed = (time.monotonic() - start_time) * 1000
                    rule_output.ai_validated = False
                    rule_output.warnings = warnings
                    is_failure = self._compute_is_failure(skill.ai_role, rule_output, None, None)
                    self._log(skill, effective_trace_id, is_failure, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
                    return rule_output

            # 7b. 若验证不合理 → AI 重选
            if ai_validation and ai_validation.result == "不合理":
                fb_reselect = fallback.check_before_ai()
                if fb_reselect.skip_ai:
                    warnings.extend(fb_reselect.warnings)
                    elapsed = (time.monotonic() - start_time) * 1000
                    is_failure = self._compute_is_failure(skill.ai_role, rule_output, ai_validation, None)
                    self._log(skill, effective_trace_id, is_failure, skill_input, rule_output, ai_validation, None, rule_output, warnings, elapsed)
                    return rule_output

                try:
                    ai_reselection = await self._ai_reselect(skill, skill_input, rule_output, prompt_config)
                    if ai_reselection and ai_reselection.result != "不合理":
                        # 包装 AI 重选结果 — 确保 result 是 dict
                        selected_nickname = ai_reselection.result
                        if isinstance(selected_nickname, dict):
                            reselected_dict = selected_nickname
                        else:
                            reselected_dict = {
                                **rule_output.result,
                                "nickname": str(selected_nickname),
                                "source": "ai",
                            }
                        final_output = SkillOutput(
                            source="ai",
                            result=reselected_dict,
                            ai_validated=True,
                            ai_reselected=True,
                            warnings=warnings,
                        )
                        elapsed = (time.monotonic() - start_time) * 1000
                        is_failure = self._compute_is_failure(skill.ai_role, rule_output, ai_validation, ai_reselection)
                        self._log(skill, effective_trace_id, is_failure, skill_input, rule_output, ai_validation, ai_reselection, final_output, warnings, elapsed)
                        return final_output
                    else:
                        # 重选仍不合理
                        rule_output.ai_reselected = True
                        rule_output.warnings = warnings
                        rule_output.warnings.append("AI 重选后仍不合理")
                except Exception as e:
                    logger.warning("Skill [%s] AI 重选异常: %s", skill_name, e)
                    fb_result2 = fallback.on_reselect_failure(e)
                    warnings.extend(fb_result2.warnings)

            # 验证合理或重选失败 → 返回规则结果
            rule_output.warnings = warnings
            elapsed = (time.monotonic() - start_time) * 1000
            is_failure = self._compute_is_failure(skill.ai_role, rule_output, ai_validation, ai_reselection)
            self._log(skill, effective_trace_id, is_failure, skill_input, rule_output, ai_validation, ai_reselection, rule_output, warnings, elapsed)
            return rule_output

        elif skill.ai_role == "enhancement":
            # 加分型：AI 增强（如语义评分）
            fb_check = fallback.check_before_ai()
            if fb_check.skip_ai:
                warnings.extend(fb_check.warnings)
                rule_output.warnings = warnings
                elapsed = (time.monotonic() - start_time) * 1000
                self._log(skill, effective_trace_id, False, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
                return rule_output

            try:
                ai_result = await self._ai_enhance(skill, skill_input, rule_output, prompt_config)
                merged_result = {**rule_output.result}
                if ai_result:
                    merged_result.update(ai_result)
                final_output = SkillOutput(
                    source=rule_output.source,
                    result=merged_result,
                    ai_validated=True,
                    ai_reselected=False,
                    warnings=warnings,
                )
                elapsed = (time.monotonic() - start_time) * 1000
                self._log(skill, effective_trace_id, False, skill_input, rule_output, None, None, final_output, warnings, elapsed)
                return final_output
            except Exception as e:
                logger.warning("Skill [%s] AI 增强异常: %s", skill_name, e)
                rule_output.warnings = warnings
                elapsed = (time.monotonic() - start_time) * 1000
                self._log(skill, effective_trace_id, False, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
                return rule_output

        else:
            # 未知 ai_role → 纯规则返回
            logger.warning("Skill [%s] 未知 ai_role=%s，纯规则输出", skill_name, skill.ai_role)
            rule_output.warnings = warnings
            elapsed = (time.monotonic() - start_time) * 1000
            self._log(skill, effective_trace_id, False, skill_input, rule_output, None, None, rule_output, warnings, elapsed)
            return rule_output

    # ── 私有方法 ──

    def _build_fallback_config(self, rules_config: dict) -> FallbackConfig:
        """从 rules_config 的 ai_fallback 段构建降级配置（Pydantic 校验）。"""
        af = rules_config.get("ai_fallback", {})
        validated = FallbackConfigModel(
            validate_timeout_seconds=float(af.get("validate_timeout_seconds", 3)),
            reselect_timeout_seconds=float(af.get("reselect_timeout_seconds", 5)),
            max_retries=int(af.get("max_retries", 1)),
            circuit_breaker_threshold=int(af.get("circuit_breaker_threshold", 3)),
            circuit_breaker_cooldown_seconds=float(af.get("circuit_breaker_cooldown_seconds", 60)),
            conservative_mode=bool(af.get("conservative_mode", False)),
        )
        return FallbackConfig(
            validate_timeout_seconds=validated.validate_timeout_seconds,
            reselect_timeout_seconds=validated.reselect_timeout_seconds,
            max_retries=validated.max_retries,
            circuit_breaker_threshold=validated.circuit_breaker_threshold,
            circuit_breaker_cooldown_seconds=validated.circuit_breaker_cooldown_seconds,
            conservative_mode=validated.conservative_mode,
        )

    @staticmethod
    def _compute_is_failure(
        ai_role: str,
        rule_output: SkillOutput,
        ai_validation: AiValidationResult | None,
        ai_reselection: AiReselectionResult | None,
    ) -> bool:
        """根据 ai_role 计算 is_failure 标记。"""
        if ai_role == "enhancement":
            return False

        if ai_role == "correction":
            if ai_validation and ai_validation.result == "不合理":
                return True
            if ai_reselection and ai_reselection.result == "不合理":
                return True
            result = rule_output.result
            if not result or result.get("error"):
                return True

        return False

    async def _ai_validate(
        self,
        skill: SkillModule,
        rule_output: SkillOutput,
        prompt_config: dict | None,
    ) -> AiValidationResult:
        """调用 AI 进行常识验证。返回 Pydantic 模型。"""
        import json as _json, re as _re

        system_prompt = (prompt_config or {}).get("system_prompt", "你是合理性判断专家。")
        user_template = (prompt_config or {}).get("user_template_validate", "请判断以下结果是否合理：{{result}}")

        nick = rule_output.result.get("nickname", "")
        candidates = _json.dumps(rule_output.result.get("candidates", [])[:5], ensure_ascii=False)
        user_message = self._render_template(user_template, {"result": nick, "candidates": candidates})

        resp = await self._deepseek.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        content = resp.content.strip()

        # 尝试 JSON 解析
        for candidate in [content]:
            if candidate.startswith("```"):
                lines = candidate.split("\n")
                end = -1 if lines[-1].strip() == "```" else len(lines)
                start = 1 if lines[0].startswith("```json") or lines[0].startswith("```") else 0
                candidate = "\n".join(lines[start:end])
            try:
                parsed = _json.loads(candidate)
                return AiValidationResult(
                    result=parsed.get("result", "合理"),
                    reason=parsed.get("reason", ""),
                )
            except (_json.JSONDecodeError, ValueError):
                continue

        # 非 JSON 回退：先检查"不合理"，避免"不合理"中的"合理"被误匹配
        if _re.search(r"(不合理|unreasonable|invalid|不是)", content, _re.IGNORECASE):
            return AiValidationResult(result="不合理", reason=content[:120])
        if _re.search(r"(合理|reasonable|valid)", content, _re.IGNORECASE):
            return AiValidationResult(result="合理", reason=content[:120])
        return AiValidationResult(result="合理", reason="no explicit judgement")

    async def _ai_reselect(
        self,
        skill: SkillModule,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
    ) -> AiReselectionResult:
        """调用 AI 重新选择/提取。返回 Pydantic 模型。"""
        import json as _json2

        system_prompt = (prompt_config or {}).get("system_prompt", "你是信息提取专家。")
        user_template = (prompt_config or {}).get("user_template_reselect", "请从以下数据中重新选择：{{candidates}}")

        candidates_list = rule_output.result.get("candidates", []) if isinstance(rule_output.result, dict) else []
        candidates_json = _json2.dumps(candidates_list, ensure_ascii=False)

        user_message = self._render_template(
            user_template,
            {"candidates": candidates_json},
        )

        response = await self._deepseek.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=1024,
        )

        return AiReselectionResult(
            result=str(response.get("result", "")),
            reason=str(response.get("reason", "")),
        )

    async def _ai_enhance(
        self,
        skill: SkillModule,
        skill_input: SkillInput,
        rule_output: SkillOutput,
        prompt_config: dict | None,
    ) -> dict | None:
        """调用 AI 增强规则结果（enhancement 角色）。"""
        system_prompt = (prompt_config or {}).get("system_prompt", "你是评分增强专家。")
        user_template = (prompt_config or {}).get("user_template", "请根据以下信息评分：{{input_data}}")

        user_message = self._render_template(user_template, {"input_data": skill_input.input_data})

        response = await self._deepseek.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        return response

    @staticmethod
    def _render_template(template: str, context: dict) -> str:
        """简单 Jinja2 风格模板渲染（仅支持 {{var}}）。"""
        result = template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            if isinstance(value, dict):
                import json
                result = result.replace(placeholder, json.dumps(value, ensure_ascii=False))
            else:
                result = result.replace(placeholder, str(value))
        return result

    def _log(
        self,
        skill: SkillModule,
        trace_id: str,
        is_failure: bool,
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

            # 生成 input_summary
            if skill.summarize_input:
                input_summary = skill.summarize_input(skill_input.input_data)
            elif isinstance(skill_input.input_data, dict):
                keys = list(skill_input.input_data.keys())[:5]
                input_summary = {k: str(skill_input.input_data[k])[:100] for k in keys}
            else:
                input_summary = {"type": type(skill_input.input_data).__name__}

            # 通过 log_execution 统一校验（LogEntry Pydantic 模型）后写入
            log_writer.log_execution(
                trace_id=trace_id,
                is_failure=is_failure,
                input_summary=input_summary,
                rule_output=rule_output.result,
                ai_validation=ai_validation.model_dump() if ai_validation else None,
                ai_reselection=ai_reselection.model_dump() if ai_reselection else None,
                final_output=final_output.result,
                warnings=warnings,
                elapsed_ms=round(elapsed_ms, 1),
            )
        except Exception as e:
            logger.warning("Skill 日志记录失败: %s", e)
