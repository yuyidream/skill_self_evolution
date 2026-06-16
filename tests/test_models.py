"""
Pydantic 模型校验测试

覆盖：
- CandidateInput（已有）
- RulesConfigModel / PromptConfigModel（P0 外部输入）
- EvolveTomlModel / EvolvePromptYamlModel（P0 外部输入）
- RejectionRuleItem / RuleResultDict（P1 内部传递）
- CodeIssueModel / FunctionContextModel / LayerResultModel / GateResultModel（P2 门禁）
"""

import json
import pytest
from pydantic import ValidationError

from skill_self_evolution.models import (
    BlockCandidate,
    CandidateInput,
    CodeIssueModel,
    EvolveGuardModel,
    FunctionContextModel,
    GateResultModel,
    GeometryRuleParams,
    LayerResultModel,
    OcrBlock,
    PromptConfigModel,
    RejectionRuleItem,
    RuleResultDict,
    RulesConfigModel,
    SessionInput,
    EvolveTomlModel,
    EvolvePromptYamlModel,
)


# ── CandidateInput（已有） ──

class TestCandidateInput:
    def test_valid(self):
        ci = CandidateInput(candidates=["张三", "李四"])
        assert ci.candidates == ["张三", "李四"]

    def test_empty_list_rejected(self):
        with pytest.raises(ValidationError):
            CandidateInput(candidates=[])

    def test_candidates_json_roundtrip(self):
        data = {"candidates": ["张三", "李四", "王五"]}
        ci = CandidateInput.model_validate(data)
        assert len(ci.candidates) == 3

    def test_min_length_1(self):
        ci = CandidateInput(candidates=["只有一条"])
        assert ci.candidates == ["只有一条"]


# ── P0: RejectionRuleItem ──

class TestRejectionRuleItem:
    def test_valid_regex(self):
        r = RejectionRuleItem(type="regex", pattern="^警惕", action="drop")
        assert r.type == "regex"
        assert r.pattern == "^警惕"

    def test_valid_prefix(self):
        r = RejectionRuleItem(type="prefix", keywords=["@", "撤回"], action="drop")
        assert r.keywords == ["@", "撤回"]

    def test_valid_length(self):
        r = RejectionRuleItem(type="length", min=2, max=30, action="drop")
        assert r.min == 2
        assert r.max == 30

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            RejectionRuleItem(type="unknown", action="drop")

    def test_defaults(self):
        r = RejectionRuleItem(type="regex", pattern="test")
        assert r.action == "drop"
        assert r.keywords == []
        assert r.min == 0

    def test_extra_fields_allowed(self):
        """extra=allow：不破坏 Evolver 动态新增字段的能力"""
        r = RejectionRuleItem.model_validate({
            "type": "regex",
            "pattern": "test",
            "action": "drop",
            "min_overlap_area_ratio": 0.3,  # 额外字段
        })
        assert r.type == "regex"


# ── P0: RulesConfigModel ──

class TestRulesConfigModel:
    def test_minimal(self):
        rc = RulesConfigModel()
        assert rc.rejection_rules == []

    def test_full_config(self):
        data = {
            "correctness_criteria": {
                "bad_categories": [
                    {"name": "安全横幅", "patterns": ["^警惕"]},
                ],
                "verification_conditions": [
                    {"id": "click_coordinate", "description": "坐标检查"},
                ],
            },
            "rejection_rules": [
                {"type": "regex", "pattern": "^警惕", "action": "drop"},
            ],
            "nickname_thresholds": {
                "min_confidence": 0.7,
                "nickname_max_chars": 30,
            },
            "ai_fallback": {
                "validate_timeout_seconds": 3,
            },
        }
        rc = RulesConfigModel.model_validate(data)
        assert len(rc.rejection_rules) == 1
        assert len(rc.correctness_criteria.bad_categories) == 1
        assert rc.nickname_thresholds.min_confidence == 0.7

    def test_extra_fields_allowed(self):
        """Evolver 新增 verification_conditions 字段不应被拒绝"""
        data = {
            "rejection_rules": [{"type": "regex", "pattern": "test"}],
            "custom_section": {"key": "value"},
        }
        rc = RulesConfigModel.model_validate(data)
        assert len(rc.rejection_rules) == 1

    def test_bad_rule_rejected(self):
        with pytest.raises(ValidationError):
            RulesConfigModel.model_validate({
                "rejection_rules": [{"type": "invalid", "action": "drop"}],
            })


# ── P0: PromptConfigModel ──

class TestPromptConfigModel:
    def test_minimal(self):
        pc = PromptConfigModel()
        assert pc.system_prompt == ""

    def test_full(self):
        data = {
            "system_prompt": "你是专家",
            "user_template_validate": "判断：{{result}}",
            "user_template_reselect": "重选：{{candidates}}",
            "extra_field": "allowed",
        }
        pc = PromptConfigModel.model_validate(data)
        assert pc.system_prompt == "你是专家"
        assert pc.user_template_validate == "判断：{{result}}"


# ── P0: EvolveTomlModel ──

class TestEvolveTomlModel:
    def test_defaults(self):
        et = EvolveTomlModel()
        assert et.skill.ai_role == "correction"
        assert et.evolve.guard.require_benchmark_pass is True

    def test_full(self):
        data = {
            "skill": {"ai_role": "correction"},
            "evolve": {
                "auto_modify": {
                    "rules_config": {"mode": "full", "max_change_percent": 15},
                    "prompt": False,
                },
                "guard": {"require_benchmark_pass": True},
            },
        }
        et = EvolveTomlModel.model_validate(data)
        rc = et.evolve.auto_modify.rules_config
        assert isinstance(rc, object)  # Pydantic model
        assert rc.mode == "full"  # type: ignore[union-attr]

    def test_extra_allowed(self):
        data = {"skill": {"ai_role": "enhancement"}, "custom": "yes"}
        et = EvolveTomlModel.model_validate(data)
        assert et.skill.ai_role == "enhancement"


# ── P0: EvolvePromptYamlModel ──

class TestEvolvePromptYamlModel:
    def test_defaults(self):
        ep = EvolvePromptYamlModel()
        assert ep.system == ""

    def test_full(self):
        data = {
            "system": "你是配置优化专家",
            "analyze_template": "分析：{{failure_logs}}",
        }
        ep = EvolvePromptYamlModel.model_validate(data)
        assert ep.system == "你是配置优化专家"


# ── P1: RuleResultDict ──

class TestRuleResultDict:
    def test_defaults(self):
        rr = RuleResultDict()
        assert rr.candidates == []
        assert rr.result == ""

    def test_with_data(self):
        rr = RuleResultDict(candidates=["张三", "李四"], result="张三")
        assert rr.result == "张三"
        assert len(rr.candidates) == 2

    def test_roundtrip(self):
        rr = RuleResultDict(candidates=["张三"], result="张三")
        d = rr.model_dump()
        rr2 = RuleResultDict.model_validate(d)
        assert rr2.result == "张三"


# ── P2: CodeIssueModel ──

class TestCodeIssueModel:
    def test_minimal(self):
        ci = CodeIssueModel(rule="test_rule", level="error", message="bad")
        assert ci.rule == "test_rule"
        assert ci.level == "error"

    def test_full(self):
        ci = CodeIssueModel(
            rule="no_bare_except",
            level="error",
            message="bare except",
            file="test.py",
            line=42,
            col=5,
        )
        assert ci.line == 42
        assert ci.col == 5


# ── P2: FunctionContextModel ──

class TestFunctionContextModel:
    def test_module_level(self):
        fc = FunctionContextModel(
            name="my_func",
            is_method=False,
            params=["cx", "cy"],
            local_vars=["result"],
        )
        assert fc.self_forbidden is True
        prompt = fc.context_for_prompt()
        assert "NO self" in prompt
        assert "FORBIDDEN: self" in prompt

    def test_method(self):
        fc = FunctionContextModel(
            name="process",
            is_method=True,
            params=["self", "data"],
            local_vars=["tmp"],
        )
        assert fc.self_forbidden is False


# ── P2: LayerResultModel ──

class TestLayerResultModel:
    def test_minimal(self):
        lr = LayerResultModel(layer=1, layer_name="static", passed=True)
        assert lr.layer == 1
        assert lr.passed is True
        assert lr.issues == []

    def test_with_issues(self):
        issue = CodeIssueModel(rule="r", level="error", message="m")
        lr = LayerResultModel(
            layer=2, layer_name="unit", passed=False,
            issues=[issue], output="FAILED", elapsed_ms=123.4,
        )
        assert len(lr.issues) == 1
        assert lr.output == "FAILED"


# ── P2: GateResultModel ──

class TestGateResultModel:
    def test_passed(self):
        gr = GateResultModel(
            passed=True,
            layers=[
                LayerResultModel(layer=1, layer_name="static", passed=True),
                LayerResultModel(layer=2, layer_name="unit", passed=True),
            ],
        )
        assert gr.passed is True
        assert gr.failed_layer is None

    def test_failed_layer3(self):
        gr = GateResultModel(
            passed=False,
            layers=[
                LayerResultModel(layer=1, layer_name="static", passed=True),
                LayerResultModel(layer=2, layer_name="unit", passed=True),
                LayerResultModel(layer=3, layer_name="integration", passed=False, output="FAILED"),
            ],
        )
        assert gr.passed is False
        assert gr.failed_layer == 3

    def test_feedback(self):
        gr = GateResultModel(passed=False, feedback="error message")
        assert "error" in gr.feedback


# ── 新增：OcrBlock ──

class TestOcrBlock:
    def test_minimal(self):
        block = OcrBlock(text="昵称A")
        assert block.text == "昵称A"
        assert block.bbox_xyxy == [0, 0, 0, 0]
        assert block.class_ == ""
        assert block.confidence == 0.0

    def test_computed_properties(self):
        block = OcrBlock(
            text="测试",
            bbox_xyxy=[50, 100, 250, 130],
            class_="nickname_candidate",
            confidence=0.95,
            band="B1",
        )
        assert block.width == 200.0
        assert block.height == 30.0
        assert block.center_x == 150.0
        assert block.center_y == 115.0
        assert block.left == 50
        assert block.top == 100
        assert block.right == 250
        assert block.bottom == 130

    def test_extra_fields_allowed(self):
        block = OcrBlock(text="x", extra_field=42)
        assert block.text == "x"

    def test_class_alias(self):
        block = OcrBlock(text="x", **{"class": "nickname_candidate"})
        assert block.class_ == "nickname_candidate"


# ── 新增：GeometryRuleParams ──

class TestGeometryRuleParams:
    def test_defaults(self):
        params = GeometryRuleParams()
        assert params.screen_width == 0
        assert params.char_height_median == 0

    def test_full(self):
        params = GeometryRuleParams(
            screen_width=1080, screen_height=2340,
            midline_y=1170, avatar_column_left=50,
            avatar_column_right=120, char_height_median=28.0,
        )
        assert params.screen_width == 1080
        assert params.char_height_median == 28.0


# ── 新增：SessionInput ──

class TestSessionInput:
    def test_defaults(self):
        si = SessionInput()
        assert si.session_dir == ""
        assert si.screenshot_id == ""

    def test_full(self):
        si = SessionInput(session_dir="/data/sessions/abc", screenshot_id="scr_001")
        assert si.session_dir == "/data/sessions/abc"


# ── 新增：BlockCandidate ──

class TestBlockCandidate:
    def test_valid(self):
        block = OcrBlock(text="候选昵称")
        bc = BlockCandidate(block=block, source_file="debug.json", is_pipeline_selected=True)
        assert bc.block.text == "候选昵称"
        assert bc.is_pipeline_selected is True

    def test_default_selected(self):
        bc = BlockCandidate(block=OcrBlock(text="x"))
        assert bc.is_pipeline_selected is False


# ── 新增：EvolveGuardModel 新字段 ──

class TestEvolveGuardModel:
    def test_defaults(self):
        guard = EvolveGuardModel()
        assert guard.min_failure_count == 10
        assert guard.max_cases_per_batch == 20
        assert guard.dry_run is False
        assert guard.require_benchmark_pass is True

    def test_custom(self):
        guard = EvolveGuardModel(
            min_failure_count=5, max_cases_per_batch=10, dry_run=True,
        )
        assert guard.min_failure_count == 5
        assert guard.max_cases_per_batch == 10
        assert guard.dry_run is True


# ── 新增：RejectionRuleItem geometry type ──

class TestRejectionRuleItemGeometry:
    def test_geometry_type_accepted(self):
        rule = RejectionRuleItem(
            type="geometry",
            action="drop",
            description="头像列过滤",
            constraint="avatar_column",
            operator="lt",
            value=100.0,
        )
        assert rule.type == "geometry"
        assert rule.description == "头像列过滤"
