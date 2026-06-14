"""
JSONL 日志器 — 追加写入 Skill 执行日志，Pydantic 校验。

日志路径: /data/skill-logs/{skill_name}/{date}.jsonl
（可通过 SKILL_LOG_DIR 环境变量覆盖）
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from skill_self_evolution.models import LogEntry

logger = logging.getLogger(__name__)

_BEIJING_TZ = timezone(timedelta(hours=8))


def _beijing_now() -> datetime:
    return datetime.now(_BEIJING_TZ)


def _beijing_today_str() -> str:
    return _beijing_now().strftime("%Y-%m-%d")


def _get_log_dir(skill_name: str) -> Path:
    """获取日志目录，优先取环境变量 SKILL_LOG_DIR。"""
    base = os.environ.get("SKILL_LOG_DIR", "/data/skill-logs")
    return Path(base) / skill_name


class SkillLogger:
    """Skill 执行日志器，每行一个 JSON（Pydantic LogEntry 校验）。"""

    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        self._log_path: Path | None = None

    @property
    def log_path(self) -> Path:
        if self._log_path is None:
            log_dir = _get_log_dir(self.skill_name)
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = log_dir / f"{_beijing_today_str()}.jsonl"
        return self._log_path

    def write(self, entry: dict) -> None:
        """追加一行 JSON 到日志文件（接受已校验的 dict）。"""
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Skill 日志写入失败: %s", e)

    def log_execution(
        self,
        trace_id: str,
        is_failure: bool,
        input_summary: dict,
        rule_output: dict,
        ai_validation: dict | None,
        ai_reselection: dict | None,
        final_output: dict,
        warnings: list[str],
        elapsed_ms: float,
    ) -> None:
        """写入标准执行日志条目（Pydantic 校验后持久化）。"""
        entry = LogEntry(
            trace_id=trace_id,
            skill_name=self.skill_name,
            timestamp=_beijing_now().isoformat(),
            is_failure=is_failure,
            input_summary=input_summary,
            rule_output=rule_output,
            ai_validation=ai_validation,
            ai_reselection=ai_reselection,
            final_output=final_output,
            warnings=warnings,
            elapsed_ms=round(elapsed_ms, 1),
        )
        self.write(entry.model_dump())
