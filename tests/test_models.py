"""
模型验证测试：SkillInput[T] + SkillOutput
"""

import pytest
from pydantic import BaseModel, ValidationError

from skill_self_evolution.models import SkillInput, SkillOutput


class TestInputData(BaseModel):
    name: str
    value: int = 0


class TestSkillOutput:
    """SkillOutput 模型测试"""

    def test_default_values(self):
        output = SkillOutput(source="rule", result={"key": "value"})
        assert output.source == "rule"
        assert output.result == {"key": "value"}
        assert output.ai_validated is False
        assert output.ai_reselected is False
        assert output.warnings == []

    def test_with_ai_validation(self):
        output = SkillOutput(
            source="ai",
            result={"nickname": "张三"},
            ai_validated=True,
            ai_reselected=True,
        )
        assert output.source == "ai"
        assert output.ai_validated is True
        assert output.ai_reselected is True

    def test_warnings_preserved(self):
        output = SkillOutput(
            source="rule",
            result={},
            warnings=["需人工复核"],
        )
        assert "需人工复核" in output.warnings

    def test_source_must_be_provided(self):
        with pytest.raises(ValidationError):
            SkillOutput(result={})


class TestSkillInput:
    """SkillInput[T] 泛型测试"""

    def test_with_custom_data(self):
        inp = SkillInput(input_data=TestInputData(name="test", value=42))
        assert inp.input_data.name == "test"
        assert inp.input_data.value == 42
        assert inp.trace_id is not None

    def test_trace_id_autogen(self):
        inp = SkillInput(input_data={"key": "value"})
        assert len(inp.trace_id) > 0
        # UUID v4 格式
        assert len(inp.trace_id) == 36
        assert inp.trace_id.count("-") == 4

    def test_trace_id_custom(self):
        custom = "my-custom-trace-id-12345"
        inp = SkillInput(trace_id=custom, input_data={})
        assert inp.trace_id == custom

    def test_serialization(self):
        inp = SkillInput(input_data={"key": "value"}, trace_id="abc-123")
        d = inp.model_dump()
        assert d["trace_id"] == "abc-123"
        assert d["input_data"] == {"key": "value"}
