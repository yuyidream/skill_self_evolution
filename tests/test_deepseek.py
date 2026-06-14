"""
DeepSeek 客户端测试：CircuitBreaker 熔断器
"""

import time

from skill_self_evolution.deepseek import CircuitBreaker


class TestCircuitBreaker:
    """熔断器单元测试"""

    def test_initial_state(self):
        cb = CircuitBreaker()
        assert cb.is_open is False

    def test_circuit_opens_after_threshold(self):
        cb = CircuitBreaker(threshold=2, cooldown_seconds=60)
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True

    def test_circuit_stays_open_within_cooldown(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=99)
        cb.record_failure()
        assert cb.is_open is True

    def test_circuit_reopens_after_cooldown(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        assert cb.is_open is True
        time.sleep(0.02)
        assert cb.is_open is False

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(threshold=2)
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.is_open is False  # 只记录了 1 次失败

    def test_success_closes_open_circuit(self):
        cb = CircuitBreaker(threshold=1, cooldown_seconds=99)
        cb.record_failure()
        assert cb.is_open is True
        cb.record_success()
        assert cb.is_open is False
