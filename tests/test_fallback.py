"""
降级策略测试：乐观/保守模式
"""

from skill_self_evolution.deepseek import CircuitBreaker
from skill_self_evolution.fallback import FallbackConfig, FallbackMode, FallbackStrategy


class TestFallbackStrategy:
    """降级策略测试"""

    def test_optimistic_mode_default(self):
        config = FallbackConfig()
        strategy = FallbackStrategy(config, CircuitBreaker())
        assert strategy.mode == FallbackMode.OPTIMISTIC

    def test_conservative_mode(self):
        config = FallbackConfig(conservative_mode=True)
        strategy = FallbackStrategy(config, CircuitBreaker())
        assert strategy.mode == FallbackMode.CONSERVATIVE

    def test_check_before_ai_normal(self):
        config = FallbackConfig()
        strategy = FallbackStrategy(config, CircuitBreaker())
        result = strategy.check_before_ai()
        assert result.skip_ai is False

    def test_check_before_ai_disabled(self):
        config = FallbackConfig(enabled=False)
        strategy = FallbackStrategy(config, CircuitBreaker())
        result = strategy.check_before_ai()
        assert result.skip_ai is True
        assert "禁用" in result.reason

    def test_check_before_ai_circuit_open(self):
        cb = CircuitBreaker(threshold=1)
        cb.record_failure()
        config = FallbackConfig(conservative_mode=True)
        strategy = FallbackStrategy(config, cb)
        result = strategy.check_before_ai()
        assert result.skip_ai is True
        assert result.needs_review is True

    def test_on_validate_failure_optimistic(self):
        config = FallbackConfig()
        strategy = FallbackStrategy(config, CircuitBreaker())
        result = strategy.on_validate_failure(RuntimeError("timeout"))
        assert result.skip_ai is True
        assert result.needs_review is False

    def test_on_validate_failure_conservative(self):
        config = FallbackConfig(conservative_mode=True)
        strategy = FallbackStrategy(config, CircuitBreaker())
        result = strategy.on_validate_failure(RuntimeError("timeout"))
        assert result.skip_ai is True
        assert result.needs_review is True
        assert any("需人工复核" in w for w in result.warnings)

    def test_on_reselect_failure_optimistic(self):
        config = FallbackConfig()
        strategy = FallbackStrategy(config, CircuitBreaker())
        result = strategy.on_reselect_failure(RuntimeError("timeout"))
        assert result.skip_ai is True
        assert result.needs_review is False

    def test_on_reselect_failure_conservative(self):
        config = FallbackConfig(conservative_mode=True)
        strategy = FallbackStrategy(config, CircuitBreaker())
        result = strategy.on_reselect_failure(RuntimeError("timeout"))
        assert result.skip_ai is True
        assert result.needs_review is True
