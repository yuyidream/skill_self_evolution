"""
SkillExecutor — 通用执行引擎。

调用方传入候选人 JSON 文件路径 + rules_config + prompt_config，
框架负责：Pydantic 校验 → 规则引擎过滤 → AI 验证 → 重选 → JSONL 日志。

使用方式：
    executor = SkillExecutor(skill_name="nickname_selector", ai_role="correction")
    result = await executor.run(
        candidates_path="/tmp/candidates.json",
        rules_config=...,
        prompt_config=...,
    )
"""

import json as _json
import re as _re
import time
from pathlib import Path
from typing import Any

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)

from skill_self_evolution.context import set_trace_id
from skill_self_evolution.deepseek import CircuitBreaker, DeepSeekClient
from skill_self_evolution.fallback import FallbackConfig, FallbackStrategy
from skill_self_evolution.logger import SkillLogger
from skill_self_evolution.models import (
    AiReselectionResult,
    AiValidationResult,
    BlockCandidate,
    CandidateInput,
    FallbackConfigModel,
    OcrBlock,
    PromptConfigModel,
    RuleResultDict,
    RulesConfigModel,
    SessionInput,
    SkillOutput,
)
from skill_self_evolution.rule_runner import run_rejection_rules


class SkillExecutor:
    """通用执行引擎。

    参数：
        skill_name: 日志标识
        ai_role: "correction"（纠错型，默认）| "enhancement"（增强型）
    """

    def __init__(
        self,
        *,
        skill_name: str = "default",
        ai_role: str = "correction",
        deepseek_api_key: str = "",
        deepseek_api_base: str = "https://api.deepseek.com/v1",
        deepseek_model: str = "deepseek-v4-pro",
        enrich_failure: "Callable[[str], dict[str, str]] | None" = None,
        version_mgr: "Any | None" = None,
    ):
        """
        Args:
            enrich_failure: 可选回调，入参 session_dir 路径，返回 dict[str, str]。
                           返回的键值对会注入到 JSONL 的 input_summary 中，
                           供 Evolver 分析时传递 session 文件内容给 LLM。
            version_mgr: ConfigVersionManager 实例（可选），传入后执行日志会同时写入 MySQL。
        """
        self.skill_name = skill_name
        self.ai_role = ai_role
        self._enrich_failure = enrich_failure
        self._enrichment: dict[str, str] = {}
        self._version_mgr = version_mgr

        self._deepseek = DeepSeekClient(
            api_key=deepseek_api_key,
            api_base=deepseek_api_base,
            model=deepseek_model,
        )

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        return self._deepseek.circuit_breaker

    # ── 主入口 ──

    async def run(
        self,
        candidates_path: str = "",
        *,
        session_dir: str = "",
        rules_config: dict | None = None,
        prompt_config: dict | None = None,
        trace_id: str | None = None,
    ) -> SkillOutput:
        """执行完整管线。

        Args:
            candidates_path: 候选人 JSON 文件路径，格式 {"candidates": [...]}
            session_dir: session 目录路径（含 debug_session_derived.json + speaker JSON）
                        传入后从 session 目录自动加载候选块，
                        优先级高于 candidates_path
            rules_config: rules_config.yaml 解析后的 dict
            prompt_config: prompt.yaml 解析后的 dict
            trace_id: 外部 trace_id
        """
        start_time = time.monotonic()

        # 1. trace_id
        effective_trace_id = trace_id or str(__import__("uuid").uuid4())
        set_trace_id(effective_trace_id)

        warnings: list[str] = []

        data_source_label = "session_dir" if session_dir else ("candidates_path" if candidates_path else "none")
        # 从 session 目录路径中提取真实日期 (YYYY-MM-DD)
        import re
        _sd_match = re.search(r'/(\d{8})/', session_dir) if session_dir else None
        _session_date = f"{_sd_match.group(1)[:4]}-{_sd_match.group(1)[4:6]}-{_sd_match.group(1)[6:8]}" if _sd_match else ""

        logger.info(
            "executor.start",
            skill_name=self.skill_name,
            ai_role=self.ai_role,
            source=data_source_label,
            trace_id=effective_trace_id,
        )

        # 2. Pydantic 入口校验 — rules_config / prompt_config 格式不对立刻报错
        try:
            if rules_config is not None:
                rules_config = RulesConfigModel.model_validate(rules_config).model_dump()
            if prompt_config is not None:
                prompt_config = PromptConfigModel.model_validate(prompt_config).model_dump()
        except Exception as e:
            logger.exception("executor.config_validation_failed", skill_name=self.skill_name, error=str(e))
            elapsed = (time.monotonic() - start_time) * 1000
            output = SkillOutput(
                source="rule",
                result={"error": f"配置校验失败: {e}"},
                warnings=[f"配置校验失败: {e}"],
            )
            self._log(effective_trace_id, True, False, candidates_path or session_dir, output, None, None, output, [f"配置校验失败: {e}"], elapsed)
            return output

        # 3. 降级配置
        fallback_cfg = self._build_fallback_config(rules_config or {})
        fallback = FallbackStrategy(fallback_cfg, self._deepseek.circuit_breaker)

        # 4. 规则阶段：加载候选池 → 过滤
        try:
            if session_dir:
                # 从 session 目录加载候选块
                candidates = self._load_candidates_from_session(session_dir)
                data_source = session_dir
                # 调用 enrich_failure 回调，加载 session 文件内容供 Evolver 分析
                self._enrichment = {}
                if self._enrich_failure:
                    try:
                        self._enrichment = self._enrich_failure(session_dir)
                        logger.info(
                            "executor.enrich_failure_ok",
                            skill_name=self.skill_name,
                            session_dir=session_dir,
                            injected_keys=list(self._enrichment.keys()),
                            injected_count=len(self._enrichment),
                        )
                    except Exception as e:
                        logger.warning("executor.enrich_failure_error", skill_name=self.skill_name, error=str(e))
            else:
                candidates = self._load_candidates(candidates_path)
                data_source = candidates_path

            rejection_rules = (rules_config or {}).get("rejection_rules", [])
            filtered = self._apply_rules(candidates, rejection_rules)
            rule_result = RuleResultDict(
                candidates=filtered,
                result=filtered[0] if filtered else "",
            ).model_dump()
            rule_output = SkillOutput(source="rule", result=rule_result)
            logger.info(
                "executor.rule_stage_ok",
                skill_name=self.skill_name,
                candidates_count=len(candidates),
                filtered_count=len(filtered),
                result=str(rule_result.get("result", ""))[:80],
            )
        except Exception as e:
            logger.exception("executor.rule_stage_error", skill_name=self.skill_name)
            elapsed = (time.monotonic() - start_time) * 1000
            output = SkillOutput(
                source="rule",
                result={"error": str(e)},
                warnings=[f"规则阶段异常: {e}"],
            )
            self._log(effective_trace_id, True, False, candidates_path or session_dir, output, None, None, output, warnings, elapsed, session_date=_session_date)
            return output

        ai_validation: AiValidationResult | None = None
        ai_reselection: AiReselectionResult | None = None

        # 5. AI 阶段
        if self.ai_role == "correction":
            fb_check = fallback.check_before_ai()
            if fb_check.skip_ai:
                warnings.extend(fb_check.warnings)
                rule_output.ai_validated = False
                rule_output.warnings = warnings
                elapsed = (time.monotonic() - start_time) * 1000
                is_failure, no_valid = self._compute_is_failure(rule_output, None, None)
                self._log(effective_trace_id, is_failure, no_valid, data_source, rule_output, None, None, rule_output, warnings, elapsed, session_date=_session_date)
                return rule_output

            try:
                ai_validation = await self._ai_validate(rule_output, prompt_config)
                rule_output.ai_validated = True
                logger.info(
                    "executor.ai_validation_ok",
                    skill_name=self.skill_name,
                    result=ai_validation.result if ai_validation else "N/A",
                    reason=(ai_validation.reason if ai_validation else "")[:120],
                )
            except Exception as e:
                logger.warning("executor.ai_validation_error", skill_name=self.skill_name, error=str(e))
                fb_result = fallback.on_validate_failure(e)
                warnings.extend(fb_result.warnings)
                if fb_result.skip_ai:
                    elapsed = (time.monotonic() - start_time) * 1000
                    rule_output.ai_validated = False
                    rule_output.warnings = warnings
                    is_failure, no_valid = self._compute_is_failure(rule_output, None, None)
                    self._log(effective_trace_id, is_failure, no_valid, data_source, rule_output, None, None, rule_output, warnings, elapsed, session_date=_session_date)
                    return rule_output

            if ai_validation and ai_validation.result == "不合理":
                fb_reselect = fallback.check_before_ai()
                if fb_reselect.skip_ai:
                    warnings.extend(fb_reselect.warnings)
                    elapsed = (time.monotonic() - start_time) * 1000
                    is_failure, no_valid = self._compute_is_failure(rule_output, ai_validation, None)
                    self._log(effective_trace_id, is_failure, no_valid, data_source, rule_output, ai_validation, None, rule_output, warnings, elapsed, session_date=_session_date)
                    return rule_output

                try:
                    ai_reselection = await self._ai_reselect(rule_output, prompt_config)
                    logger.info(
                        "executor.ai_reselection_ok",
                        skill_name=self.skill_name,
                        result=str(ai_reselection.result)[:80] if ai_reselection else "N/A",
                    )
                    if ai_reselection and ai_reselection.result != "不合理":
                        selected = ai_reselection.result
                        if isinstance(selected, dict):
                            reselected_dict = selected
                        else:
                            reselected_dict = {**rule_output.result, "result": str(selected), "source": "ai"}
                        final_output = SkillOutput(
                            source="ai",
                            result=reselected_dict,
                            ai_validated=True,
                            ai_reselected=True,
                            warnings=warnings,
                        )
                        elapsed = (time.monotonic() - start_time) * 1000
                        is_failure, no_valid = self._compute_is_failure(rule_output, ai_validation, ai_reselection)
                        self._log(effective_trace_id, is_failure, no_valid, data_source, rule_output, ai_validation, ai_reselection, final_output, warnings, elapsed, session_date=_session_date)
                        return final_output
                    else:
                        rule_output.ai_reselected = True
                        rule_output.warnings = warnings
                        rule_output.warnings.append("AI 重选后仍不合理")
                except Exception as e:
                    logger.warning("executor.ai_reselection_error", skill_name=self.skill_name, error=str(e))
                    fb_result2 = fallback.on_reselect_failure(e)
                    warnings.extend(fb_result2.warnings)

            rule_output.warnings = warnings
            elapsed = (time.monotonic() - start_time) * 1000
            is_failure, no_valid = self._compute_is_failure(rule_output, ai_validation, ai_reselection)
            self._log(effective_trace_id, is_failure, no_valid, data_source, rule_output, ai_validation, ai_reselection, rule_output, warnings, elapsed, session_date=_session_date)
            return rule_output

        elif self.ai_role == "enhancement":
            fb_check = fallback.check_before_ai()
            if fb_check.skip_ai:
                warnings.extend(fb_check.warnings)
                rule_output.warnings = warnings
                elapsed = (time.monotonic() - start_time) * 1000
                self._log(effective_trace_id, False, False, data_source, rule_output, None, None, rule_output, warnings, elapsed, session_date=_session_date)
                return rule_output

            try:
                ai_result = await self._ai_enhance(rule_output, prompt_config)
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
                self._log(effective_trace_id, False, False, data_source, rule_output, None, None, final_output, warnings, elapsed, session_date=_session_date)
                return final_output
            except Exception as e:
                logger.warning("executor.ai_enhancement_error", skill_name=self.skill_name, error=str(e))
                rule_output.warnings = warnings
                elapsed = (time.monotonic() - start_time) * 1000
                self._log(effective_trace_id, False, False, data_source, rule_output, None, None, rule_output, warnings, elapsed, session_date=_session_date)
                return rule_output

        else:
            logger.warning("executor.unknown_ai_role", skill_name=self.skill_name, ai_role=self.ai_role)
            rule_output.warnings = warnings
            elapsed = (time.monotonic() - start_time) * 1000
            self._log(effective_trace_id, False, False, data_source, rule_output, None, None, rule_output, warnings, elapsed, session_date=_session_date)
            return rule_output

    # ── 候选池处理 ──

    @staticmethod
    def _load_candidates(path: str) -> list[str]:
        """读取候选人 JSON 文件并做 Pydantic 校验。"""
        if not path:
            return []
        data = _json.loads(Path(path).read_text(encoding="utf-8"))
        validated = CandidateInput.model_validate(data)
        return validated.candidates

    @staticmethod
    def _load_candidates_from_session(session_dir: str) -> list[str]:
        """从 session 目录读取候选昵称文本。

        读取顺序：
        1. debug_session_derived.json → 提取所有 class="nickname_candidate" 的 text
        2. speaker JSON → 读取 speaker_binding_raw 作为管线选中昵称（置顶）

        Returns:
            list[str]: 候选昵称文本列表（管线选中昵称排在首位）
        """
        session_path = Path(session_dir)
        if not session_path.is_dir():
            return []

        candidates: list[str] = []
        pipeline_selected: str = ""

        # 1. 读取 debug_session_derived.json
        debug_path = session_path / "debug_session_derived.json"
        if debug_path.exists():
            try:
                debug_data = _json.loads(debug_path.read_text(encoding="utf-8"))
                screenshots = debug_data.get("screenshots", []) if isinstance(debug_data, dict) else []
                if not screenshots and isinstance(debug_data, list):
                    screenshots = debug_data

                for scr in screenshots:
                    blocks = scr.get("blocks", []) if isinstance(scr, dict) else []
                    for blk in blocks:
                        if not isinstance(blk, dict):
                            continue
                        if blk.get("class") == "nickname_candidate":
                            txt = blk.get("text", "").strip()
                            if txt and txt not in candidates:
                                candidates.append(txt)
            except Exception:
                pass

        # 2. 读取 speaker JSON 获取管线选中昵称
        speaker_files = sorted(session_path.glob("*.json"))
        for sf in speaker_files:
            if sf.name in ("metadata.json", "debug_session_derived.json", "customer_metadata.json"):
                continue
            try:
                data = _json.loads(sf.read_text(encoding="utf-8"))
                if data.get("other", {}).get("md5_duplicate", False):
                    continue
                if isinstance(data, dict):
                    md5_sp = data.get("md5_spokesperson", {})
                    if isinstance(md5_sp, dict):
                        binding = md5_sp.get("speaker_binding_raw", "")
                        if isinstance(binding, str) and binding.strip():
                            pipeline_selected = binding.strip()
                        elif isinstance(binding, dict):
                            pipeline_selected = str(binding.get("result", ""))
                        elif isinstance(binding, list) and binding:
                            pipeline_selected = str(binding[0])
            except Exception:
                continue

        # 3. 管线选中昵称置顶
        if pipeline_selected:
            if pipeline_selected in candidates:
                candidates.remove(pipeline_selected)
            candidates.insert(0, pipeline_selected)

        return candidates

    @staticmethod
    def _apply_rules(candidates: list[str], rejection_rules: list[dict]) -> list[str]:
        """对每条候选文本执行 rule_runner 过滤。"""
        filtered: list[str] = []
        for text in candidates:
            result = run_rejection_rules(str(text), rejection_rules)
            if result is not None:
                filtered.append(result)
        return list(dict.fromkeys(filtered))  # 去重保序

    # ── AI 方法 ──

    async def _ai_validate(self, rule_output: SkillOutput, prompt_config: dict | None) -> AiValidationResult:
        system_prompt = (prompt_config or {}).get("system_prompt", "你是合理性判断专家。")
        user_template = (prompt_config or {}).get("user_template_validate", "请判断以下结果是否合理：{{result}}")

        nickname = rule_output.result.get("result", "")
        candidates = _json.dumps(rule_output.result.get("candidates", [])[:5], ensure_ascii=False)
        user_message = self._render_template(user_template, {"result": nickname, "candidates": candidates})

        resp = await self._deepseek.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
            max_tokens=256,
        )
        content = resp.content.strip()

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

        if _re.search(r"(不合理|unreasonable|invalid|不是)", content, _re.IGNORECASE):
            return AiValidationResult(result="不合理", reason=content[:120])
        if _re.search(r"(合理|reasonable|valid)", content, _re.IGNORECASE):
            return AiValidationResult(result="合理", reason=content[:120])
        return AiValidationResult(result="合理", reason="no explicit judgement")

    async def _ai_reselect(self, rule_output: SkillOutput, prompt_config: dict | None) -> AiReselectionResult:
        system_prompt = (prompt_config or {}).get("system_prompt", "你是信息提取专家。")
        user_template = (prompt_config or {}).get("user_template_reselect", "请从以下数据中重新选择：{{candidates}}")

        candidates_list = rule_output.result.get("candidates", []) if isinstance(rule_output.result, dict) else []
        candidates_json = _json.dumps(candidates_list, ensure_ascii=False)
        user_message = self._render_template(user_template, {"candidates": candidates_json})

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

    async def _ai_enhance(self, rule_output: SkillOutput, prompt_config: dict | None) -> dict | None:
        system_prompt = (prompt_config or {}).get("system_prompt", "你是评分增强专家。")
        user_template = (prompt_config or {}).get("user_template", "请根据以下信息评分：{{input_data}}")
        user_message = self._render_template(user_template, {"input_data": rule_output.result})

        response = await self._deepseek.chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        return response

    # ── 私有方法 ──

    def _build_fallback_config(self, rules_config: dict) -> FallbackConfig:
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

    def _compute_is_failure(
        self,
        rule_output: SkillOutput,
        ai_validation: AiValidationResult | None,
        ai_reselection: AiReselectionResult | None,
    ) -> tuple[bool, bool]:
        """Return ``(is_failure, no_valid_alternative)``.

        PRD §B.1: ``no_valid_alternative=True`` when AI reselection returned
        "不合理" — meaning no reasonable alternative exists in the candidate pool
        (the declarative rules incorrectly filtered out the correct answer).
        """
        if self.ai_role == "enhancement":
            return False, False
        if self.ai_role == "correction":
            is_fail = False
            no_valid = False
            if ai_validation and ai_validation.result == "不合理":
                is_fail = True
                if ai_reselection and ai_reselection.result == "不合理":
                    no_valid = True
            if ai_reselection and ai_reselection.result == "不合理":
                is_fail = True
                no_valid = True
            result = rule_output.result
            if not result or result.get("error"):
                is_fail = True
            return is_fail, no_valid
        return False, False

    @staticmethod
    def _render_template(template: str, context: dict) -> str:
        result = template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            if isinstance(value, dict):
                result = result.replace(placeholder, _json.dumps(value, ensure_ascii=False))
            else:
                result = result.replace(placeholder, str(value))
        return result

    def _log(
        self,
        trace_id: str,
        is_failure: bool,
        no_valid_alternative: bool,
        candidates_source: str,
        rule_output: SkillOutput,
        ai_validation: AiValidationResult | None,
        ai_reselection: AiReselectionResult | None,
        final_output: SkillOutput,
        warnings: list[str],
        elapsed_ms: float,
        session_date: str = "",
    ) -> None:
        try:
            log_writer = SkillLogger(self.skill_name, version_mgr=self._version_mgr)
            input_summary: dict[str, Any] = {"candidates_path": candidates_source}
            if self._enrichment:
                input_summary.update(self._enrichment)

            log_writer.log_execution(
                trace_id=trace_id,
                is_failure=is_failure,
                no_valid_alternative=no_valid_alternative,
                input_summary=input_summary,
                rule_output=rule_output.result,
                ai_validation=ai_validation.model_dump() if ai_validation else None,
                ai_reselection=ai_reselection.model_dump() if ai_reselection else None,
                final_output=final_output.result,
                warnings=warnings,
                elapsed_ms=round(elapsed_ms, 1),
                session_date=session_date,
            )
            logger.info(
                "executor.jsonl_written",
                skill_name=self.skill_name,
                trace_id=trace_id,
                is_failure=is_failure,
                no_valid_alternative=no_valid_alternative,
                elapsed_ms=round(elapsed_ms, 1),
                enrich_keys=list(self._enrichment.keys()) if self._enrichment else [],
            )
        except Exception as e:
            logger.warning("executor.jsonl_log_error", error=str(e))
