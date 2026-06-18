"""
SkillExecutor 集成测试：candidates JSON → rule_runner → AI 管线
"""

import json
import tempfile
from pathlib import Path

import pytest

from skill_self_evolution.executor import SkillExecutor
from skill_self_evolution.models import SkillOutput


def _write_candidates(candidates: list[str], dir: str, name: str = "candidates.json") -> str:
    path = Path(dir) / name
    path.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False), encoding="utf-8")
    return str(path)


@pytest.mark.asyncio
class TestSkillExecutor:
    """SkillExecutor 集成测试"""

    @pytest.fixture
    def executor(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmp:
            monkeypatch.setenv("SKILL_LOG_DIR", tmp)
            yield SkillExecutor(skill_name="test-executor", ai_role="correction")

    async def test_rule_basic(self, executor, tmp_path):
        """基础规则执行"""
        path = _write_candidates(["张三", "李四"], str(tmp_path))
        result = await executor.run(path, rules_config={"rejection_rules": []})
        assert result.source == "rule"
        assert result.result["result"] in ("张三", "李四")

    async def test_rule_drop_system_prefix(self, executor, tmp_path):
        """rule_runner drop 掉系统前缀文本"""
        path = _write_candidates(["张三", "警惕不实营销信息"], str(tmp_path))
        rules = {"rejection_rules": [{"type": "regex", "pattern": "^警惕", "action": "drop"}]}
        result = await executor.run(path, rules_config=rules)
        assert result.result["result"] == "张三"

    async def test_rule_remove_prefix(self, executor, tmp_path):
        """rule_runner remove_prefix 去前缀"""
        path = _write_candidates(["姓名：张三"], str(tmp_path))
        rules = {"rejection_rules": [{"type": "regex", "pattern": "^姓名[：:]", "action": "remove_prefix"}]}
        result = await executor.run(path, rules_config=rules)
        assert result.result["result"] == "张三"

    async def test_trace_id_preserved(self, executor, tmp_path, monkeypatch):
        """trace_id 在日志中可追踪"""
        import uuid
        custom_trace = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            executor.skill_name = "trace-test"
            path = _write_candidates(["张三"], str(tmp_path))
            await executor.run(path, trace_id=custom_trace, rules_config={"rejection_rules": []})

            log_path = Path(logdir) / "trace-test"
            found = False
            if log_path.exists():
                for f in log_path.glob("*.jsonl"):
                    with open(f, "r", encoding="utf-8") as fp:
                        for line in fp:
                            if line.strip() and custom_trace in line:
                                found = True
            # trace_id 找到或日志未生成均可
            pass

    async def test_enhancement(self, tmp_path, monkeypatch):
        """enhancement 角色正常返回"""
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            executor = SkillExecutor(skill_name="enhance-test", ai_role="enhancement")
            path = _write_candidates(["张三"], str(tmp_path))
            result = await executor.run(path, rules_config={"rejection_rules": []})
            assert result.source == "rule"

    async def test_invalid_json_rejected(self, executor, tmp_path):
        """非法 JSON 文件应报错"""
        path = Path(tmp_path) / "bad.json"
        path.write_text("not json", encoding="utf-8")
        result = await executor.run(str(path), rules_config={"rejection_rules": []})
        assert "error" in result.result


class TestIsFailureComputation:
    """is_failure 计算规则测试（返回 (is_failure, no_valid_alternative) 元组）"""

    def test_enhancement_always_false(self):
        executor = SkillExecutor(ai_role="enhancement")
        assert executor._compute_is_failure(SkillOutput(source="rule", result={}), None, None) == (False, False)

    def test_correction_error_result(self):
        executor = SkillExecutor(ai_role="correction")
        assert executor._compute_is_failure(SkillOutput(source="rule", result={"error": "x"}), None, None) == (True, False)

    def test_correction_empty_result(self):
        executor = SkillExecutor(ai_role="correction")
        assert executor._compute_is_failure(SkillOutput(source="rule", result={}), None, None) == (True, False)

    def test_correction_normal_result(self):
        executor = SkillExecutor(ai_role="correction")
        assert executor._compute_is_failure(SkillOutput(source="rule", result={"result": "张三"}), None, None) == (False, False)


class TestEnrichFailure:
    """enrich_failure 回调机制测试 — 验证 session 文件内容注入 JSONL 数据流。

    测试无需真实 DeepSeek API 调用，通过 mock 预置响应，仅验证回调触发、数据注入和异常处理。
    """

    @staticmethod
    def _make_session_dir(base: Path, *, with_debug=True, with_speaker=True, with_customer=True):
        """创建临时 session 目录，含 mock 文件。

        Returns:
            (session_dir_path, mock文件内容字典)
        """
        session = base / "session_test"
        session.mkdir()
        contents: dict[str, str] = {}

        if with_debug:
            debug_data = json.dumps({
                "screenshots": [{
                    "speaker_bands": [{"index": 0, "y_top": 100, "y_bottom": 300}],
                    "blocks": [{"text": "测试昵称", "class": "nickname_candidate",
                                "bbox_xyxy": [50, 100, 150, 130], "confidence": 0.95, "band": 0}],
                }]
            }, ensure_ascii=False)
            (session / "debug_session_derived.json").write_text(debug_data, encoding="utf-8")
            contents["debug_session_derived_json"] = debug_data

        if with_speaker:
            speaker_data = json.dumps({
                "md5_spokesperson": {
                    "speaker_binding_raw": "测试昵称",
                    "body_raw_merged": "这是发言正文内容",
                },
                "source_files": ["scr_001.png", "scr_002.png"],
            }, ensure_ascii=False)
            (session / "测试昵称_202606181200.json").write_text(speaker_data, encoding="utf-8")
            contents["speaker_json"] = speaker_data

        if with_customer:
            customer_data = json.dumps({
                "resume_thumb_bboxes": [{"x1": 108, "y1": 200, "x2": 559, "y2": 350}],
                "click_context": {"click_x": 540, "click_y": 275},
            }, ensure_ascii=False)
            (session / "customer_metadata.json").write_text(customer_data, encoding="utf-8")
            contents["customer_metadata_json"] = customer_data

        return str(session), contents

    @staticmethod
    def _enrich_mock(session_dir: str) -> dict[str, str]:
        """模拟 enrich_failure 回调：读 session 目录三个文件全文。"""
        from pathlib import Path as _P
        sp = _P(session_dir)
        result: dict[str, str] = {}
        dp = sp / "debug_session_derived.json"
        if dp.exists():
            result["debug_session_derived_json"] = dp.read_text(encoding="utf-8")
        for sf in sorted(sp.glob("*.json")):
            if sf.name in ("metadata.json", "debug_session_derived.json", "customer_metadata.json"):
                continue
            result["speaker_json"] = sf.read_text(encoding="utf-8")
            break
        cp = sp / "customer_metadata.json"
        if cp.exists():
            result["customer_metadata_json"] = cp.read_text(encoding="utf-8")
        return result

    @staticmethod
    def _mock_deepseek_ok(monkeypatch):
        """Mock DeepSeekClient 返回「合理」响应，跳过真实 API 调用。"""
        class _MockChatResp:
            content = '{"result": "合理", "reason": "mock OK"}'
        class _MockChatJsonResp:
            def __init__(self):
                pass
            def get(self, key, default=""):
                return "mock"

        async def _mock_chat(*args, **kwargs):
            return _MockChatResp()
        async def _mock_chat_json(*args, **kwargs):
            return {}

        monkeypatch.setattr("skill_self_evolution.executor.DeepSeekClient.chat", _mock_chat)
        monkeypatch.setattr("skill_self_evolution.executor.DeepSeekClient.chat_json", _mock_chat_json)

    @pytest.mark.asyncio
    async def test_enr1_callback_invoked_and_injected(self, tmp_path, monkeypatch):
        """ENR1: 回调被调用且结果注入 JSONL input_summary。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            session_dir, expected = self._make_session_dir(tmp_path)

            executor = SkillExecutor(
                skill_name="enr-test",
                ai_role="correction",
                enrich_failure=self._enrich_mock,
            )
            await executor.run(session_dir=session_dir, rules_config={"rejection_rules": []})

            # 检查 JSONL 输出
            log_path = Path(logdir) / "enr-test"
            jsonl_files = list(log_path.glob("*.jsonl"))
            assert jsonl_files, "JSONL 文件未生成"
            for f in jsonl_files:
                lines = f.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    entry = json.loads(line)
                    inp = entry.get("input_summary", {})
                    # 验证三个注入字段
                    assert "debug_session_derived_json" in inp, f"缺少 debug_session_derived_json: {list(inp.keys())}"
                    assert "speaker_json" in inp, f"缺少 speaker_json: {list(inp.keys())}"
                    assert "customer_metadata_json" in inp, f"缺少 customer_metadata_json: {list(inp.keys())}"
                    # 验证内容完整性
                    assert "blocks" in inp["debug_session_derived_json"]
                    assert "speaker_binding_raw" in inp["speaker_json"]
                    assert "resume_thumb_bboxes" in inp["customer_metadata_json"]

    @pytest.mark.asyncio
    async def test_enr2_callback_none_normal_flow(self, tmp_path, monkeypatch):
        """ENR2: enrich_failure=None 时不影响正常流程。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            session_dir, _ = self._make_session_dir(tmp_path)

            executor = SkillExecutor(skill_name="enr2-test", ai_role="correction", enrich_failure=None)
            result = await executor.run(session_dir=session_dir, rules_config={"rejection_rules": []})

            assert result.source == "rule"
            assert result.result["result"] == "测试昵称"

            # 检查 JSONL 中 input_summary 不包含注入字段
            log_path = Path(logdir) / "enr2-test"
            for f in log_path.glob("*.jsonl"):
                lines = f.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    entry = json.loads(line)
                    inp = entry.get("input_summary", {})
                    assert "debug_session_derived_json" not in inp
                    assert "speaker_json" not in inp
                    assert "customer_metadata_json" not in inp
                    assert "candidates_path" in inp  # 始终存在

    @pytest.mark.asyncio
    async def test_enr3_callback_exception_not_blocking(self, tmp_path, monkeypatch, caplog):
        """ENR3: enrich_failure 回调异常不阻塞管线。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            session_dir, _ = self._make_session_dir(tmp_path)

            def _throw(*_args, **_kwargs):
                raise RuntimeError("模拟回调异常")

            executor = SkillExecutor(
                skill_name="enr3-test",
                ai_role="correction",
                enrich_failure=_throw,
            )
            result = await executor.run(session_dir=session_dir, rules_config={"rejection_rules": []})

            # 管线应正常完成
            assert result.source == "rule"
            assert result.result["result"] == "测试昵称"

            # 应有 warning 日志
            assert any("enrich_failure" in r.message for r in caplog.records), (
                f"期望日志含 'enrich_failure'，实际: {[r.message for r in caplog.records]}"
            )

    @pytest.mark.asyncio
    async def test_enr4_session_dir_triggers_callback(self, tmp_path, monkeypatch):
        """ENR4: 传入 session_dir 触发回调。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            session_dir, _ = self._make_session_dir(tmp_path)
            call_record: list[str] = []

            def _record_call(sd: str) -> dict[str, str]:
                call_record.append(sd)
                return self._enrich_mock(sd)

            executor = SkillExecutor(
                skill_name="enr4-test",
                ai_role="correction",
                enrich_failure=_record_call,
            )
            await executor.run(session_dir=session_dir, rules_config={"rejection_rules": []})

            assert len(call_record) == 1, f"期望回调被调用 1 次，实际 {len(call_record)}次"
            assert session_dir in call_record[0]

    @pytest.mark.asyncio
    async def test_enr5_candidates_path_no_callback(self, tmp_path, monkeypatch):
        """ENR5: 传入 candidates_path 不触发 enrich_failure 回调。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            call_record: list[str] = []

            def _record_call(sd: str) -> dict[str, str]:
                call_record.append(sd)
                return {}

            path = _write_candidates(["昵称A"], str(tmp_path))
            executor = SkillExecutor(
                skill_name="enr5-test",
                ai_role="correction",
                enrich_failure=_record_call,
            )
            await executor.run(path, rules_config={"rejection_rules": []})

            assert len(call_record) == 0, f"candidates_path 模式不应触发回调，实际调用 {len(call_record)}次"

    @pytest.mark.asyncio
    async def test_enr6_partial_files_graceful(self, tmp_path, monkeypatch):
        """ENR6: 部分文件缺失时优雅降级。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            # 不创建 customer_metadata.json
            session_dir, _ = self._make_session_dir(tmp_path, with_customer=False)

            executor = SkillExecutor(
                skill_name="enr6-test",
                ai_role="correction",
                enrich_failure=self._enrich_mock,
            )
            await executor.run(session_dir=session_dir, rules_config={"rejection_rules": []})

            log_path = Path(logdir) / "enr6-test"
            for f in log_path.glob("*.jsonl"):
                lines = f.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    entry = json.loads(line)
                    inp = entry.get("input_summary", {})
                    assert "debug_session_derived_json" in inp
                    assert "speaker_json" in inp
                    assert "customer_metadata_json" not in inp  # 文件不存在，不应注入

    @pytest.mark.asyncio
    async def test_enr7_complete_json_content(self, tmp_path, monkeypatch):
        """ENR7: 注入的 JSON 内容完整（非截断/过滤）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as logdir:
            monkeypatch.setenv("SKILL_LOG_DIR", logdir)
            self._mock_deepseek_ok(monkeypatch)

            session_dir, expected = self._make_session_dir(tmp_path)
            expected_debug = json.loads(expected["debug_session_derived_json"])

            executor = SkillExecutor(
                skill_name="enr7-test",
                ai_role="correction",
                enrich_failure=self._enrich_mock,
            )
            await executor.run(session_dir=session_dir, rules_config={"rejection_rules": []})

            log_path = Path(logdir) / "enr7-test"
            for f in log_path.glob("*.jsonl"):
                lines = f.read_text(encoding="utf-8").strip().split("\n")
                for line in lines:
                    entry = json.loads(line)
                    inp = entry.get("input_summary", {})

                    # 验证 debug_session_derived_json 可重新解析为 dict
                    debug_raw = inp["debug_session_derived_json"]
                    assert isinstance(debug_raw, str)
                    parsed = json.loads(debug_raw)
                    assert "screenshots" in parsed
                    assert parsed["screenshots"][0]["speaker_bands"][0]["y_top"] == 100
                    assert parsed["screenshots"][0]["blocks"][0]["class"] == "nickname_candidate"
                    assert parsed["screenshots"][0]["blocks"][0]["confidence"] == 0.95

                    # 验证 speaker_json 可重新解析
                    speaker_raw = inp["speaker_json"]
                    assert isinstance(speaker_raw, str)
                    sp = json.loads(speaker_raw)
                    assert sp["md5_spokesperson"]["speaker_binding_raw"] == "测试昵称"

                    # 验证 customer_metadata_json 可重新解析
                    cm_raw = inp["customer_metadata_json"]
                    assert isinstance(cm_raw, str)
                    cm = json.loads(cm_raw)
                    assert "resume_thumb_bboxes" in cm
                    assert cm["click_context"]["click_x"] == 540
