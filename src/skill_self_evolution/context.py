"""
trace_id 上下文管理 — 基于 contextvars 的全链路追踪。

框架在 SkillExecutor.run() 入口自动生成 trace_id 并注入上下文，
Skill 实现（run.py）无需手动处理。
"""

import contextvars

_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "trace_id", default=None
)


def get_trace_id() -> str | None:
    """获取当前协程/线程的 trace_id。"""
    return _current_trace_id.get()


def set_trace_id(trace_id: str) -> None:
    """设置当前协程/线程的 trace_id（框架内部使用）。"""
    _current_trace_id.set(trace_id)
