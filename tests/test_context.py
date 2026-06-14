"""
上下文追踪测试：trace_id contextvars 注入与读取
"""

import asyncio

from skill_self_evolution.context import get_trace_id, set_trace_id


class TestTraceContext:
    """trace_id contextvars 测试"""

    def test_set_and_get(self):
        set_trace_id("test-trace-001")
        assert get_trace_id() == "test-trace-001"

    def test_default_none(self):
        # 验证 ContextVar 默认值为 None
        from skill_self_evolution.context import _current_trace_id
        # 临时重置
        old = _current_trace_id.get()
        try:
            _current_trace_id.set(None)
            assert get_trace_id() is None
        finally:
            _current_trace_id.set(old)

    def test_across_contexts(self):
        """验证 contextvars 在不同协程间隔离"""
        set_trace_id("parent-trace")

        async def child():
            return get_trace_id()

        # 子协程继承父协程的上下文
        result = asyncio.run(child())
        assert result == "parent-trace"
