"""
Skill 日志器测试：JSONL 追加写入
"""

import json
import os
import tempfile
from pathlib import Path

from skill_self_evolution.logger import SkillLogger


class TestSkillLogger:
    """SkillLogger 测试"""

    def test_write_and_read(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setenv("SKILL_LOG_DIR", tmp)

            logger = SkillLogger("test-skill")
            entry = {
                "trace_id": "test-001",
                "skill_name": "test-skill",
                "timestamp": "2026-06-14T10:00:00+08:00",
                "is_failure": True,
                "input_summary": {"key": "val"},
                "rule_output": {"nickname": "test"},
                "ai_validation": {"result": "不合理"},
                "ai_reselection": None,
                "final_output": {"nickname": "corrected"},
                "warnings": [],
                "elapsed_ms": 123.4,
            }
            logger.write(entry)

            assert logger.log_path.exists()
            with open(logger.log_path, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
            assert len(lines) == 1
            assert lines[0]["trace_id"] == "test-001"
            assert lines[0]["is_failure"] is True

    def test_log_execution(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setenv("SKILL_LOG_DIR", tmp)

            logger = SkillLogger("test-skill-2")
            logger.log_execution(
                trace_id="exec-001",
                is_failure=False,
                input_summary={"x": "y"},
                rule_output={"score": 58},
                ai_validation=None,
                ai_reselection=None,
                final_output={"score": 80},
                warnings=[],
                elapsed_ms=42.0,
            )

            with open(logger.log_path, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
            assert len(lines) == 1
            assert lines[0]["is_failure"] is False
            assert lines[0]["final_output"] == {"score": 80}
