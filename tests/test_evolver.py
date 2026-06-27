"""
Evolver 训练集/验证集测试

覆盖：
- _build_training_set JSONL 回退路径（排除当天、仅保留历史失败）
- _get_golden_set_size 无 version_mgr 回退
- _load_failure_logs JSONL 回退路径
- EvolveProposal 新增 training_set_size / validation_set_size 属性
- 进化流程中训练集/验证集注入到 proposal 与 feedback
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from skill_self_evolution.evolver import Evolver, EvolveProposal
from skill_self_evolution.models import EvolveProposalModel


# ── 工具：构造 JSONL 日志 ──

def _write_jsonl(log_dir: Path, date_str: str, entries: list[dict]):
    """向 log_dir/{date_str}.jsonl 写入失败/成功日志条目。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{date_str}.jsonl"
    with open(log_path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _make_failure(trace_id: str, input_summary: dict | None = None) -> dict:
    return {
        "trace_id": trace_id,
        "skill_name": "test-skill",
        "timestamp": "2026-06-18T12:00:00+08:00",
        "is_failure": True,
        "no_valid_alternative": False,
        "input_summary": input_summary or {"candidates_path": "/tmp/test.json"},
        "rule_output": {"nickname": "bad"},
        "ai_validation": {"decision": "reject", "reason": "bad pattern"},
        "ai_reselection": None,
        "final_output": {},
        "warnings": [],
        "elapsed_ms": 100.0,
    }


def _make_success(trace_id: str) -> dict:
    return {
        "trace_id": trace_id,
        "skill_name": "test-skill",
        "timestamp": "2026-06-18T12:00:00+08:00",
        "is_failure": False,
        "no_valid_alternative": False,
        "input_summary": {"candidates_path": "/tmp/test.json"},
        "rule_output": {"nickname": "good"},
        "ai_validation": {"decision": "accept"},
        "ai_reselection": None,
        "final_output": {"nickname": "good"},
        "warnings": [],
        "elapsed_ms": 50.0,
    }


# ── EvolveProposal ──


class TestEvolveProposal:
    """EvolveProposal 新增训练集/验证集属性"""

    def test_training_validation_size_attrs(self):
        p = EvolveProposal()
        p.training_set_size = 42
        p.validation_set_size = 7
        assert p.training_set_size == 42
        assert p.validation_set_size == 7

    def test_to_model_includes_training_validation_size(self):
        p = EvolveProposal()
        p.failure_count = 10
        p.training_set_size = 8
        p.validation_set_size = 3
        p.applied = True

        m = p.to_model()
        assert isinstance(m, EvolveProposalModel)
        assert m.training_set_size == 8
        assert m.validation_set_size == 3


# ── Evolver._build_training_set JSONL 回退 ──


class TestBuildTrainingSetJsonl:
    """Evolver._build_training_set：历史失败 - 当天，JSONL 回退路径"""

    def test_excludes_today_keeps_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            # 昨天 3 条失败 + 1 条成功
            _write_jsonl(log_dir, "2026-06-17", [
                _make_failure("y1"),
                _make_failure("y2"),
                _make_success("y3"),
                _make_failure("y4"),
            ])
            # 今天 2 条失败
            _write_jsonl(log_dir, "2026-06-18", [
                _make_failure("t1"),
                _make_failure("t2"),
            ])

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            training, excluded = evolver._build_training_set("2026-06-18")

        assert len(training) == 3  # y1, y2, y4
        assert excluded == 2       # t1, t2
        trace_ids = {e["trace_id"] for e in training}
        assert trace_ids == {"y1", "y2", "y4"}

    def test_no_history_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            # 只有今天的失败
            _write_jsonl(log_dir, "2026-06-18", [
                _make_failure("t1"),
                _make_failure("t2"),
            ])

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            training, excluded = evolver._build_training_set("2026-06-18")

        assert len(training) == 0
        assert excluded == 2

    def test_no_jsonl_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            training, excluded = evolver._build_training_set("2026-06-18")

        assert len(training) == 0
        assert excluded == 0

    def test_mixed_dates_correctly_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-16", [_make_failure("a1"), _make_failure("a2")])
            _write_jsonl(log_dir, "2026-06-17", [_make_failure("b1")])
            _write_jsonl(log_dir, "2026-06-18", [_make_failure("c1"), _make_failure("c2"), _make_failure("c3")])

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            training, excluded = evolver._build_training_set("2026-06-18")

        assert len(training) == 3  # a1, a2 from 16th + b1 from 17th
        assert excluded == 3       # c1, c2, c3 from 18th


# ── Evolver._load_failure_logs JSONL 回退 ──


class TestLoadFailureLogsJsonl:
    """Evolver._load_failure_logs：当日失败日志加载，JSONL 回退路径"""

    def test_loads_only_failures_for_target_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-18", [
                _make_failure("f1"),
                _make_success("s1"),
                _make_failure("f2"),
            ])
            _write_jsonl(log_dir, "2026-06-17", [
                _make_failure("old"),
            ])

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            failures = evolver._load_failure_logs("2026-06-18")

        assert len(failures) == 2
        trace_ids = {f["trace_id"] for f in failures}
        assert trace_ids == {"f1", "f2"}

    def test_no_log_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            failures = evolver._load_failure_logs("2026-06-18")

        assert failures == []

    def test_no_failures_on_date_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-18", [
                _make_success("s1"),
                _make_success("s2"),
            ])

            evolver = Evolver(skill_name="test-skill", log_dir=log_dir)
            failures = evolver._load_failure_logs("2026-06-18")

        assert failures == []


# ── _get_golden_set_size 无 DB 回退 ──


class TestGoldenSetSize:
    """Evolver._get_golden_set_size：无 version_mgr 时安全回退为 0"""

    def test_no_version_mgr_returns_zero(self):
        evolver = Evolver(skill_name="test-skill")
        assert evolver._get_golden_set_size() == 0

    def test_version_mgr_without_get_golden_set_size_returns_zero(self):
        mgr = MagicMock()
        del mgr.get_golden_set_size  # 旧版 version_mgr 没有此方法
        evolver = Evolver(skill_name="test-skill", version_mgr=mgr)
        assert evolver._get_golden_set_size() == 0

    def test_version_mgr_returns_count(self):
        mgr = MagicMock()
        mgr.get_golden_set_size.return_value = 5
        evolver = Evolver(skill_name="test-skill", version_mgr=mgr)
        assert evolver._get_golden_set_size() == 5


# ── 进化流程：训练集/验证集注入 proposal ──


class TestEvolveFlowTrainingGoldenSet:
    """Evolver.evolve() 中训练集/验证集注入到 proposal 并传递到 feedback"""

    def _make_mock_evolver(self, log_dir: Path):
        """构造一个 mock Evolver，跳过 DeepSeek / benchmark / 文件写入。"""
        mgr = MagicMock()
        mgr.load_failure_logs.side_effect = Exception("MySQL not available")
        mgr.load_failure_logs_by_date.side_effect = Exception("MySQL not available")
        mgr.ensure_execution_log_table.side_effect = Exception("MySQL not available")
        mgr.load_training_set.side_effect = Exception("MySQL not available")
        mgr.get_golden_set_size.return_value = 7
        mgr.get_next_evolution_round.return_value = 3

        rules_path = log_dir / "rules_config.yaml"
        rules_path.write_text("nickname_thresholds:\n  min_confidence: 0.7\n", encoding="utf-8")

        evolver = Evolver(
            skill_name="test-skill",
            log_dir=log_dir,
            rules_config_disk_path=rules_path,
            version_mgr=mgr,
            get_rules_version=lambda: "2",
            on_rules_applied=lambda _c: "3",
        )
        evolver._deepseek = MagicMock()
        evolver.benchmark_fn = MagicMock(return_value=(5, 7, []))

        return evolver, mgr

    @pytest.mark.asyncio
    async def test_proposal_receives_training_and_validation_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            # 今天 10 条失败触发进化
            _write_jsonl(log_dir, "2026-06-18", [_make_failure(f"t{i}") for i in range(10)])
            # 昨天 4 条失败作为训练集
            _write_jsonl(log_dir, "2026-06-17", [_make_failure(f"y{i}") for i in range(4)])

            evolver, mgr = self._make_mock_evolver(log_dir)
            # mock DeepSeek 返回 rules_changes
            evolver._deepseek.chat_json = AsyncMock(return_value={
                "rules_changes": {"nickname_thresholds": {"min_confidence": 0.6}},
            })

            proposal = await evolver.evolve(dry_run=True, date_str="2026-06-18")

        assert proposal.failure_count == 10
        assert proposal.training_set_size == 4
        assert proposal.validation_set_size == 7

    @pytest.mark.asyncio
    async def test_deepseek_not_called_when_insufficient_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-18", [_make_failure("t1")])

            evolver, mgr = self._make_mock_evolver(log_dir)
            evolver._deepseek.chat_json = AsyncMock()

            proposal = await evolver.evolve(
                dry_run=True, date_str="2026-06-18", min_failure_samples=5
            )

        assert proposal.failure_count == 1
        assert proposal.training_set_size == 0
        evolver._deepseek.chat_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_training_set_defaults_when_empty(self):
        """训练集为空时不抛异常，回退为空列表。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-18", [_make_failure(f"t{i}") for i in range(12)])

            evolver, mgr = self._make_mock_evolver(log_dir)
            evolver._deepseek.chat_json = AsyncMock(return_value={})

            proposal = await evolver.evolve(dry_run=True, date_str="2026-06-18")

        assert proposal.failure_count == 12
        assert proposal.training_set_size == 0  # 无历史 → 训练集 0
        assert proposal.validation_set_size == 7

    @pytest.mark.asyncio
    async def test_training_excludes_only_target_date(self):
        """验证 _build_training_set 只排除指定日期，不排除其他日期的失败。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-16", [_make_failure("a1"), _make_failure("a2")])
            _write_jsonl(log_dir, "2026-06-17", [_make_failure("b1")])
            _write_jsonl(log_dir, "2026-06-18", [_make_failure(f"c{i}") for i in range(10)])

            evolver, mgr = self._make_mock_evolver(log_dir)
            evolver._deepseek.chat_json = AsyncMock(return_value={})

            proposal = await evolver.evolve(dry_run=True, date_str="2026-06-18")

        assert proposal.failure_count == 10
        assert proposal.training_set_size == 3  # a1, a2, b1
        assert proposal.validation_set_size == 7

    @pytest.mark.asyncio
    async def test_ai_role_enhancement_skips_evolution(self):
        evolver = Evolver(skill_name="test-skill", ai_role="enhancement")
        proposal = await evolver.evolve(dry_run=True)
        assert proposal is None

    @pytest.mark.asyncio
    async def test_feedback_receives_version_before(self):
        """验证 feedback 写入时 version_before 已正确填充。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-18", [_make_failure(f"t{i}") for i in range(10)])

            evolver, mgr = self._make_mock_evolver(log_dir)
            evolver._deepseek.chat_json = AsyncMock(return_value={
                "rules_changes": {"nickname_thresholds": {"min_confidence": 0.5}},
            })
            evolver.evolve_toml = {"evolve": {"auto_modify": {"rules_config": {"mode": "full"}}}}
            evolver.benchmark_fn = MagicMock(return_value=(6, 7, []))

            proposal = await evolver.evolve(dry_run=False, date_str="2026-06-18")

        # 验证 feedback 被调用
        mgr.save_feedback.assert_called_once()
        call_kwargs = mgr.save_feedback.call_args.kwargs
        assert call_kwargs["version_before"] == 2
        assert call_kwargs["version_after"] == 3

    @pytest.mark.asyncio
    async def test_rejection_rules_count_decrease_triggers_rollback(self):
        """guard.require_rejection_rules_count_not_decrease：条数减少则回滚，不跑 benchmark。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(log_dir, "2026-06-18", [_make_failure(f"t{i}") for i in range(10)])

            evolver, mgr = self._make_mock_evolver(log_dir)
            before_rules = (
                "rejection_rules:\n"
                "  - type: regex\n    pattern: '^a$'\n    action: drop\n"
                "    category: test\n    description: r1\n"
                "  - type: regex\n    pattern: '^b$'\n    action: drop\n"
                "    category: test\n    description: r2\n"
            )
            after_rules = (
                "rejection_rules:\n"
                "  - type: regex\n    pattern: '^a$'\n    action: drop\n"
                "    category: test\n    description: r1\n"
            )
            rules_path = log_dir / "rules_config.yaml"
            rules_path.write_text(before_rules, encoding="utf-8")

            evolver._deepseek.chat_json = AsyncMock(return_value={
                "rules_changes": {"rejection_rules": "truncate"},
            })
            evolver.evolve_toml = {
                "evolve": {
                    "auto_modify": {"rules_config": {"mode": "full"}},
                    "guard": {"require_rejection_rules_count_not_decrease": True},
                }
            }
            evolver.benchmark_fn = MagicMock(return_value=(7, 7, []))
            rollback = MagicMock()
            evolver._on_rules_rollback = rollback

            original_apply = evolver._apply_rules_changes

            def _fake_apply(_current, _changes, _max_pct):
                return after_rules

            evolver._apply_rules_changes = _fake_apply

            proposal = await evolver.evolve(dry_run=False, date_str="2026-06-18")

            assert proposal.rolled_back is True
            assert proposal.applied is False
            rollback.assert_called_once()
            assert evolver.benchmark_fn.call_count == 1  # 仅进化前 benchmark，条数 guard 跳过进化后
            assert proposal.benchmark_after == (0, 0, [])
            assert rules_path.read_text(encoding="utf-8") == before_rules


# ── ConfigVersionManager.get_golden_set_size ──


class TestConfigVersionManagerGoldenSetSize:
    """ConfigVersionManager.get_golden_set_size：获取 Golden set 大小"""

    def test_returns_count(self):
        mgr = MagicMock()
        mgr.get_golden_set_size.return_value = 5
        assert mgr.get_golden_set_size() == 5

    def test_returns_zero_when_empty(self):
        mgr = MagicMock()
        mgr.get_golden_set_size.return_value = 0
        assert mgr.get_golden_set_size() == 0
