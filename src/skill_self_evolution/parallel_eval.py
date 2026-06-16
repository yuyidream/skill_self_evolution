"""并行评测器 — 从 EvoSkill evaluate_agent_parallel 简化。

原始：https://github.com/sentient-agi/EvoSkill

去掉了 Agent / AgentTrace / tqdm 依赖，提供通用并行执行模式。
"""

import asyncio
import time
from typing import Any, Awaitable, Callable, TypeVar

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


async def run_parallel(
    tasks: list[tuple[Callable[..., Awaitable[T]], tuple[Any, ...]]],
    max_concurrent: int = 4,
    timeout_per_task: float = 600,
) -> list[tuple[T | None, Exception | None]]:
    """并行执行多个异步任务，带并发控制和超时。

    Args:
        tasks: (async_fn, args) 元组列表
        max_concurrent: 最大并发数
        timeout_per_task: 每任务超时（秒）

    Returns:
        (result, error) 元组列表，顺序与输入一致
    """
    t0 = time.monotonic()
    logger.info("parallel.start", task_count=len(tasks),
                 max_concurrent=max_concurrent)

    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[tuple[T | None, Exception | None]] = [None] * len(tasks)  # type: ignore

    async def run_one(idx: int, fn: Callable[..., Awaitable[T]], args: tuple[Any, ...]) -> None:
        async with semaphore:
            t_start = time.monotonic()
            try:
                async with asyncio.timeout(timeout_per_task):
                    results[idx] = (await fn(*args), None)
                elapsed = time.monotonic() - t_start
                logger.debug("parallel.task_ok", task_id=idx, elapsed_ms=round(elapsed * 1000))
            except asyncio.TimeoutError:
                elapsed = time.monotonic() - t_start
                logger.warning("parallel.task_timeout", task_id=idx,
                               elapsed_ms=round(elapsed * 1000))
                results[idx] = (None, TimeoutError(f"Task {idx} timed out"))
            except Exception as e:
                elapsed = time.monotonic() - t_start
                logger.warning("parallel.task_error", task_id=idx,
                               error=type(e).__name__, message=str(e)[:200],
                               elapsed_ms=round(elapsed * 1000))
                results[idx] = (None, e)

    await asyncio.gather(*[
        run_one(i, fn, args) for i, (fn, args) in enumerate(tasks)
    ])

    total_elapsed = time.monotonic() - t0
    ok_count = sum(1 for r, e in results if e is None)
    logger.info("parallel.done", total=len(tasks), ok=ok_count,
                 failed=len(tasks) - ok_count,
                 elapsed_ms=round(total_elapsed * 1000))
    return results
