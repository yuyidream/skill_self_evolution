"""
Skill Engine — 自进化框架核心。

规则执行 → AI 常识判断 → 合理就过 / 不合理 AI 从原始数据重选 → 日志记录 → 离线进化 → 优化配置
"""

from skill_self_evolution.executor import SkillExecutor
from skill_self_evolution.models import SkillInput, SkillOutput
from skill_self_evolution.context import get_trace_id, set_trace_id
from skill_self_evolution.logger import SkillLogger
from skill_self_evolution.fallback import FallbackStrategy
from skill_self_evolution.config_loader import ConfigVersionManager
from skill_self_evolution.evolver import Evolver
from skill_self_evolution.ai_assisted_executor import AiAssistedExecutor

__all__ = [
    "SkillExecutor",
    "SkillInput",
    "SkillOutput",
    "get_trace_id",
    "set_trace_id",
    "SkillLogger",
    "FallbackStrategy",
    "ConfigVersionManager",
    "Evolver",
    "AiAssistedExecutor",
]
