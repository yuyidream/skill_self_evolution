"""
Skill Engine — 自进化框架核心。

调用方注入业务函数，框架编排管线：
  SkillExecutor → run(candidates_path, rules_config, prompt_config)
  Evolver(execute_fn=, benchmark_fn=) → evolve()
"""

from skill_self_evolution.executor import SkillExecutor
from skill_self_evolution.models import (
    BlockCandidate,
    CandidateInput,
    EvolvePromptYamlModel,
    EvolveTomlModel,
    GeometryRuleParams,
    OcrBlock,
    PromptConfigModel,
    RejectionRuleItem,
    RuleResultDict,
    RulesConfigModel,
    SessionInput,
    SkillInput,
    SkillOutput,
)
from skill_self_evolution.context import get_trace_id, set_trace_id
from skill_self_evolution.logger import SkillLogger
from skill_self_evolution.fallback import FallbackStrategy
from skill_self_evolution.config_loader import ConfigVersionManager
from skill_self_evolution.evolver import Evolver
from skill_self_evolution.ai_assisted_executor import AiAssistedExecutor
from skill_self_evolution.deepseek import CircuitBreaker, DeepSeekClient, StreamChunk, normalize_deepseek_api_base
from skill_self_evolution.code_guard import CodeGuard, CodeIssue, FunctionContext, extract_context
from skill_self_evolution.gate_pipeline import GatePipeline, LayerResult, GateResult

__all__ = [
    "SkillExecutor",
    "SkillInput",
    "SkillOutput",
    "BlockCandidate",
    "CandidateInput",
    "GeometryRuleParams",
    "OcrBlock",
    "RulesConfigModel",
    "PromptConfigModel",
    "RejectionRuleItem",
    "RuleResultDict",
    "SessionInput",
    "EvolveTomlModel",
    "EvolvePromptYamlModel",
    "get_trace_id",
    "set_trace_id",
    "SkillLogger",
    "FallbackStrategy",
    "ConfigVersionManager",
    "Evolver",
    "AiAssistedExecutor",
    "CircuitBreaker",
    "DeepSeekClient",
    "StreamChunk",
    "normalize_deepseek_api_base",
    "CodeGuard",
    "CodeIssue",
    "FunctionContext",
    "extract_context",
    "GatePipeline",
    "LayerResult",
    "GateResult",
]
