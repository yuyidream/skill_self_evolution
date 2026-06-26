"""
Skill 进化 MySQL 存储 — skill_execution_log / skill_evolution_feedback 表操作。

职责：
- 执行日志读写（skill_execution_log）
- 进化反馈历史（skill_evolution_feedback）
- Golden set 大小查询（nickname_golden_label）

rules_config / prompt 的版本管理由业务项目 VersionManager + wx_version_activation 负责，
不在本模块存储（见 PRD §同一套版本文件）。
"""

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)
from datetime import datetime, timezone, timedelta
import json as _json

_BEIJING_TZ = timezone(timedelta(hours=8))

from typing import Any

import pymysql

from skill_self_evolution.config import DbConfig, get_db_config


class ConfigVersionManager:
    """Skill 进化 MySQL 存储（执行日志 + 反馈历史）。"""

    def __init__(self, db_config: dict[str, Any] | DbConfig | None = None):
        from skill_self_evolution.config import DbConfig
        if db_config is None:
            self._db_config = get_db_config()
        elif isinstance(db_config, DbConfig):
            self._db_config = db_config
        else:
            self._db_config = db_config
        self._conn: pymysql.Connection | None = None

    def set_db_config(self, db_config: dict[str, Any] | DbConfig) -> None:
        self._db_config = db_config

    def _get_conn(self) -> pymysql.Connection:
        """获取数据库连接（懒连接 + 自动重连）。兼容 dict 和 DbConfig。"""
        if self._conn is None or not self._conn.open:
            db = self._db_config
            if isinstance(db, DbConfig):
                host, port, user, password, database = (
                    db.host, db.port, db.user, db.password, db.database
                )
            else:
                host = db.get("host", "localhost")
                port = db.get("port", 3306)
                user = db.get("user", "root")
                password = db.get("password", "")
                database = db.get("database", "")
            self._conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset="utf8mb4",
                autocommit=True,
            )
        return self._conn

    def ensure_evolution_tables(self) -> None:
        """自动建表（幂等）：执行日志 + 进化反馈。"""
        self.ensure_execution_log_table()
        self.ensure_feedback_table()

    def ensure_feedback_table(self) -> None:
        """创建进化反馈记录表（幂等）。"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_evolution_feedback (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    skill_name      VARCHAR(128) NOT NULL,
                    evolution_round INT NOT NULL COMMENT '进化轮次',
                    outcome         ENUM('improved','discarded','rolled_back') NOT NULL,
                    proposal_summary TEXT COMMENT 'proposal 摘要（rules_changes + prompt_changes 的简要描述）',
                    benchmark_before_pass INT DEFAULT 0,
                    benchmark_before_total INT DEFAULT 0,
                    benchmark_after_pass INT DEFAULT 0,
                    benchmark_after_total INT DEFAULT 0,
                    failure_count   INT DEFAULT 0,
                    analysis_raw    TEXT COMMENT 'DeepSeek 原始分析结果',
                    version_before  INT COMMENT '进化前 rules_config 版本号',
                    version_after   INT COMMENT '进化后 rules_config 版本号',
                    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_skill_round (skill_name, evolution_round)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        logger.info("skill_evolution_feedback 表确认存在")

    def ensure_execution_log_table(self) -> None:
        """创建 skill_execution_log 表（幂等），并确保含有 session_date 列。"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_execution_log (
                    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
                    skill_name      VARCHAR(64) NOT NULL,
                    trace_id        VARCHAR(128) NOT NULL DEFAULT '',
                    timestamp       VARCHAR(32) NOT NULL COMMENT 'ISO-8601 北京时间',
                    session_date    VARCHAR(10) NOT NULL DEFAULT '' COMMENT 'Session 真实日期 YYYY-MM-DD',
                    is_failure      TINYINT(1) NOT NULL DEFAULT 0,
                    no_valid_alternative TINYINT(1) NOT NULL DEFAULT 0,
                    input_summary   LONGTEXT COMMENT '含 session 文件全文（enrich_failure 注入）',
                    rule_output     JSON,
                    ai_validation   JSON,
                    ai_reselection  JSON,
                    final_output    JSON,
                    warnings        JSON,
                    elapsed_ms      DOUBLE NOT NULL DEFAULT 0,
                    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_skill_failure (skill_name, is_failure),
                    INDEX idx_session_date (skill_name, session_date)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            # 兼容旧表：无 session_date 列时自动添加
            try:
                cur.execute(
                    "ALTER TABLE skill_execution_log ADD COLUMN session_date VARCHAR(10) NOT NULL DEFAULT '' "
                    "COMMENT 'Session 真实日期 YYYY-MM-DD' AFTER timestamp"
                )
                logger.info("skill_execution_log 表已补充 session_date 列")
            except Exception:
                pass  # 列已存在
        logger.info("skill_execution_log 表确认存在")

    def save_execution_log(self, entry: dict) -> int:
        """写入一条执行日志到 MySQL。

        Returns:
            新插入的 id
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO skill_execution_log
                   (skill_name, trace_id, timestamp, session_date, is_failure, no_valid_alternative,
                    input_summary, rule_output, ai_validation, ai_reselection,
                    final_output, warnings, elapsed_ms)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    entry.get("skill_name", ""),
                    entry.get("trace_id", ""),
                    entry.get("timestamp", ""),
                    entry.get("session_date", ""),
                    1 if entry.get("is_failure") else 0,
                    1 if entry.get("no_valid_alternative") else 0,
                    _json.dumps(entry.get("input_summary", {}), ensure_ascii=False),
                    _json.dumps(entry.get("rule_output", {}), ensure_ascii=False),
                    _json.dumps(entry.get("ai_validation"), ensure_ascii=False) if entry.get("ai_validation") else None,
                    _json.dumps(entry.get("ai_reselection"), ensure_ascii=False) if entry.get("ai_reselection") else None,
                    _json.dumps(entry.get("final_output", {}), ensure_ascii=False),
                    _json.dumps(entry.get("warnings", []), ensure_ascii=False),
                    entry.get("elapsed_ms", 0),
                ),
            )
            log_id = cur.lastrowid
        return log_id

    def load_failure_logs_by_date(self, skill_name: str, date_str: str) -> list[dict]:
        """加载指定 session_date 的失败日志。"""
        import pymysql.cursors
        conn = self._get_conn()
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                """SELECT * FROM skill_execution_log
                   WHERE skill_name = %s AND is_failure = 1
                   AND (session_date = %s OR timestamp LIKE %s)
                   ORDER BY id""",
                (skill_name, date_str, f"{date_str}%"),
            )
            rows = cur.fetchall()
        return [
            {
                "id": r.get("id"),
                "trace_id": r.get("trace_id", ""),
                "skill_name": r.get("skill_name", ""),
                "timestamp": r.get("timestamp", ""),
                "session_date": r.get("session_date", ""),
                "is_failure": bool(r.get("is_failure")),
                "no_valid_alternative": bool(r.get("no_valid_alternative")),
                "input_summary": self._parse_json_field(r.get("input_summary")),
                "rule_output": self._parse_json_field(r.get("rule_output")),
                "ai_validation": self._parse_json_field(r.get("ai_validation")),
                "ai_reselection": self._parse_json_field(r.get("ai_reselection")),
                "final_output": self._parse_json_field(r.get("final_output")),
                "warnings": self._parse_json_field(r.get("warnings")) or [],
                "elapsed_ms": r.get("elapsed_ms", 0),
            }
            for r in rows
        ]

    def load_failure_logs_cumulative(self, skill_name: str, since_log_id: int = 0) -> list[dict]:
        """加载累计未处理的失败日志（id > since_log_id）。

        Returns:
            日志条目列表（dict 格式，字段名与原 JSONL 一致），含 id 字段用于追踪
        """
        import pymysql.cursors
        conn = self._get_conn()
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                """SELECT * FROM skill_execution_log
                   WHERE skill_name = %s AND is_failure = 1 AND id > %s
                   ORDER BY id""",
                (skill_name, since_log_id),
            )
            rows = cur.fetchall()
        return [
            {
                "id": r.get("id"),
                "trace_id": r.get("trace_id", ""),
                "skill_name": r.get("skill_name", ""),
                "timestamp": r.get("timestamp", ""),
                "session_date": r.get("session_date", ""),
                "is_failure": bool(r.get("is_failure")),
                "no_valid_alternative": bool(r.get("no_valid_alternative")),
                "input_summary": self._parse_json_field(r.get("input_summary")),
                "rule_output": self._parse_json_field(r.get("rule_output")),
                "ai_validation": self._parse_json_field(r.get("ai_validation")),
                "ai_reselection": self._parse_json_field(r.get("ai_reselection")),
                "final_output": self._parse_json_field(r.get("final_output")),
                "warnings": self._parse_json_field(r.get("warnings")) or [],
                "elapsed_ms": r.get("elapsed_ms", 0),
            }
            for r in rows
        ]

    def get_max_execution_log_id(self, skill_name: str = "") -> int:
        """获取当前最大执行日志 id（用于进化追踪）。"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            if skill_name:
                cur.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM skill_execution_log WHERE skill_name = %s",
                    (skill_name,),
                )
            else:
                cur.execute("SELECT COALESCE(MAX(id), 0) FROM skill_execution_log")
            return cur.fetchone()[0]

    def load_training_set(
        self, skill_name: str, exclude_session_date: str
    ) -> tuple[list[dict], int]:
        """加载训练集：历史所有 is_failure=1，按 session_date 排除当前批次。

        Returns:
            (training_entries, excluded_count)
        """
        import pymysql.cursors
        conn = self._get_conn()
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 先查总数
            cur.execute(
                "SELECT COUNT(*) as cnt FROM skill_execution_log "
                "WHERE skill_name = %s AND is_failure = 1",
                (skill_name,),
            )
            total = cur.fetchone()["cnt"]

            # 训练集：历史失败 - 当天 session_date
            cur.execute(
                "SELECT * FROM skill_execution_log "
                "WHERE skill_name = %s AND is_failure = 1 "
                "AND (session_date != %s OR session_date = '') "
                "ORDER BY id",
                (skill_name, exclude_session_date),
            )
            training_rows = cur.fetchall()

            # 当天排除数
            cur.execute(
                "SELECT COUNT(*) as cnt FROM skill_execution_log "
                "WHERE skill_name = %s AND is_failure = 1 AND session_date = %s",
                (skill_name, exclude_session_date),
            )
            excluded = cur.fetchone()["cnt"]

        training = [
            {
                "trace_id": r.get("trace_id", ""),
                "skill_name": r.get("skill_name", ""),
                "timestamp": r.get("timestamp", ""),
                "session_date": r.get("session_date", ""),
                "is_failure": True,
                "no_valid_alternative": bool(r.get("no_valid_alternative")),
                "input_summary": self._parse_json_field(r.get("input_summary")),
                "rule_output": self._parse_json_field(r.get("rule_output")),
                "ai_validation": self._parse_json_field(r.get("ai_validation")),
                "ai_reselection": self._parse_json_field(r.get("ai_reselection")),
                "final_output": self._parse_json_field(r.get("final_output")),
                "warnings": self._parse_json_field(r.get("warnings")) or [],
                "elapsed_ms": r.get("elapsed_ms", 0),
            }
            for r in training_rows
        ]

        logger.info(
            "ConfigVersionManager 训练集加载: skill=%s total_failures=%d training=%d excluded_session_date(%s)=%d",
            skill_name, total, len(training), exclude_session_date, excluded,
        )
        return training, excluded

    def get_golden_set_size(self) -> int:
        """获取 Golden set 大小（nickname_golden_label 表）。

        Returns:
            标注样本数量
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT COUNT(*) FROM nickname_golden_label")
                row = cur.fetchone()
                return int(row[0]) if row else 0
            except Exception:
                return 0

    def _parse_json_field(self, value) -> Any:
        """解析 JSON 字段（MySQL JSON 列可能返回 str 或已解析对象）。"""
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                return _json.loads(value)
            except Exception:
                return value
        return value

    def save_feedback(
        self,
        skill_name: str,
        evolution_round: int,
        outcome: str,
        proposal_summary: str = "",
        benchmark_before_pass: int = 0,
        benchmark_before_total: int = 0,
        benchmark_after_pass: int = 0,
        benchmark_after_total: int = 0,
        failure_count: int = 0,
        analysis_raw: str = "",
        version_before: int | None = None,
        version_after: int | None = None,
    ) -> int:
        """记录一轮进化反馈。

        Returns:
            新插入的 feedback id
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO skill_evolution_feedback
                   (skill_name, evolution_round, outcome, proposal_summary,
                    benchmark_before_pass, benchmark_before_total,
                    benchmark_after_pass, benchmark_after_total,
                    failure_count, analysis_raw, version_before, version_after)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    skill_name, evolution_round, outcome, proposal_summary,
                    benchmark_before_pass, benchmark_before_total,
                    benchmark_after_pass, benchmark_after_total,
                    failure_count, analysis_raw, version_before, version_after,
                ),
            )
            feedback_id = cur.lastrowid
        logger.info("反馈记录写入: %s round=%d outcome=%s id=%d", skill_name, evolution_round, outcome, feedback_id)
        return feedback_id

    def load_feedback_history(
        self, skill_name: str, max_rounds: int = 5
    ) -> list[dict]:
        """加载最近 N 轮反馈历史。

        Args:
            skill_name: Skill 名称
            max_rounds: 最多返回多少轮

        Returns:
            按 evolution_round 降序排列的反馈记录列表
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT evolution_round, outcome, proposal_summary,
                          benchmark_before_pass, benchmark_before_total,
                          benchmark_after_pass, benchmark_after_total,
                          failure_count, version_before, version_after
                   FROM skill_evolution_feedback
                   WHERE skill_name = %s
                   ORDER BY evolution_round DESC
                   LIMIT %s""",
                (skill_name, max_rounds),
            )
            rows = cur.fetchall()
        return [
            {
                "evolution_round": r[0],
                "outcome": r[1],
                "proposal_summary": r[2],
                "benchmark_before_pass": r[3],
                "benchmark_before_total": r[4],
                "benchmark_after_pass": r[5],
                "benchmark_after_total": r[6],
                "failure_count": r[7],
                "version_before": r[8],
                "version_after": r[9],
            }
            for r in rows
        ]

    def get_next_evolution_round(self, skill_name: str) -> int:
        """获取下一次进化的轮次号（当前最大轮次 + 1）。"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(MAX(evolution_round), 0) + 1
                   FROM skill_evolution_feedback
                   WHERE skill_name = %s""",
                (skill_name,),
            )
            return cur.fetchone()[0]

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn and self._conn.open:
            self._conn.close()
            self._conn = None
