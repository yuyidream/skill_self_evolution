"""
AiAssistedExecutor 基类测试：correction / enhancement 流程
"""

import pytest

from skill_self_evolution.models import SkillInput, SkillOutput, AiValidationResult, AiReselectionResult
from skill_self_evolution.fallback import FallbackConfig, FallbackStrategy
from skill_self_evolution.deepseek import CircuitBreaker
from skill_self_evolution.ai_assisted_executor import AiAssistedExecutor


class MockCorrectionExecutor(AiAssistedExecutor):
    """模拟 correction 角色执行器"""

    async def ai_validate(self, skill_input, rule_output, prompt_config) -> AiValidationResult:
        nickname = rule_output.result.get("nickname", "")
        if nickname == "阿姨派单群":
            return AiValidationResult(result="不合理", reason="这是群名不是人名")
        return AiValidationResult(result="合理", reason="看起来像真实昵称")

    async def ai_reselect(self, skill_input, rule_output, prompt_config) -> AiReselectionResult:
        return AiReselectionResult(result={"nickname": "张三"}, reason="")


class MockEnhancementExecutor(AiAssistedExecutor):
    """模拟 enhancement 角色执行器"""

    async def ai_validate(self, skill_input, rule_output, prompt_config) -> AiValidationResult:
        return AiValidationResult(result="合理", reason="")

    async def ai_reselect(self, skill_input, rule_output, prompt_config) -> AiReselectionResult:
        return AiReselectionResult(result="合理", reason="")

    async def ai_enhance(self, skill_input, rule_output, prompt_config) -> dict:
        return {"semantic_score": 18}


class MockSkillModule:
    """模拟 SkillModule"""
    def __init__(self, ai_role="correction"):
        self.skill_name = "mock-skill"
        self.ai_role = ai_role
        self.evolve_toml = {"skill": {"ai_role": ai_role}}
        self.evolve_prompt_yaml = {}
        self.summarize_input = None


@pytest.mark.asyncio
class TestAiAssistedCorrection:
    """AiAssistedExecutor correction 流程测试"""

    async def test_validate_pass(self):
        """AI 验证通过 → 返回规则结果"""
        executor = MockCorrectionExecutor()
        skill = MockSkillModule("correction")
        skill_input = SkillInput(input_data={"screenshot_id": "scr_001"})
        rule_output = SkillOutput(source="rule", result={"nickname": "张三"})
        fallback = FallbackStrategy(FallbackConfig(), CircuitBreaker())

        result = await executor.run_correction_flow(skill, skill_input, rule_output, None, fallback)
        assert result.source == "rule"
        assert result.ai_validated is True
        assert result.result == {"nickname": "张三"}

    async def test_validate_fail_then_reselect(self):
        """AI 验证不合理 → 触发重选 → 返回 AI 结果"""
        executor = MockCorrectionExecutor()
        skill = MockSkillModule("correction")
        skill_input = SkillInput(input_data={"screenshot_id": "scr_002"})
        rule_output = SkillOutput(source="rule", result={"nickname": "阿姨派单群"})
        fallback = FallbackStrategy(FallbackConfig(), CircuitBreaker())

        result = await executor.run_correction_flow(skill, skill_input, rule_output, None, fallback)
        assert result.source == "ai"
        assert result.ai_reselected is True
        assert result.result == {"nickname": "张三"}

    async def test_circuit_open_skips_ai(self):
        """熔断器开启 → 跳过 AI → 返回规则原始结果"""
        executor = MockCorrectionExecutor()
        skill = MockSkillModule("correction")
        skill_input = SkillInput(input_data={})
        rule_output = SkillOutput(source="rule", result={"nickname": "bad"})
        cb = CircuitBreaker(threshold=1)
        cb.record_failure()
        fallback = FallbackStrategy(FallbackConfig(conservative_mode=True), cb)

        result = await executor.run_correction_flow(skill, skill_input, rule_output, None, fallback)
        assert result.source == "rule"
        assert result.ai_validated is False


@pytest.mark.asyncio
class TestAiAssistedEnhancement:
    """AiAssistedExecutor enhancement 流程测试"""

    async def test_enhance_merges_result(self):
        """enhancement → AI 结果合并到规则结果"""
        executor = MockEnhancementExecutor()
        skill = MockSkillModule("enhancement")
        skill_input = SkillInput(input_data={})
        rule_output = SkillOutput(source="rule", result={"rule_score": 58})
        fallback = FallbackStrategy(FallbackConfig(), CircuitBreaker())

        result = await executor.run_enhancement_flow(skill, skill_input, rule_output, None, fallback)
        assert result.ai_validated is True
        assert result.result.get("rule_score") == 58
        assert result.result.get("semantic_score") == 18

    async def test_enhance_disabled_returns_rule_only(self):
        """AI 禁用 → 仅返回规则结果"""
        executor = MockEnhancementExecutor()
        skill = MockSkillModule("enhancement")
        skill_input = SkillInput(input_data={})
        rule_output = SkillOutput(source="rule", result={"rule_score": 58})
        fallback = FallbackStrategy(FallbackConfig(enabled=False), CircuitBreaker())

        result = await executor.run_enhancement_flow(skill, skill_input, rule_output, None, fallback)
        assert result.ai_validated is False
        assert result.result == {"rule_score": 58}
