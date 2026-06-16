"""Evolution loop configuration — adapted from EvoSkill LoopConfig.

原始：https://github.com/sentient-agi/EvoSkill
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


EvolutionMode = Literal["prompt_only", "config_only"]
SelectionStrategy = Literal["best", "random", "round_robin"]


@dataclass
class LoopConfig:
    """进化循环配置参数。

    Attributes:
        max_iterations: 最大迭代轮数
        frontier_size: Top-N 精英池大小
        no_improvement_limit: 连续无改善则提前停止
        concurrency: 并行评测数
        evolution_mode: 进化维度（prompt_only | config_only）
        selection_strategy: 从 frontier 选 parent 的策略
        failure_sample_count: 每次 proposer 分析的失败样本数
        samples_per_category: 每类别采样数
        reset_feedback: 新循环是否清空反馈历史
        continue_mode: 是否从上次 checkpoint 续跑
        cache_enabled: 是否启用缓存
        cache_dir: 缓存目录
        proposer_max_truncation_level: 上下文截断级别（0=完整 1=中等 2=激进）
        proposer_single_failure_fallback: 全部截断失败后降级到单样本
        consecutive_proposer_failures_limit: 连续 proposer 失败上限
    """

    max_iterations: int = 20
    frontier_size: int = 3
    no_improvement_limit: int = 5
    concurrency: int = 4

    evolution_mode: EvolutionMode = "config_only"
    selection_strategy: SelectionStrategy = "best"

    failure_sample_count: int = 3
    samples_per_category: int = 2
    categories_per_batch: int = 3

    reset_feedback: bool = True
    continue_mode: bool = False

    cache_enabled: bool = True
    cache_dir: Path = field(default_factory=lambda: Path(".cache/runs"))

    proposer_max_truncation_level: int = 2
    proposer_single_failure_fallback: bool = True
    consecutive_proposer_failures_limit: int = 5
