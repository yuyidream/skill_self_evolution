"""结构化日志（structlog，stdlib 集成）。

用法::

    from skill_self_evolution.logging import get_logger
    logger = get_logger(__name__)

    logger.info("event_name", key=value)
    logger.info("msg with %s", arg)
    logger.warning("event", exc_info=True)

默认使用 ConsoleRenderer。设置环境变量 STRUCTLOG_JSON=true 可切换为 JSONRenderer。
"""

import os
import structlog

_is_configured = False


def _configure_default():
    global _is_configured
    if _is_configured:
        return
    _is_configured = True

    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if os.environ.get("STRUCTLOG_JSON", "").lower() == "true":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


_configure_default()


def get_logger(name: str = ""):
    """返回 structlog logger（stdlib 绑定）。"""
    return structlog.get_logger(name)
