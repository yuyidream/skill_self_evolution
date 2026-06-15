"""
EvoSkill 离线进化器 — 读 JSONL 日志 → DeepSeek 分析失败模式 → 生成优化提案 → 自动写入或发 PR。

流程：
1. 读昨日 JSONL → 筛选 is_failure=true
2. 若 is_failure 样本 < min_failure_samples → 跳过本次进化
3. 跑 benchmark()
4. DeepSeek 分析失败模式（优先 Skill 自定义 evolve_prompt.yaml）
5. 生成 YAML 优化提案
6. 按 evolve.toml 权限 → 自动写 MySQL 或发 PR
    - rules_config / prompt 权限为 true → 自动写入（含历史归档）
    - skill_md / scripts 权限为 false → 生成 PR 文件
7. benchmark 安全网：变更后重跑 benchmark，退化则自动回滚
"""

import json
from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)
import os
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

yaml_safe = YAML(typ='safe')
yaml_rt = YAML()  # round-trip: 保留注释和格式
yaml_rt.default_flow_style = False


def _yaml_dump_str(data: Any) -> str:
    """ruamel.yaml YAML().dump() 需要 stream，薄封装返回字符串。"""
    buf = StringIO()
    yaml_rt.dump(data, buf)
    return buf.getvalue()

from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.loader import SkillLoader, SkillModule
from skill_self_evolution.logger import _get_log_dir
from skill_self_evolution.models import EvolveProposalModel
from skill_self_evolution.yaml_lint import lint_and_fix_yaml

_BEIJING_TZ = timezone(timedelta(hours=8))

_FRAMEWORK_DEFAULTS = Path(__file__).resolve().parents[2] / "defaults"


def _yesterday_str() -> str:
    return (datetime.now(_BEIJING_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")


class EvolveProposal:
    """一次进化分析产生的提案（内部状态用普通类，序列化时通过 EvolveProposalModel 校验）。"""

    def __init__(self):
        self.rules_changes: dict[str, Any] = {}
        self.prompt_changes: dict[str, Any] = {}
        self.rules_text: str | None = None
        self.prompt_text: str | None = None
        self.analysis_raw: str = ""
        self.failure_count: int = 0
        self.benchmark_before: tuple[int, int, list] = (0, 0, [])
        self.benchmark_after: tuple[int, int, list] = (0, 0, [])
        self.applied: bool = False
        self.rolled_back: bool = False

    def to_model(self) -> EvolveProposalModel:
        """转为 Pydantic 模型（用于序列化/日志）。"""
        return EvolveProposalModel(
            rules_changes=self.rules_changes,
            prompt_changes=self.prompt_changes,
            rules_text=self.rules_text,
            prompt_text=self.prompt_text,
            analysis_raw=self.analysis_raw,
            failure_count=self.failure_count,
            applied=self.applied,
            rolled_back=self.rolled_back,
        )


class Evolver:
    """离线进化引擎。"""

    def __init__(
        self,
        skill_name: str,
        skill_base_dir: Path | None = None,
        deepseek: DeepSeekClient | None = None,
        config_version_manager=None,
    ):
        """
        Args:
            skill_name: Skill 名称
            skill_base_dir: Skill 根目录
            deepseek: DeepSeek 客户端（用于分析失败模式）
            config_version_manager: ConfigVersionManager 实例（用于写入 MySQL）
        """
        self.skill_name = skill_name
        self._loader = SkillLoader(skill_base_dir)
        self._deepseek = deepseek
        self._version_mgr = config_version_manager

    def _load_failure_logs(self, date_str: str | None = None) -> list[dict]:
        """读取 JSONL 日志中 is_failure=true 的记录。

        Args:
            date_str: 日期字符串 YYYY-MM-DD，默认昨天

        Returns:
            is_failure=true 的日志记录列表
        """
        target_date = date_str or _yesterday_str()
        log_dir = _get_log_dir(self.skill_name)
        log_path = log_dir / f"{target_date}.jsonl"

        if not log_path.exists():
            logger.info("EvoSkill [%s] 日志文件不存在: %s", self.skill_name, log_path)
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
            logger.warning("EvoSkill [%s] 日志读取失败: %s", self.skill_name, e)
            return []

        logger.info("EvoSkill [%s] 读取 %d 条 is_failure 记录", self.skill_name, len(failures))
        return failures

    def _run_benchmark(self, skill: SkillModule) -> tuple[int, int, list]:
        """跑 benchmark() 获取基准指标。

        Returns:
            (pass_count, total_count, failures_list)
        """
        try:
            return skill.benchmark(self)
        except Exception as e:
            logger.warning("EvoSkill [%s] benchmark 执行失败: %s", self.skill_name, e)
            return 0, 0, [str(e)]

    async def _analyze_failures(
        self,
        skill: SkillModule,
        failures: list[dict],
        current_rules: str,
        current_prompt: str,
    ) -> dict:
        """调用 DeepSeek 分析失败模式。

        Returns:
            {"rules_changes": {...}, "prompt_changes": {...}}
        """
        if not self._deepseek:
            logger.warning("EvoSkill [%s] DeepSeek 客户端未配置，无法分析", self.skill_name)
            return {}

        # 加载 evolve_prompt.yaml（Skill 自定义优先，框架默认降级）
        prompt_cfg = skill.evolve_prompt_yaml or {}
        if not prompt_cfg:
            defaults_path = _FRAMEWORK_DEFAULTS / "evolve_prompt.yaml"
            if defaults_path.exists():
                prompt_cfg = yaml_safe.load(defaults_path.read_text(encoding="utf-8")) or {}

        system = prompt_cfg.get("system", "你是配置优化专家。")
        template = prompt_cfg.get(
            "analyze_template",
            "分析以下失败案例：\n{{failure_logs}}\n输出优化建议 JSON。",
        )

        # 序列化失败日志（截断过长内容）
        failure_texts = []
        for f in failures[:20]:  # 最多 20 条
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
            logger.warning("EvoSkill [%s] 分析请求失败: %s", self.skill_name, e)
            return {}

    async def evolve(
        self,
        min_failure_samples: int = 10,
        dry_run: bool = True,
        date_str: str | None = None,
    ) -> EvolveProposal | None:
        """执行一轮进化。

        Args:
            min_failure_samples: 最少失败样本数，不足则跳过
            dry_run: True=仅分析不写入，False=自动写入 MySQL
            date_str: 日期字符串，默认昨天

        Returns:
            EvolveProposal 或 None（跳过时）
        """
        logger.info(
            "EvoSkill [%s] 开始进化分析 (min_failure_samples=%d, dry_run=%s)",
            self.skill_name,
            min_failure_samples,
            dry_run,
        )

        proposal = EvolveProposal()

        # 1. 加载 Skill 模块
        try:
            skill = self._loader.load(self.skill_name)
        except Exception as e:
            logger.error("EvoSkill [%s] 加载失败: %s", self.skill_name, e)
            return None

        # 2. enhancement 角色不触发进化
        if skill.ai_role == "enhancement":
            logger.info("EvoSkill [%s] ai_role=enhancement，不触发进化", self.skill_name)
            return None

        # 3. 读取 JSONL 日志
        failures = self._load_failure_logs(date_str)
        proposal.failure_count = len(failures)

        if len(failures) < min_failure_samples:
            logger.info(
                "EvoSkill [%s] 失败样本不足 (got=%d, need=%d)，跳过进化",
                self.skill_name,
                len(failures),
                min_failure_samples,
            )
            return proposal

        # 4. 跑 benchmark（进化前基线）
        logger.info("EvoSkill [%s] 运行进化前 benchmark...", self.skill_name)
        proposal.benchmark_before = self._run_benchmark(skill)
        logger.info(
            "EvoSkill [%s] 进化前 benchmark: %d/%d 通过",
            self.skill_name,
            proposal.benchmark_before[0],
            proposal.benchmark_before[1],
        )

        # 5. 加载当前配置
        current_rules = ""
        current_prompt = ""
        if self._version_mgr:
            current_rules = self._version_mgr.load_raw(self.skill_name, "rules_config") or ""
            current_prompt = self._version_mgr.load_raw(self.skill_name, "prompt") or ""

        # 6. DeepSeek 分析
        analysis = await self._analyze_failures(skill, failures, current_rules, current_prompt)
        if not analysis:
            logger.warning("EvoSkill [%s] DeepSeek 分析未产出结果", self.skill_name)
            return proposal

        proposal.rules_changes = analysis.get("rules_changes", {})
        proposal.prompt_changes = analysis.get("prompt_changes", {})

        if not proposal.rules_changes and not proposal.prompt_changes:
            logger.info("EvoSkill [%s] DeepSeek 未提出任何优化建议", self.skill_name)
            return proposal

        # 7. 生成 YAML 文本
        evolve_cfg = skill.evolve_toml
        auto_cfg = evolve_cfg.get("evolve", {}).get("auto_modify", {})

        if proposal.rules_changes and auto_cfg.get("rules_config", False):
            rules_threshold = auto_cfg.get("rules_config", {})
            max_pct = rules_threshold.get("max_change_percent", 20)
            proposal.rules_text = self._apply_rules_changes(current_rules, proposal.rules_changes, max_pct)

        if proposal.prompt_changes and auto_cfg.get("prompt", False):
            proposal.prompt_text = self._apply_prompt_changes(current_prompt, proposal.prompt_changes)

        # 8. 写入
        if not dry_run and self._version_mgr:
            guard = evolve_cfg.get("evolve", {}).get("guard", {})
            require_bench = guard.get("require_benchmark_pass", True)

            applied = True
            if proposal.rules_text and auto_cfg.get("rules_config", False):
                proposal.rules_text, lint_errors = lint_and_fix_yaml(proposal.rules_text)
                if lint_errors:
                    logger.warning("EvoSkill [%s] rules_config lint issues: %s", self.skill_name, lint_errors)
                self._version_mgr.save(self.skill_name, "rules_config", proposal.rules_text)
                logger.info("EvoSkill [%s] rules_config 已写入 MySQL", self.skill_name)
            if proposal.prompt_text and auto_cfg.get("prompt", False):
                proposal.prompt_text, lint_errors = lint_and_fix_yaml(proposal.prompt_text)
                if lint_errors:
                    logger.warning("EvoSkill [%s] prompt lint issues: %s", self.skill_name, lint_errors)
                self._version_mgr.save(self.skill_name, "prompt", proposal.prompt_text)
                logger.info("EvoSkill [%s] prompt 已写入 MySQL", self.skill_name)

            # 9. benchmark 安全网：重新跑 benchmark 验证不退化
            if require_bench and (proposal.rules_text or proposal.prompt_text):
                logger.info("EvoSkill [%s] 运行进化后 benchmark...", self.skill_name)
                # 清除缓存使新配置生效
                self._loader.invalidate_cache(self.skill_name)
                skill_after = self._loader.load(self.skill_name)
                proposal.benchmark_after = self._run_benchmark(skill_after)

                pass_before = proposal.benchmark_before[0]
                total_before = proposal.benchmark_before[1]
                pass_after = proposal.benchmark_after[0]

                if total_before > 0 and pass_after < pass_before:
                    # 退化 → 回滚
                    logger.warning(
                        "EvoSkill [%s] benchmark 退化 (%d/%d → %d/%d)，自动回滚",
                        self.skill_name,
                        pass_before,
                        total_before,
                        pass_after,
                        proposal.benchmark_after[1],
                    )
                    if proposal.rules_text and auto_cfg.get("rules_config", False):
                        self._version_mgr.rollback(self.skill_name, "rules_config", 0)
                    if proposal.prompt_text and auto_cfg.get("prompt", False):
                        self._version_mgr.rollback(self.skill_name, "prompt", 0)
                    proposal.rolled_back = True
                    proposal.applied = False
                else:
                    proposal.applied = True
            else:
                proposal.applied = applied

        return proposal

    def _apply_rules_changes(self, current_yaml: str, changes: dict, max_change_percent: float) -> str:
        """将 DeepSeek 产出的 rules_changes 合并到现有 YAML。

        当前实现：简单字符串替换，仅允许阈值调整。
        """
        if not current_yaml:
            return _yaml_dump_str(changes)

        # 遍历 changes 中的阈值调整
        modified = current_yaml
        for key, value in changes.items():
            if isinstance(value, (int, float)):
                # 查找 YAML 中的对应键并替换数值
                import re
                pattern = rf"^\s*{re.escape(key)}\s*:\s*[\d.]+"
                new_line = f"{key}: {value}"
                modified = re.sub(pattern, new_line, modified, flags=re.MULTILINE)

        return modified

    def _apply_prompt_changes(self, current_yaml: str, changes: dict) -> str:
        """将 DeepSeek 产出的 prompt_changes 合并到现有 YAML。

        当前实现：按字段路径替换 YAML 值。
        """
        if not current_yaml:
            return _yaml_dump_str(changes)

        try:
            cfg = yaml_rt.load(current_yaml) or {}
            _deep_update(cfg, changes)
            return _yaml_dump_str(cfg)
        except Exception:
            return current_yaml


def _deep_update(base: dict, updates: dict) -> None:
    """递归合并 dict。"""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
