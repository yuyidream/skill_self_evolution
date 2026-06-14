"""
Skill 加载器测试：动态导入 run.py + evolve.toml 解析
"""

import tempfile
from pathlib import Path

import pytest

from skill_self_evolution.loader import SkillLoader, _parse_simple_toml


class TestTomlParser:
    """极简 TOML 解析器测试"""

    def test_basic_key_values(self):
        toml = """
key1 = "value1"
key2 = 42
key3 = true
key4 = 3.14
"""
        result = _parse_simple_toml(toml)
        assert result["key1"] == "value1"
        assert result["key2"] == 42
        assert result["key3"] is True
        assert result["key4"] == 3.14

    def test_section(self):
        toml = """
[skill]
ai_role = "correction"

[evolve.auto_modify]
rules_config = true
"""
        result = _parse_simple_toml(toml)
        assert result["skill"]["ai_role"] == "correction"
        assert result["evolve"]["auto_modify"]["rules_config"] is True

    def test_comments_ignored(self):
        toml = """
# 这是注释
key = "value"
"""
        result = _parse_simple_toml(toml)
        assert result["key"] == "value"


class TestSkillLoader:
    """SkillLoader 测试"""

    def test_load_missing_skill(self):
        loader = SkillLoader(Path(tempfile.gettempdir()))
        with pytest.raises(FileNotFoundError):
            loader.load("non-existent-skill")

    def test_load_skill_without_run_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "my-skill"
            skill_dir.mkdir()
            loader = SkillLoader(Path(tmp))
            with pytest.raises(FileNotFoundError):
                loader.load("my-skill")

    def test_load_minimal_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)

            # 创建 skill 目录结构
            skill_dir = base / "test-skill"
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(parents=True)

            # 创建 run.py
            (scripts_dir / "run.py").write_text("""
def execute(input_data, config):
    from skill_self_evolution.models import SkillOutput
    return SkillOutput(source="rule", result={"ok": True})

def benchmark(executor):
    return 0, 0, []

def summarize_input(input_data):
    return {"summary": "test"}
""", encoding="utf-8")

            # 创建 evolve.toml
            (skill_dir / "evolve.toml").write_text("""
[skill]
ai_role = "correction"
""", encoding="utf-8")

            loader = SkillLoader(base)
            skill = loader.load("test-skill")

            assert skill.skill_name == "test-skill"
            assert skill.ai_role == "correction"
            assert skill.execute is not None
            assert skill.benchmark is not None
            assert skill.summarize_input is not None

    def test_cache_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skill_dir = base / "cache-skill"
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(parents=True)

            (scripts_dir / "run.py").write_text("""
def execute(input_data, config):
    from skill_self_evolution.models import SkillOutput
    return SkillOutput(source="rule", result={})

def benchmark(executor):
    return 0, 0, []
""", encoding="utf-8")

            (skill_dir / "evolve.toml").write_text('[skill]\nai_role = "correction"\n', encoding="utf-8")

            loader = SkillLoader(base)
            skill1 = loader.load("cache-skill")
            skill2 = loader.load("cache-skill")
            assert skill1 is skill2  # 缓存命中

            loader.invalidate_cache("cache-skill")
            skill3 = loader.load("cache-skill")
            assert skill3 is not skill1  # 缓存失效后重新加载
