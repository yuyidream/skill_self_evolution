"""
JSONL 日志器 + MySQL 执行日志 — Pydantic 校验。

日志路径: /data/skill-logs/{skill_name}/{date}.jsonl
MySQL 表: skill_execution_log（主存储）
（JSONL 为辅，MySQL 表为主）
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)

from skill_self_evolution.models import LogEntry

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
    """Skill 执行日志器。

    - 主存储：MySQL skill_execution_log 表（需传入 version_mgr）
    - 副存储：JSONL 文件（容器内本地备份）
    """

    def __init__(self, skill_name: str, version_mgr: Any = None):
        self.skill_name = skill_name
        self._log_path: Path | None = None
        self._version_mgr = version_mgr

    @property
    def log_path(self) -> Path:
        if self._log_path is None:
            log_dir = _get_log_dir(self.skill_name)
            log_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = log_dir / f"{_beijing_today_str()}.jsonl"
        return self._log_path

    def write(self, entry: dict) -> None:
        """追加一行 JSON 到日志文件 + MySQL。"""
        # 1. MySQL 主存储
        if self._version_mgr:
            try:
                self._version_mgr.ensure_execution_log_table()
                log_id = self._version_mgr.save_execution_log(entry)
                logger.debug(
                    "execution_log.mysql_written",
                    skill_name=self.skill_name,
                    log_id=log_id,
                    is_failure=entry.get("is_failure"),
                )
            except Exception:
                logger.warning("execution_log.mysql_write_failed", exc_info=True)

        # 2. JSONL 副存储
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Skill 日志写入失败: %s", e)

    def log_execution(
        self,
        trace_id: str,
        is_failure: bool,
        no_valid_alternative: bool,
        input_summary: dict,
        rule_output: dict,
        ai_validation: dict | None,
        ai_reselection: dict | None,
        final_output: dict,
        warnings: list[str],
        elapsed_ms: float,
    ) -> None:
        """写入标准执行日志条目（Pydantic 校验后持久化到 MySQL + JSONL）。"""
        entry = LogEntry(
            trace_id=trace_id,
            skill_name=self.skill_name,
            timestamp=_beijing_now().isoformat(),
            is_failure=is_failure,
            no_valid_alternative=no_valid_alternative,
            input_summary=input_summary,
            rule_output=rule_output,
            ai_validation=ai_validation,
            ai_reselection=ai_reselection,
            final_output=final_output,
            warnings=warnings,
            elapsed_ms=round(elapsed_ms, 1),
        )
        self.write(entry.model_dump())
