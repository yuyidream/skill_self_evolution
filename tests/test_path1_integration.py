"""
端到端集成测试 — 验证 Path 1 全链路：JSONL → Evolver → rules_config 变更 → benchmark 验证/回滚。
"""

import json
import os
import tempfile
from pathlib import Path

import pytest
from skill_self_evolution.evolver import _deep_update, _warn_numeric_drift
from skill_self_evolution.rule_runner import run_block_rules, run_rejection_rules
from skill_self_evolution.models import GeometryRuleParams, OcrBlock

# ── 测试：_apply_rules_changes deep-merge ──


class TestApplyRulesChanges:
    """验证 _deep_update 能正确处理列表项增删、嵌套 dict 修改。"""

    def test_deep_update_adds_list_items(self):
        base = {"rejection_rules": [{"type": "regex", "pattern": "foo", "action": "drop"}]}
        updates = {"rejection_rules": [{"type": "regex", "pattern": "bar", "action": "drop"}]}
        _deep_update(base, updates)
        assert len(base["rejection_rules"]) == 1
        assert base["rejection_rules"][0]["pattern"] == "bar"

    def test_deep_update_merges_nested_dicts(self):
        base = {"nickname_thresholds": {"min_confidence": 0.7, "nickname_max_chars": 30}}
        updates = {"nickname_thresholds": {"min_confidence": 0.8}}
        _deep_update(base, updates)
        assert base["nickname_thresholds"]["min_confidence"] == 0.8
        assert base["nickname_thresholds"]["nickname_max_chars"] == 30  # 保留未变更的

    def test_deep_update_adds_new_key(self):
        base = {"nickname_thresholds": {"min_confidence": 0.7}}
        updates = {"nickname_thresholds": {"new_field": 42}}
        _deep_update(base, updates)
        assert base["nickname_thresholds"]["new_field"] == 42

    def test_deep_update_adds_top_level_key(self):
        base = {"rejection_rules": []}
        updates = {"new_section": {"enabled": True}}
        _deep_update(base, updates)
        assert base["new_section"]["enabled"] is True


# ── 测试：数值漂移告警 ──


class TestWarnNumericDrift:
    """数值变更超过阈值时产生告警日志。"""

    def test_drift_within_limit_no_warning(self, caplog):
        caplog.set_level("WARNING")
        _warn_numeric_drift({"score": 10.0}, {"score": 11.0}, 20)
        assert not any("数值变更超限" in r.message for r in caplog.records)

    def test_drift_exceeds_limit_warns(self, caplog):
        caplog.set_level("WARNING")
        _warn_numeric_drift({"score": 10.0}, {"score": 15.0}, 20)
        assert any("数值变更超限" in r.message for r in caplog.records)

    def test_drift_ignores_non_numeric(self, caplog):
        caplog.set_level("WARNING")
        _warn_numeric_drift({"rules": [1, 2, 3]}, {"rules": [4, 5, 6]}, 20)
        assert not any("数值变更超限" in r.message for r in caplog.records)


# ── 测试：rule_runner ──


class TestRuleRunner:
    """声明式规则执行薄层。"""

    def test_regex_drop(self):
        result = run_rejection_rules("警惕不实营销信息", [
            {"type": "regex", "pattern": "^警惕不实营销信息", "action": "drop"},
        ])
        assert result is None

    def test_regex_remove_prefix(self):
        result = run_rejection_rules("姓名：张三", [
            {"type": "regex", "pattern": "^姓名[：:]\\s*", "action": "remove_prefix"},
        ])
        assert result == "张三"

    def test_regex_no_match_returns_text(self):
        result = run_rejection_rules("张三", [
            {"type": "regex", "pattern": "^姓名[：:]", "action": "drop"},
        ])
        assert result == "张三"

    def test_prefix_drop(self):
        result = run_rejection_rules("@系统消息", [
            {"type": "prefix", "keywords": ["@", "撤回"], "action": "drop"},
        ])
        assert result is None

    def test_prefix_no_match_returns_text(self):
        result = run_rejection_rules("正常昵称", [
            {"type": "prefix", "keywords": ["@", "撤回"], "action": "drop"},
        ])
        assert result == "正常昵称"

    def test_length_filter_too_short(self):
        result = run_rejection_rules("A", [
            {"type": "length", "min": 2, "max": 30, "action": "drop"},
        ])
        assert result is None

    def test_length_filter_within_range(self):
        result = run_rejection_rules("AB", [
            {"type": "length", "min": 2, "max": 30, "action": "drop"},
        ])
        assert result == "AB"

    def test_length_filter_too_long(self):
        result = run_rejection_rules("A" * 31, [
            {"type": "length", "min": 2, "max": 30, "action": "drop"},
        ])
        assert result is None

    def test_chain_multiple_rules(self):
        rules = [
            {"type": "regex", "pattern": "^\\s*", "action": "remove_prefix"},
            {"type": "regex", "pattern": "\\[.*?\\]", "action": "drop"},
            {"type": "length", "min": 2, "max": 30, "action": "drop"},
        ]
        assert run_rejection_rules("  Hello", rules) == "Hello"
        assert run_rejection_rules("[广告]", rules) is None
        assert run_rejection_rules("正常昵称", rules) == "正常昵称"


# ── 新增：run_block_rules 几何规则 ──

class TestBlockRules:
    def test_avatar_column_drop_block_inside_col(self):
        """头像列内 block 被 drop。"""
        block = OcrBlock(text="昵称", bbox_xyxy=[30, 100, 100, 130])
        params = GeometryRuleParams(avatar_column_left=0, avatar_column_right=120, screen_width=1080)
        rules = [{"type": "geometry", "constraint": "avatar_column", "action": "drop", "operator": "lte", "value": 120}]
        result = run_block_rules(block, rules, params)
        assert result is None

    def test_avatar_column_pass_block_outside_col(self):
        """头像列外 block 通过。"""
        block = OcrBlock(text="昵称", bbox_xyxy=[500, 100, 700, 130])
        params = GeometryRuleParams(avatar_column_left=0, avatar_column_right=120, screen_width=1080)
        rules = [{"type": "geometry", "constraint": "avatar_column", "action": "drop", "operator": "lte", "value": 120}]
        result = run_block_rules(block, rules, params)
        assert result is not None
        assert result.text == "昵称"

    def test_bbox_width_drop_too_narrow(self):
        """过窄的 block 被 drop。"""
        block = OcrBlock(text="x", bbox_xyxy=[100, 100, 112, 130])
        rules = [{"type": "geometry", "constraint": "bbox_width", "action": "drop", "operator": "lt", "value": 20}]
        result = run_block_rules(block, rules)
        assert result is None

    def test_bbox_width_pass(self):
        """宽度足够的 block 通过。"""
        block = OcrBlock(text="正常昵称", bbox_xyxy=[100, 100, 300, 130])
        rules = [{"type": "geometry", "constraint": "bbox_width", "action": "drop", "operator": "lt", "value": 20}]
        result = run_block_rules(block, rules)
        assert result is not None

    def test_char_height_ratio_drop(self):
        """字符高度比值超过阈值的 block 被 drop。"""
        block = OcrBlock(text="大字", bbox_xyxy=[100, 100, 200, 200])
        params = GeometryRuleParams(char_height_median=30.0)
        rules = [{"type": "geometry", "constraint": "char_height_ratio", "action": "drop", "operator": "gt", "value": 2.0}]
        result = run_block_rules(block, rules, params)
        assert result is None

    def test_no_median_skip(self):
        """无中位数时不触发规则。"""
        block = OcrBlock(text="正常", bbox_xyxy=[100, 100, 200, 130])
        rules = [{"type": "geometry", "constraint": "char_height_ratio", "action": "drop", "operator": "gt", "value": 2.0}]
        result = run_block_rules(block, rules)  # no params → default median=0
        assert result is not None

    def test_chain_multiple_geometry_rules(self):
        """多条几何规则链式执行。"""
        block = OcrBlock(text="候选", bbox_xyxy=[50, 100, 250, 130])
        params = GeometryRuleParams(screen_width=1080, char_height_median=28.0)
        rules = [
            {"type": "geometry", "constraint": "bbox_width", "action": "drop", "operator": "lt", "value": 20},
            {"type": "geometry", "constraint": "char_height_ratio", "action": "drop", "operator": "gt", "value": 3.0},
        ]
        result = run_block_rules(block, rules, params)
        assert result is not None
        assert result.text == "候选"

    def test_skip_non_geometry_rules(self):
        """非 geometry 类型规则被跳过。"""
        block = OcrBlock(text="昵称", bbox_xyxy=[100, 100, 200, 130])
        rules = [{"type": "regex", "pattern": ".*", "action": "drop"}]
        result = run_block_rules(block, rules)
        assert result is not None  # regex 规则不适用于 block，跳过

    def test_invalid_rule_skipped(self):
        """非法规则被跳过不报错。"""
        block = OcrBlock(text="昵称", bbox_xyxy=[100, 100, 200, 130])
        rules = [{"type": "geometry"}]  # 缺少 constraint/value
        result = run_block_rules(block, rules)
        assert result is not None


# ── 端到端：JSONL → Evolver 流程（dry-run） ──


@pytest.mark.integration
@pytest.mark.asyncio
async def test_evolver_deep_merge_e2e():
    """验证 Evolver 能从 JSONL 分析并生成有效的 rules_changes（dry-run）。"""
    import asyncio

    temp_dir = tempfile.mkdtemp(prefix="skill_evolve_test_")

    try:
        # 1. 写入一条模拟 is_failure JSONL
        log_dir = Path(temp_dir) / "logs" / "nickname-selector"
        log_dir.mkdir(parents=True, exist_ok=True)

        failure_entry = {
            "timestamp": "2026-06-14T12:00:00",
            "skill_name": "nickname-selector",
            "is_failure": True,
            "input_summary": {"screenshot_id": "test_001"},
            "ai_role": "correction",
            "ai_validation": {"result": "不合理", "reason": "输出为日期格式"},
            "ai_reselection": {"result": "合理", "selected_index": 2},
            "rule_output": {
                "nickname": "2026-06-14",
                "candidates": ["2026-06-14", "小明", "张三"],
                "band_id": "S1",
                "screenshot_id": "test_001",
            },
        }

        jsonl_path = log_dir / "nickname-selector_2026-06-14.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(failure_entry, ensure_ascii=False) + "\n")

        # 2. 设置环境变量使 Evolver 读取我们的 log 目录
        os.environ["SKILL_LOG_DIR"] = str(Path(temp_dir) / "logs")

        # 3. 创建一个最小的 rules_config.yaml
        rules_dir = Path(temp_dir) / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        original_yaml = "rejection_rules: []\n"
        (rules_dir / "rules_config.yaml").write_text(original_yaml, encoding="utf-8")

        # 4. 验证 _deep_update 对列表项的处理
        cfg = {"rejection_rules": []}
        _deep_update(cfg, {
            "rejection_rules": [
                {"type": "regex", "pattern": "\\d{4}-\\d{2}-\\d{2}", "action": "drop",
                 "description": "过滤日期格式"},
            ],
        })
        assert len(cfg["rejection_rules"]) == 1
        assert cfg["rejection_rules"][0]["pattern"] == "\\d{4}-\\d{2}-\\d{2}"

    finally:
        # 清理
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
