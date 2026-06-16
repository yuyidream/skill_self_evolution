"""
配置版本管理器 — MySQL skill_config / skill_config_history 表操作。

职责：
- 从 MySQL 加载当前激活版本的 rules_config / prompt YAML
- 写入新版本时自动归档旧版本到 skill_config_history
- 支持回滚到任意历史版本

业务项目可通过提供 adapter 实现同一接口，或直接使用 ConfigVersionManager。
"""

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)
from datetime import datetime, timezone, timedelta

_BEIJING_TZ = timezone(timedelta(hours=8))

from typing import Any

import pymysql
from ruamel.yaml import YAML

yaml_safe = YAML(typ='safe')

from skill_self_evolution.config import DbConfig, get_db_config


class ConfigVersionManager:
    """框架内置版本管理：version 递增 + 历史归档。"""

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

    def ensure_tables(self) -> None:
        """自动建表（幂等）。首次使用时或部署阶段调用。"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_config (
                    skill_name   VARCHAR(128) NOT NULL COMMENT 'Skill 名称',
                    config_type  ENUM('rules_config','prompt') NOT NULL COMMENT '配置类型',
                    content      MEDIUMTEXT NOT NULL COMMENT 'YAML 字符串',
                    version      INT NOT NULL DEFAULT 1 COMMENT '版本号，每次更新递增',
                    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    PRIMARY KEY (skill_name, config_type)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS skill_config_history (
                    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
                    skill_name   VARCHAR(128) NOT NULL,
                    config_type  ENUM('rules_config','prompt') NOT NULL,
                    content      MEDIUMTEXT NOT NULL,
                    version      INT NOT NULL,
                    archived_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_skill_version (skill_name, config_type, version)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
        logger.info("skill_config / skill_config_history 表确认存在")

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

    def load(self, skill_name: str, config_type: str) -> dict | None:
        """从 MySQL 加载当前激活版本，返回解析后的 dict。

        Args:
            skill_name: Skill 名称（如 "nickname-selector"）
            config_type: "rules_config" 或 "prompt"

        Returns:
            解析后的 YAML dict，未找到配置时返回 None
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM skill_config WHERE skill_name = %s AND config_type = %s",
                (skill_name, config_type),
            )
            row = cur.fetchone()
        if row is None:
            logger.debug("skill_config 未找到: %s/%s", skill_name, config_type)
            return None
        return yaml_safe.load(row[0])

    def load_raw(self, skill_name: str, config_type: str) -> str | None:
        """加载原始 YAML 字符串（用于进化分析 prompt 注入）。"""
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM skill_config WHERE skill_name = %s AND config_type = %s",
                (skill_name, config_type),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def save(self, skill_name: str, config_type: str, content: str) -> int:
        """写入新版本：先归档旧版本到 skill_config_history，再更新主表。

        Args:
            skill_name: Skill 名称
            config_type: "rules_config" 或 "prompt"
            content: YAML 字符串（非解析后的 dict）

        Returns:
            新版本号
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            # 查询当前版本号和内容
            cur.execute(
                "SELECT version, content FROM skill_config WHERE skill_name = %s AND config_type = %s",
                (skill_name, config_type),
            )
            row = cur.fetchone()

            if row:
                old_version = row[0]
                old_content = row[1]
                new_version = old_version + 1
                # 归档旧版本
                cur.execute(
                    "INSERT INTO skill_config_history (skill_name, config_type, content, version) "
                    "VALUES (%s, %s, %s, %s)",
                    (skill_name, config_type, old_content, old_version),
                )
                # 更新主表
                cur.execute(
                    "UPDATE skill_config SET content = %s, version = %s, updated_at = %s "
                    "WHERE skill_name = %s AND config_type = %s",
                    (content, new_version, datetime.now(_BEIJING_TZ), skill_name, config_type),
                )
            else:
                new_version = 1
                cur.execute(
                    "INSERT INTO skill_config (skill_name, config_type, content, version) "
                    "VALUES (%s, %s, %s, %s)",
                    (skill_name, config_type, content, new_version),
                )

        logger.info("配置写入: %s/%s v%d", skill_name, config_type, new_version)
        return new_version

    def rollback(self, skill_name: str, config_type: str, target_version: int) -> bool:
        """回滚到指定版本。

        Args:
            skill_name: Skill 名称
            config_type: "rules_config" 或 "prompt"
            target_version: 目标版本号

        Returns:
            True 表示回滚成功，False 表示目标版本不存在
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            # 查找目标版本
            if target_version == 0:
                # v0 = 删除当前配置
                cur.execute(
                    "DELETE FROM skill_config WHERE skill_name = %s AND config_type = %s",
                    (skill_name, config_type),
                )
                logger.info("配置已删除（回滚到 v0）: %s/%s", skill_name, config_type)
                return True

            # 从历史表查找
            cur.execute(
                "SELECT content FROM skill_config_history "
                "WHERE skill_name = %s AND config_type = %s AND version = %s "
                "ORDER BY archived_at DESC LIMIT 1",
                (skill_name, config_type, target_version),
            )
            hist = cur.fetchone()
            if hist is None:
                logger.warning("历史版本不存在: %s/%s v%d", skill_name, config_type, target_version)
                return False

            # 从主表获取当前版本以归档
            cur.execute(
                "SELECT version, content FROM skill_config WHERE skill_name = %s AND config_type = %s",
                (skill_name, config_type),
            )
            current = cur.fetchone()

            if current:
                # 归档当前版本
                cur.execute(
                    "INSERT INTO skill_config_history (skill_name, config_type, content, version) "
                    "VALUES (%s, %s, %s, %s)",
                    (skill_name, config_type, current[1], current[0]),
                )

            # 写入目标版本内容
            new_version = (current[0] + 1) if current else 1
            cur.execute(
                "REPLACE INTO skill_config (skill_name, config_type, content, version, updated_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (skill_name, config_type, hist[0], new_version, datetime.now(_BEIJING_TZ)),
            )

        logger.info("配置回滚成功: %s/%s → v%d (from history v%d)", skill_name, config_type, new_version, target_version)
        return True

    def close(self) -> None:
        """关闭数据库连接。"""
        if self._conn and self._conn.open:
            self._conn.close()
            self._conn = None
