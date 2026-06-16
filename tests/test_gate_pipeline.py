"""GatePipeline 集成测试 — 静态检查 + pytest 集成"""

import textwrap
from pathlib import Path

import pytest
from skill_self_evolution.gate_pipeline import GatePipeline


@pytest.fixture
def pipeline():
    return GatePipeline(max_complexity=10)


@pytest.mark.asyncio
async def test_layer1_passes_clean(tmp_path):
    f = tmp_path / "clean.py"
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")
    pipe = GatePipeline()
    result = await pipe._layer1_static_check([str(f)])
    assert result.passed is True


@pytest.mark.asyncio
async def test_layer1_catches_bare_except(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text(textwrap.dedent("""
        def foo():
            try:
                pass
            except:
                pass
    """), encoding="utf-8")
    pipe = GatePipeline()
    result = await pipe._layer1_static_check([str(f)])
    assert result.passed is False
    assert any(i.rule == "no_bare_except" for i in result.issues)


@pytest.mark.asyncio
async def test_layer1_catches_random_import(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("import random\n", encoding="utf-8")
    pipe = GatePipeline()
    result = await pipe._layer1_static_check([str(f)])
    assert result.passed is False


@pytest.mark.asyncio
async def test_layer1_catches_global(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text(textwrap.dedent("""
        def foo():
            global x
            x = 1
    """), encoding="utf-8")
    pipe = GatePipeline()
    result = await pipe._layer1_static_check([str(f)])
    assert result.passed is False


@pytest.mark.asyncio
async def test_layer1_catches_swallowing(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text(textwrap.dedent("""
        def foo():
            try:
                pass
            except Exception:
                pass
    """), encoding="utf-8")
    pipe = GatePipeline()
    result = await pipe._layer1_static_check([str(f)])
    assert result.passed is False


@pytest.mark.asyncio
async def test_layer2_runs_pytest(tmp_path):
    """Layer 2 跑真实 pytest"""
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_dummy.py"
    test_file.write_text(textwrap.dedent("""
        def test_pass():
            assert True
    """), encoding="utf-8")

    pipe = GatePipeline()
    result = await pipe._layer2_unit_test(str(test_file), str(tmp_path))
    assert result.passed is True, f"pytest output: {result.output}"


@pytest.mark.asyncio
async def test_layer2_catches_failure(tmp_path):
    """Layer 2 捕捉 pytest 失败"""
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    test_file = test_dir / "test_bad.py"
    test_file.write_text(textwrap.dedent("""
        def test_fail():
            assert 1 == 2
    """), encoding="utf-8")

    pipe = GatePipeline()
    result = await pipe._layer2_unit_test(str(test_file), str(tmp_path))
    assert result.passed is False


@pytest.mark.asyncio
async def test_layer3_same_as_layer2(tmp_path):
    """Layer 3 集成测试 — 和 Layer 2 同样的 pytest 机制"""
    test_dir = tmp_path / "integration"
    test_dir.mkdir()
    test_file = test_dir / "test_integration.py"
    test_file.write_text(textwrap.dedent("""
        def test_integration_ok():
            assert True
    """), encoding="utf-8")

    pipe = GatePipeline()
    result = await pipe._layer3_integration_test(str(test_file), str(tmp_path))
    assert result.passed is True


@pytest.mark.asyncio
async def test_layer4_candidate_replay_pass(tmp_path):
    """Layer 4 候选数据回放"""
    def replay(files):
        return True, "All 10 candidates passed"

    pipe = GatePipeline()
    result = await pipe._layer4_candidate_replay(replay, ["test.py"])
    assert result.passed is True
    assert "All 10" in result.output


@pytest.mark.asyncio
async def test_layer4_candidate_replay_fail(tmp_path):
    def replay(files):
        return False, "3/10 candidates failed"

    pipe = GatePipeline()
    result = await pipe._layer4_candidate_replay(replay, ["test.py"])
    assert result.passed is False


@pytest.mark.asyncio
async def test_build_feedback_with_context(tmp_path):
    """_build_feedback 注入函数上下文"""
    f = tmp_path / "bad.py"
    f.write_text(textwrap.dedent("""
        def my_func(items, threshold):
            good = []
            bad = 0
            for i in items:
                if i > threshold:
                    good.append(i)
                else:
                    bad += 1
            return good, bad
    """), encoding="utf-8")

    from skill_self_evolution.gate_pipeline import LayerResult
    pipe = GatePipeline()
    lr = LayerResult(layer=2, layer_name="unit_test", passed=False, output="AssertionError: ...")

    feedback = pipe._build_feedback([lr], [str(f)], "my_func")
    assert "my_func" in feedback
    assert "NO self" in feedback
    assert "items" in feedback
    assert "threshold" in feedback
    assert "FORBIDDEN" in feedback


@pytest.mark.asyncio
async def test_check_static_shortcut(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("import random\n", encoding="utf-8")
    passed, issues = GatePipeline.check_static([str(f)])
    assert passed is False
    assert len(issues) >= 1
