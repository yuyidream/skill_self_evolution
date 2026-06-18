"""
Evolver 离线进化器 — 读 JSONL 日志 → DeepSeek 分析失败模式 → 生成优化提案 → 自动写入或回滚。

调用方注入 execute_fn / benchmark_fn / ai_role 等可覆盖项，
框架只在 evolve() 中编排进化流程。

使用方式：
    evolver = Evolver(
        skill_name="my-task",
        execute_fn=my_execute,
        benchmark_fn=my_benchmark,
        ai_role="correction",
        evolution_mode="both",
        evolve_toml={"evolve": {"auto_modify": {"rules_config": {"mode": "full"}}}},
        deepseek=DeepSeekClient(...),
        version_mgr=ConfigVersionManager(...),
    )
    proposal = await evolver.evolve(dry_run=False)
"""

import json
from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)
import os
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Literal

from ruamel.yaml import YAML

yaml_safe = YAML(typ='safe')
yaml_rt = YAML()
yaml_rt.default_flow_style = False


def _yaml_dump_str(data: Any) -> str:
    buf = StringIO()
    yaml_rt.dump(data, buf)
    return buf.getvalue()


from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.logger import _get_log_dir
from skill_self_evolution.models import EvolveProposalModel, EvolvePromptYamlModel, EvolveTomlModel
from skill_self_evolution.yaml_lint import lint_and_fix_yaml

_BEIJING_TZ = timezone(timedelta(hours=8))
_FRAMEWORK_DEFAULTS = Path(__file__).resolve().parents[2] / "defaults"


def _yesterday_str() -> str:
    return (datetime.now(_BEIJING_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


# ── 默认函数 ──

def _default_execute(skill_input, config: dict):
    raise NotImplementedError("Evolver needs execute_fn")


def _default_benchmark(executor) -> tuple[int, int, list]:
    return 0, 0, []


# ── EvolveProposal ──

class EvolveProposal:
    """一次进化分析产生的提案。"""

    def __init__(self):
        self.rules_changes: dict[str, Any] = {}
        self.prompt_changes: dict[str, Any] = {}
        self.rules_text: str | None = None
        self.prompt_text: str | None = None
        self.analysis_raw: str = ""
        self.failure_count: int = 0
        self.training_set_size: int = 0
        self.validation_set_size: int = 0
        self.benchmark_before: tuple[int, int, list] = (0, 0, [])
        self.benchmark_after: tuple[int, int, list] = (0, 0, [])
        self.applied: bool = False
        self.rolled_back: bool = False

    def to_model(self) -> EvolveProposalModel:
        return EvolveProposalModel(
            rules_changes=self.rules_changes,
            prompt_changes=self.prompt_changes,
            rules_text=self.rules_text,
            prompt_text=self.prompt_text,
            analysis_raw=self.analysis_raw,
            failure_count=self.failure_count,
            training_set_size=self.training_set_size,
            validation_set_size=self.validation_set_size,
            applied=self.applied,
            rolled_back=self.rolled_back,
        )


# ── Evolver ──

class Evolver:
    """离线进化引擎 — 调用方注入所有业务函数，框架编排进化流程。"""

    def __init__(
        self,
        *,
        skill_name: str = "default",
        execute_fn: Callable | None = None,
        benchmark_fn: Callable[..., tuple[int, int, list]] | None = None,
        ai_role: str = "correction",
        evolution_mode: Literal["both", "rules_only", "prompt_only"] = "both",
        evolve_toml: dict[str, Any] | None = None,
        evolve_prompt_yaml: dict[str, Any] | None = None,
        log_dir: Path | None = None,
        rules_config_disk_path: Path | None = None,
        deepseek: DeepSeekClient | None = None,
        version_mgr=None,
        feedback_max_rounds: int = 5,
    ):
        """
        Args:
            skill_name: 日志/标识名
            execute_fn: 规则执行函数
            benchmark_fn: 基准测试函数  (evolver) -> (pass, total, failures)
            ai_role: "correction" | "enhancement"
            evolution_mode: "both" | "rules_only" | "prompt_only"
            evolve_toml: evolve.toml 解析后的 dict（含 auto_modify / guard）
            evolve_prompt_yaml: AI 分析用的提示词模板 dict
            log_dir: JSONL 日志目录（默认从 skill_name 推导）
            rules_config_disk_path: rules_config.yaml 磁盘路径（用于同步）
            deepseek: DeepSeek 客户端
            version_mgr: ConfigVersionManager（MySQL 读写）
            feedback_max_rounds: 注入到分析 prompt 的历史反馈轮数（默认 5）
        """
        self.skill_name = skill_name
        self.execute_fn = execute_fn or _default_execute
        self.benchmark_fn = benchmark_fn or _default_benchmark
        self.ai_role = ai_role
        self.evolution_mode = evolution_mode
        self._feedback_max_rounds = feedback_max_rounds

        # ── Pydantic 入口校验 ──
        if evolve_toml is not None:
            EvolveTomlModel.model_validate(evolve_toml)
        if evolve_prompt_yaml is not None:
            EvolvePromptYamlModel.model_validate(evolve_prompt_yaml)

        self.evolve_toml = evolve_toml or {}
        self.evolve_prompt_yaml = evolve_prompt_yaml or {}
        self._log_dir = Path(log_dir) if log_dir else None
        self._rules_disk_path = rules_config_disk_path
        self._deepseek = deepseek
        self._version_mgr = version_mgr

    @property
    def log_dir(self) -> Path:
        if self._log_dir:
            return self._log_dir
        return _get_log_dir(self.skill_name)

    def _load_failure_logs(self, date_str: str | None = None) -> list[dict]:
        target_date = date_str or _yesterday_str()
        log_path = self.log_dir / f"{target_date}.jsonl"

        if not log_path.exists():
            logger.info("Evolver [%s] 日志文件不存在: %s", self.skill_name, log_path)
            return []

        failures = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("is_failure", False):
                            failures.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Evolver [%s] 日志读取失败: %s", self.skill_name, e)
            return []

        logger.info("Evolver [%s] 读取 %d 条 is_failure 记录", self.skill_name, len(failures))
        return failures

    def _build_training_set(self, exclude_date: str | None = None) -> tuple[list[dict], int]:
        """构建训练集：历史所有 is_failure=true，排除 exclude_date。

        PRD §B.1：训练集 = 历史失败 - 当天新增失败（防循环自证）。

        Returns:
            (training_entries, excluded_count): 训练样本列表 + 当天排除数
        """
        target_date = exclude_date or _yesterday_str()
        all_failures: list[dict] = []
        excluded = 0
        scanned = 0

        if not self.log_dir.exists():
            logger.info("Evolver [%s] log_dir 不存在: %s，训练集为空", self.skill_name, self.log_dir)
            return [], 0

        for jsonl_file in sorted(self.log_dir.glob("*.jsonl")):
            try:
                basename = jsonl_file.name
                # 文件名格式: YYYY-MM-DD.jsonl
                if not basename.endswith(".jsonl"):
                    continue
                date_part = basename[:-6]  # strip ".jsonl"

                with open(jsonl_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            if not entry.get("is_failure", False):
                                continue
                            scanned += 1
                            if date_part == target_date:
                                excluded += 1
                            else:
                                all_failures.append(entry)
                        except json.JSONDecodeError:
                            continue
            except Exception as e:
                logger.warning("Evolver [%s] 训练集读取失败 %s: %s", self.skill_name, jsonl_file, e)

        logger.info(
            "Evolver [%s] 训练集构建完成: total_scanned=%d, training=%d, excluded_today=%d",
            self.skill_name, scanned, len(all_failures), excluded,
        )
        return all_failures, excluded

    def _run_benchmark(self) -> tuple[int, int, list]:
        try:
            return self.benchmark_fn(self)
        except Exception as e:
            logger.warning("Evolver [%s] benchmark 执行失败: %s", self.skill_name, e)
            return 0, 0, [str(e)]

    def _get_golden_set_size(self) -> int:
        """查询 Golden set 大小（nickname_golden_label 表）。"""
        try:
            if self._version_mgr and hasattr(self._version_mgr, "_cursor"):
                self._version_mgr._cursor.execute("SELECT COUNT(*) FROM nickname_golden_label")
                row = self._version_mgr._cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception:
            pass
        return 0

    async def _analyze_failures(
        self,
        failures: list[dict],
        current_rules: str,
        current_prompt: str,
    ) -> dict:
        if not self._deepseek:
            logger.warning("Evolver [%s] DeepSeek 客户端未配置，无法分析", self.skill_name)
            return {}

        # ── 根据 evolution_mode 选择默认模板 ──
        prompt_cfg = self.evolve_prompt_yaml or {}
        if not prompt_cfg:
            if self.evolution_mode == "prompt_only":
                defaults_path = _FRAMEWORK_DEFAULTS / "evolve_prompt_only.yaml"
            else:
                defaults_path = _FRAMEWORK_DEFAULTS / "evolve_prompt.yaml"
            if defaults_path.exists():
                prompt_cfg = yaml_safe.load(defaults_path.read_text(encoding="utf-8")) or {}

        system = prompt_cfg.get("system", "你是配置优化专家。")
        template = prompt_cfg.get(
            "analyze_template",
            "分析以下失败案例：\n{{failure_logs}}\n输出优化建议 JSON。",
        )

        # ── 加载反馈历史 ──
        feedback_text = self._load_feedback_history()

        failure_texts = []
        for f in failures[:20]:
            line = json.dumps({
                "input_summary": f.get("input_summary", {}),
                "rule_output": f.get("rule_output", {}),
                "ai_validation": f.get("ai_validation"),
                "ai_reselection": f.get("ai_reselection"),
                "final_output": f.get("final_output", {}),
                "warnings": f.get("warnings", []),
            }, ensure_ascii=False, indent=2)
            failure_texts.append(line)

        user_message = template
        user_message = user_message.replace("{{skill_name}}", self.skill_name)
        user_message = user_message.replace("{{feedback_history}}", feedback_text)
        user_message = user_message.replace("{{current_rules_config}}", current_rules or "（空）")
        user_message = user_message.replace("{{current_prompt}}", current_prompt or "（空）")
        user_message = user_message.replace("{{failure_logs}}", "\n---\n".join(failure_texts))

        try:
            response = await self._deepseek.chat_json(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=4096,
            )
            return response
        except Exception as e:
            logger.warning("Evolver [%s] 分析请求失败: %s", self.skill_name, e)
            return {}

    async def evolve(
        self,
        min_failure_samples: int = 10,
        dry_run: bool = True,
        date_str: str | None = None,
    ) -> EvolveProposal | None:
        """执行一轮进化。

        Args:
            min_failure_samples: 最少失败样本数
            dry_run: True=仅分析不写入，False=自动写入 MySQL
            date_str: 日期字符串，默认昨天
        """
        mode = self.evolution_mode
        logger.info(
            "Evolver [%s] 开始进化分析 (mode=%s, min_failure_samples=%d, dry_run=%s)",
            self.skill_name, mode, min_failure_samples, dry_run,
        )

        proposal = EvolveProposal()

        # 1. enhancement 角色不触发进化
        if self.ai_role == "enhancement":
            logger.info("Evolver [%s] ai_role=enhancement，不触发进化", self.skill_name)
            return None

        # 2. 读当天 JSONL（仅用于阈值判断）
        today_failures = self._load_failure_logs(date_str)
        proposal.failure_count = len(today_failures)

        if len(today_failures) < min_failure_samples:
            logger.info(
                "Evolver [%s] 失败样本不足 (got=%d, need=%d)，跳过进化",
                self.skill_name, len(today_failures), min_failure_samples,
            )
            return proposal

        # 2.5 构建训练集（历史失败 - 当天）和验证集（Golden set）
        training_set, excluded_today = self._build_training_set(date_str)
        validation_size = self._get_golden_set_size() if self._version_mgr else 0
        logger.info(
            "Evolver [%s] 训练集=%d 条, 验证集(Golden set)=%d 条, 当天排除=%d 条",
            self.skill_name, len(training_set), validation_size, excluded_today,
        )
        proposal.training_set_size = len(training_set)
        proposal.validation_set_size = validation_size

        # ── 进化轮次号 ──
        evolution_round = 1
        if self._version_mgr:
            try:
                self._version_mgr.ensure_feedback_table()
            except Exception as e:
                logger.debug("Evolver [%s] 反馈表创建跳过: %s", self.skill_name, e)
            evolution_round = self._version_mgr.get_next_evolution_round(self.skill_name)

        # 3. 进化前 benchmark（验证集：Golden set）
        logger.info("Evolver [%s] 运行进化前 benchmark (验证集)...", self.skill_name)
        proposal.benchmark_before = self._run_benchmark()
        logger.info(
            "Evolver [%s] 进化前 benchmark (验证集): %d/%d 通过",
            self.skill_name, proposal.benchmark_before[0], proposal.benchmark_before[1],
        )

        # 4. 加载当前配置（受 evolution_mode 控制）
        current_rules = ""
        current_prompt = ""
        version_before = None
        if self._version_mgr:
            if mode in ("both", "rules_only"):
                current_rules = self._version_mgr.load_raw(self.skill_name, "rules_config") or ""
                try:
                    rules_cfg = self._version_mgr.load(self.skill_name, "rules_config")
                    version_before = rules_cfg.get("version") if rules_cfg else None
                except Exception:
                    pass
            if mode in ("both", "prompt_only"):
                current_prompt = self._version_mgr.load_raw(self.skill_name, "prompt") or ""

        # 5. DeepSeek 分析（使用训练集）
        analysis = await self._analyze_failures(training_set if training_set else today_failures, current_rules, current_prompt)
        if not analysis:
            logger.warning("Evolver [%s] DeepSeek 分析未产出结果", self.skill_name)
            return proposal

        proposal.analysis_raw = json.dumps(analysis, ensure_ascii=False, indent=2)
        proposal.rules_changes = analysis.get("rules_changes", {})
        proposal.prompt_changes = analysis.get("prompt_changes", {})

        if not proposal.rules_changes and not proposal.prompt_changes:
            logger.info("Evolver [%s] DeepSeek 未提出任何优化建议", self.skill_name)
            return proposal

        # 6. 生成 YAML 文本（受 evolution_mode 控制）
        auto_cfg = self.evolve_toml.get("evolve", {}).get("auto_modify", {})

        if proposal.rules_changes and auto_cfg.get("rules_config", False) and mode in ("both", "rules_only"):
            rules_threshold = auto_cfg.get("rules_config", {})
            max_pct = rules_threshold.get("max_change_percent", 20) if isinstance(rules_threshold, dict) else 20
            proposal.rules_text = self._apply_rules_changes(current_rules, proposal.rules_changes, max_pct)

        if proposal.prompt_changes and auto_cfg.get("prompt", False) and mode in ("both", "prompt_only"):
            proposal.prompt_text = self._apply_prompt_changes(current_prompt, proposal.prompt_changes)

        # 7. 写入
        if not dry_run and self._version_mgr:
            guard = self.evolve_toml.get("evolve", {}).get("guard", {})
            require_bench = guard.get("require_benchmark_pass", True)

            applied = True
            version_after = version_before
            if proposal.rules_text and auto_cfg.get("rules_config", False) and mode in ("both", "rules_only"):
                proposal.rules_text, lint_errors = lint_and_fix_yaml(proposal.rules_text)
                if lint_errors:
                    logger.warning("Evolver [%s] rules_config lint issues: %s", self.skill_name, lint_errors)
                new_ver = self._version_mgr.save(self.skill_name, "rules_config", proposal.rules_text)
                if new_ver:
                    version_after = new_ver
                self._sync_rules_to_disk(proposal.rules_text)
                logger.info("Evolver [%s] rules_config 已写入 MySQL + 同步到磁盘", self.skill_name)
            if proposal.prompt_text and auto_cfg.get("prompt", False) and mode in ("both", "prompt_only"):
                proposal.prompt_text, lint_errors = lint_and_fix_yaml(proposal.prompt_text)
                if lint_errors:
                    logger.warning("Evolver [%s] prompt lint issues: %s", self.skill_name, lint_errors)
                self._version_mgr.save(self.skill_name, "prompt", proposal.prompt_text)
                logger.info("Evolver [%s] prompt 已写入 MySQL", self.skill_name)

            # 8. benchmark 安全网
            if require_bench and (proposal.rules_text or proposal.prompt_text):
                logger.info("Evolver [%s] 运行进化后 benchmark...", self.skill_name)
                proposal.benchmark_after = self._run_benchmark()

                pass_before = proposal.benchmark_before[0]
                total_before = proposal.benchmark_before[1]
                pass_after = proposal.benchmark_after[0]

                if total_before > 0 and pass_after < pass_before:
                    logger.warning(
                        "Evolver [%s] benchmark 退化 (%d/%d → %d/%d)，自动回滚",
                        self.skill_name, pass_before, total_before,
                        pass_after, proposal.benchmark_after[1],
                    )
                    if proposal.rules_text and auto_cfg.get("rules_config", False) and mode in ("both", "rules_only"):
                        self._version_mgr.rollback(self.skill_name, "rules_config", 0)
                        restored = self._version_mgr.load_raw(self.skill_name, "rules_config")
                        if restored:
                            self._sync_rules_to_disk(restored)
                    if proposal.prompt_text and auto_cfg.get("prompt", False) and mode in ("both", "prompt_only"):
                        self._version_mgr.rollback(self.skill_name, "prompt", 0)
                    proposal.rolled_back = True
                    proposal.applied = False
                else:
                    proposal.applied = True
            else:
                proposal.applied = applied

            # ── 记录反馈历史 ──
            outcome = "rolled_back" if proposal.rolled_back else ("improved" if proposal.applied else "discarded")
            try:
                self._version_mgr.save_feedback(
                    skill_name=self.skill_name,
                    evolution_round=evolution_round,
                    outcome=outcome,
                    proposal_summary=self._build_proposal_summary(proposal),
                    benchmark_before_pass=proposal.benchmark_before[0],
                    benchmark_before_total=proposal.benchmark_before[1],
                    benchmark_after_pass=proposal.benchmark_after[0] if proposal.benchmark_after else 0,
                    benchmark_after_total=proposal.benchmark_after[1] if proposal.benchmark_after else 0,
                    failure_count=proposal.failure_count,
                    analysis_raw=proposal.analysis_raw,
                    version_before=version_before,
                    version_after=version_after,
                )
                logger.info("Evolver [%s] 反馈已记录 round=%d outcome=%s", self.skill_name, evolution_round, outcome)
            except Exception as e:
                logger.warning("Evolver [%s] 反馈记录失败（不影响主流程）: %s", self.skill_name, e)

        return proposal

    def _sync_rules_to_disk(self, yaml_content: str) -> None:
        if not self._rules_disk_path:
            logger.info("Evolver [%s] 未配置 rules_config_disk_path，跳过磁盘同步", self.skill_name)
            return
        disk_path = Path(self._rules_disk_path)
        try:
            disk_path.parent.mkdir(parents=True, exist_ok=True)
            disk_path.write_text(yaml_content, encoding="utf-8")
            logger.info("Evolver [%s] rules_config 已同步到磁盘: %s", self.skill_name, disk_path)
        except Exception as e:
            logger.warning("Evolver [%s] 磁盘同步失败: %s", self.skill_name, e)

    def _apply_rules_changes(self, current_yaml: str, changes: dict, max_change_percent: float) -> str:
        if not current_yaml:
            return _yaml_dump_str(changes)
        try:
            cfg = yaml_rt.load(current_yaml) or {}
            _warn_numeric_drift(cfg, changes, max_change_percent)
            _deep_update(cfg, changes)
            return _yaml_dump_str(cfg)
        except Exception:
            logger.warning("Evolver [%s] rules_config YAML 合并失败，回退原始 YAML", self.skill_name)
            return current_yaml

    def _apply_prompt_changes(self, current_yaml: str, changes: dict) -> str:
        if not current_yaml:
            return _yaml_dump_str(changes)
        try:
            cfg = yaml_rt.load(current_yaml) or {}
            _deep_update(cfg, changes)
            return _yaml_dump_str(cfg)
        except Exception:
            return current_yaml

    def _load_feedback_history(self) -> str:
        """加载历史反馈记录，格式化为 prompt 可注入的文本。"""
        if not self._version_mgr:
            return ""
        try:
            history = self._version_mgr.load_feedback_history(
                self.skill_name, max_rounds=self._feedback_max_rounds
            )
        except Exception as e:
            logger.debug("Evolver [%s] 反馈历史加载失败: %s", self.skill_name, e)
            return ""

        if not history:
            return "（无历史进化记录）"

        lines = []
        for entry in history:
            bench_info = ""
            if entry["benchmark_before_total"] > 0:
                bench_info = (
                    f" (benchmark: {entry['benchmark_before_pass']}/{entry['benchmark_before_total']}"
                    f" → {entry['benchmark_after_pass']}/{entry['benchmark_after_total']})"
                )
            lines.append(
                f"- 第 {entry['evolution_round']} 轮 [{entry['outcome']}]{bench_info}: "
                f"{entry['proposal_summary'] or '(无摘要)'}"
            )
        return "\n".join(lines)

    def _build_proposal_summary(self, proposal: EvolveProposal) -> str:
        """从提案中提取摘要文本，供反馈记录。"""
        parts: list[str] = []
        if proposal.rules_changes:
            keys = list(proposal.rules_changes.keys())
            parts.append(f"rules_changes: {', '.join(keys)}")
        if proposal.prompt_changes:
            keys = list(proposal.prompt_changes.keys())
            parts.append(f"prompt_changes: {', '.join(keys)}")
        if proposal.training_set_size or proposal.validation_set_size:
            parts.append(
                json.dumps({
                    "training_set_size": proposal.training_set_size,
                    "validation_set_size": proposal.validation_set_size,
                }, ensure_ascii=False)
            )
        return "; ".join(parts) if parts else ""


# ── 工具函数 ──

def _warn_numeric_drift(original: dict, changes: dict, max_pct: float) -> None:
    for key, value in changes.items():
        if isinstance(value, dict):
            _warn_numeric_drift(original.get(key, {}), value, max_pct)
        elif isinstance(value, list):
            pass
        elif isinstance(value, (int, float)):
            orig_val = original.get(key)
            if isinstance(orig_val, (int, float)) and orig_val != 0:
                drift = abs(value - orig_val) / abs(orig_val) * 100
                if drift > max_pct:
                    logger.warning(
                        "Evolver rules_config 数值变更超限: %s %s → %s (%.1f%%, 阈值 %.0f%%)",
                        key, orig_val, value, drift, max_pct,
                    )


def _deep_update(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
