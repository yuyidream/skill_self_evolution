"""
Skill 动态加载器 — 加载 run.py / summarize_input / evolve.toml / evolve_prompt.yaml / skill.md。
"""

import importlib.util
from loguru import logger
import os
from pathlib import Path
from typing import Any, Callable

from ruamel.yaml import YAML

yaml_safe = YAML(typ='safe')
yaml_rt = YAML()  # round-trip mode — 保留注释和格式，用于 dump

# Skill 根目录：优先 SKILL_BASE_DIR 环境变量；兼容 housekeeping 的路径
_skill_base_env = os.getenv("SKILL_BASE_DIR", "")
if _skill_base_env:
    DEFAULT_SKILL_BASE = Path(_skill_base_env)
else:
    # 尝试相对于 housekeeping 项目根目录（兼容老部署）
    _hk_root = Path(__file__).resolve().parents[3].parent / "housekeeping_ai_match"
    _hk_skill = _hk_root / "backend" / "config" / "services" / "skill"
    if _hk_skill.is_dir():
        DEFAULT_SKILL_BASE = _hk_skill
    else:
        DEFAULT_SKILL_BASE = Path.cwd() / "backend" / "config" / "services" / "skill"


class SkillModule:
    """已加载的 Skill 模块，包含 execute / benchmark / summarize_input 函数和元数据。"""

    def __init__(
        self,
        skill_name: str,
        execute: Callable,
        benchmark: Callable | None = None,
        summarize_input: Callable | None = None,
        evolve_toml: dict[str, Any] | None = None,
        evolve_prompt_yaml: dict[str, Any] | None = None,
        skill_md: str | None = None,
    ):
        self.skill_name = skill_name
        self.execute = execute
        self.benchmark = benchmark or (lambda executor: (0, 0, []))
        self.summarize_input = summarize_input
        self.evolve_toml = evolve_toml or {}
        self.evolve_prompt_yaml = evolve_prompt_yaml
        self.skill_md = skill_md

    @property
    def ai_role(self) -> str:
        """从 evolve.toml 读取 ai_role，默认 "correction"。"""
        return self.evolve_toml.get("skill", {}).get("ai_role", "correction")


class SkillLoader:
    """Skill 加载器，负责从磁盘动态导入 run.py 并解析配置文件。"""

    def __init__(self, skill_base_dir: Path | None = None):
        self._base_dir = skill_base_dir or DEFAULT_SKILL_BASE
        self._cache: dict[str, SkillModule] = {}

    def load(self, skill_name: str) -> SkillModule:
        """加载指定 Skill（含缓存）"""
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_dir = self._base_dir / skill_name
        if not skill_dir.is_dir():
            raise FileNotFoundError(f"Skill 目录不存在: {skill_dir}")

        # 1. 加载 run.py（强制导出 execute）
        run_path = skill_dir / "scripts" / "run.py"
        if not run_path.is_file():
            raise FileNotFoundError(f"run.py 不存在: {run_path}")

        spec = importlib.util.spec_from_file_location(
            f"skill_{skill_name.replace('-', '_')}", str(run_path)
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 run.py: {run_path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "execute"):
            raise AttributeError(f"{run_path} 缺少强制函数 execute()")

        execute_fn = getattr(module, "execute")
        benchmark_fn = getattr(module, "benchmark", None)
        summarize_input_fn = getattr(module, "summarize_input", None)

        # 2. 加载 evolve.toml
        evolve_toml = self._load_evolve_toml(skill_dir)

        # 3. 加载 evolve_prompt.yaml（Skill 自定义优先）
        evolve_prompt_yaml = self._load_evolve_prompt_yaml(skill_dir)

        # 4. 加载 skill.md
        skill_md = self._load_skill_md(skill_dir)

        skill_module = SkillModule(
            skill_name=skill_name,
            execute=execute_fn,
            benchmark=benchmark_fn,
            summarize_input=summarize_input_fn,
            evolve_toml=evolve_toml,
            evolve_prompt_yaml=evolve_prompt_yaml,
            skill_md=skill_md,
        )
        self._cache[skill_name] = skill_module
        logger.info("Skill 加载完成: %s (ai_role=%s)", skill_name, skill_module.ai_role)
        return skill_module

    def invalidate_cache(self, skill_name: str | None = None) -> None:
        """清除缓存（配置热加载后调用）。"""
        if skill_name:
            self._cache.pop(skill_name, None)
        else:
            self._cache.clear()

    @staticmethod
    def _load_evolve_toml(skill_dir: Path) -> dict[str, Any]:
        toml_path = skill_dir / "evolve.toml"
        if not toml_path.is_file():
            logger.debug("evolve.toml 未找到，使用默认值: %s", toml_path)
            return {"skill": {"ai_role": "correction"}}

        # 简单 TOML 解析（仅支持顶层表 [section] 和 key=value，不依赖 toml 库）
        return _parse_simple_toml(toml_path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_evolve_prompt_yaml(skill_dir: Path) -> dict[str, Any]:
        yaml_path = skill_dir / "evolve_prompt.yaml"
        if not yaml_path.is_file():
            return {}
        return yaml_safe.load(yaml_path.read_text(encoding="utf-8"))

    @staticmethod
    def _load_skill_md(skill_dir: Path) -> str | None:
        md_path = skill_dir / "skill.md"
        if not md_path.is_file():
            return None
        return md_path.read_text(encoding="utf-8")


def _parse_simple_toml(content: str) -> dict[str, Any]:
    """极简 TOML 解析器，支持一层嵌套的 [parent.child] 节。"""
    result: dict[str, Any] = {}
    current_path: list[str] = []  # 当前 section 路径栈

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # [section] 或 [section.sub]
        if line.startswith("[") and "]" in line:
            section_name = line[1:].split("]")[0].strip()
            parts = section_name.split(".")
            current_path = parts

            # 确保路径存在（若中间节点已被占用为非 dict，则替换为 dict）
            cursor = result
            for part in parts:
                if part not in cursor or not isinstance(cursor.get(part), dict):
                    cursor[part] = {}
                cursor = cursor[part]
            continue

        # key = value
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            # 类型推断
            if value.lower() in ("true", "false"):
                parsed: Any = value.lower() == "true"
            elif value.isdigit():
                parsed = int(value)
            elif _is_float(value):
                parsed = float(value)
            else:
                parsed = value

            # 写入当前 section
            cursor = result
            for part in current_path:
                cursor = cursor[part]
            cursor[key] = parsed

    return result


def _is_float(s: str) -> bool:
    try:
        float(s)
        return "." in s
    except ValueError:
        return False
