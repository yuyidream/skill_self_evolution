"""EvoSkill Feedback Descent 演示 — 3 轮+ 代码修复闭环

演示 EvoSkill 模块的实际用法：
- feedback_descent.FeedbackDescent：反馈驱动优化算法
- feedback_history：结构化反馈持久化
- parallel_eval：并行测试执行
- structlog：结构化日志

目标：修复 nickname_ocr_simple.py 注入的 hallucination（self.config.get 在模块级函数）
"""
import asyncio
import concurrent.futures
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, r"E:\projects\skill_self_evolution\src")
os.environ["DB_PASSWORD"] = "local_root_123"

from skill_self_evolution.logging import get_logger
from skill_self_evolution.feedback_descent import (
    FeedbackDescent, Proposer, Evaluator, EvaluationResult, FeedbackEntry,
)
from skill_self_evolution.feedback_history import append_feedback, read_feedback_history
from skill_self_evolution.parallel_eval import run_parallel
from skill_self_evolution.harness.opencode.executor import execute_query

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# 路径 & 辅助
# ═══════════════════════════════════════════════════════════════

TARGET = Path("E:/projects/housekeeping_ai_match/scripts/wx_match/processor/nickname_ocr_simple.py")
BACKEND = Path("E:/projects/housekeeping_ai_match/backend")
FEEDBACK_PATH = Path("E:/projects/skill_self_evolution/data/demo_feedback_history.md")
FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
FEEDBACK_PATH.write_text("# Demo Feedback History\n", encoding="utf-8")

orig_content = TARGET.read_text("utf-8")
orig_path = Path(str(TARGET) + ".orig.bak")
orig_path.write_text(orig_content, "utf-8")


def restore():
    TARGET.write_text(orig_path.read_text("utf-8"), "utf-8")


def inject_hallucination():
    c = TARGET.read_text("utf-8")
    old = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    new_lines = [
        old,
        "            click_w = click_area[2] - click_area[0]",
        "            click_h = click_area[3] - click_area[1]",
        "            click_area_size = click_w * click_h",
        "            min_overlap_area_ratio = self.config.get('card_binding', {}).get('min_overlap_area_ratio', 0.3)",
        "            ambiguity_tie_ratio = self.config.get('card_binding', {}).get('ambiguity_tie_ratio', 0.05)",
    ]
    new = "\n".join(new_lines)
    if old not in c:
        return False
    TARGET.write_text(c.replace(old, new, 1), "utf-8")
    return True


def replace_code(code: str) -> bool:
    c = TARGET.read_text("utf-8")
    lines = c.split("\n")
    marker = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    end_marker = "for ci, raw in enumerate(raws):"
    start_line = end_line = None
    for i, l in enumerate(lines):
        if marker in l:
            start_line = i
        if start_line is not None and end_marker in l:
            end_line = i
            if end_line > 0 and lines[end_line - 1].strip() == "":
                end_line = end_line - 1
            break
    if start_line is None or end_line is None:
        return False
    dedented = textwrap.dedent(code)
    raw_lines = dedented.strip().split("\n")
    ind = "            "
    fixed = [ind + nl if nl.strip() else "" for nl in raw_lines]
    c = "\n".join(lines[:start_line] + fixed + lines[end_line:])
    TARGET.write_text(c, "utf-8")
    return True


def extract_code(text: str) -> str | None:
    lines = text.split("\n")
    start = -1
    for i, l in enumerate(lines):
        if l.strip().startswith("```python"):
            start = i + 1
        elif l.strip() == "```" and start >= 0:
            return "\n".join(lines[start:i])
    return None


# ═══════════════════════════════════════════════════════════════
# 测试函数（供 parallel_eval 并行调用）
# ═══════════════════════════════════════════════════════════════

async def run_e2e_test() -> dict:
    """E2E 测试"""
    t0 = time.monotonic()
    r = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/test_wx_match/test_processor_pipeline_e2e.py",
        "-q", "--tb=short", "--no-header", "-W", "ignore"
    ], cwd=str(BACKEND), capture_output=True, text=True, timeout=120)
    passed = not any(l.strip().endswith(" failed") for l in r.stdout.split("\n"))
    elapsed = time.monotonic() - t0
    return {"test": "e2e", "passed": passed, "elapsed_ms": round(elapsed * 1000),
            "output": r.stdout[-500:]}


async def run_candidate_replay_test() -> dict:
    """候选回放测试"""
    t0 = time.monotonic()
    script = r"""
import sys, os
sys.path.insert(0, r"E:\projects\housekeeping_ai_match")
sys.path.insert(0, r"E:\projects\housekeeping_ai_match\backend")
sys.path.insert(0, r"E:\projects\housekeeping_ai_match\scripts\wx_match")
os.environ["DB_PASSWORD"] = "local_root_123"
from unittest.mock import MagicMock
from scripts.wx_match.processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig
s = MagicMock()
s.resume_thumb_bboxes = [[100, 200, 400, 500], [350, 200, 600, 500]]
s.original_resolution = MagicMock(width=720, height=1600)
ctx = MagicMock(); ctx.click_coords = [375, 350]
s.click_context = ctx
cfg = NicknameOcrConfig()
try:
    result = _resume_thumb_bindings_and_orphans(
        screenshot=s, blocks=[], classes=[], claimed_indices=set(), nicknames=(),
        config=cfg, original_width=720, image_size=(720, 1600)
    )
    bindings, orphan, excluded = result
    print(f"OK|bindings={len(bindings) if bindings else 0}|orphan={orphan}")
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    print(f"ERROR|{type(e).__name__}: {e}")
    print(tb[-300:])
"""
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND), capture_output=True, text=True, encoding='utf-8', timeout=30
    )
    passed = r.stdout.strip().startswith("OK|")
    elapsed = time.monotonic() - t0
    return {"test": "replay", "passed": passed, "elapsed_ms": round(elapsed * 1000),
            "output": r.stdout.strip()[-300:]}


# ═══════════════════════════════════════════════════════════════
# 候选代码（模拟生成过程 — 真正用 AI）
# ═══════════════════════════════════════════════════════════════

@dataclass
class CandidateCode:
    code: str
    iteration: int = 0

SYSTEM_PROMPT = """You are a Python code fixer. Output ONLY ```python``` code to INSERT.
Target: module-level function, NO self. NO function def.
Hardcoded: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05.
Local vars: cx, cy, raws, click_source_card_idx."""


async def generate_candidate(prompt: str) -> str:
    """通过 harness 调用 DeepSeek 生成代码候选"""
    options = {
        "provider_id": "deepseek",
        "model_id": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        "mode": "build",
        "cwd": str(BACKEND),
        "system": SYSTEM_PROMPT,
    }
    result = await execute_query(options, prompt)
    msgs = result[0].get("messages", [])
    for m in msgs:
        info = m.get("info", {})
        if info.get("role") == "assistant":
            return "".join(
                p.get("text", "") for p in m.get("parts", [])
                if p.get("type") == "text"
            )
    return ""


async def run_combined_tests() -> list[dict]:
    """并行跑 E2E + 候选回放"""
    results = await run_parallel([
        (run_e2e_test, ()),
        (run_candidate_replay_test, ()),
    ], max_concurrent=2, timeout_per_task=120)
    return [r for r, _ in results if r is not None]


# ═══════════════════════════════════════════════════════════════
# FeedbackDescent Proposer & Evaluator 实现
# ═══════════════════════════════════════════════════════════════

def _run_async(coro):
    """在独立线程中运行异步协程（解决 FeedbackDescent sync→async 问题）"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result(timeout=180)

class CodeProposer:
    """DeepSeek 驱动的代码 Proposer"""

    def generate_initial(self, problem: str) -> CandidateCode:
        """Generate initial fix (round 1)"""
        logger.info("proposer.generate_initial")
        prompt = f"""Fix the BUG. Insert overlap-area logic:

Original (broken):
    click_area = (cx, cy, cx + 2.0, cy + 2.0)
    matching_cards: list[int] = []
    for i, raw in enumerate(raws):
        if not raw or len(raw) < 4: continue
        rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
        if rx1 <= cx <= rx2 and ry1 <= cy <= ry2: matching_cards.append(i)
    if len(matching_cards) == 1: click_source_card_idx = matching_cards[0]

Target: overlap_area = (ox2-ox1)*(oy2-oy1), ratio >= 0.3, tie-break at 0.05.
Use: cx, cy, raws, click_source_card_idx. Hardcode params.
Output ```python``` ONLY."""
        code = _run_async(generate_candidate(prompt))
        code = extract_code(code) or code
        logger.info("proposer.initial_done", code_len=len(code) if code else 0)
        return CandidateCode(code=code or "", iteration=0)

    def propose(
        self, current_best: CandidateCode, feedback_history: list[FeedbackEntry[CandidateCode]]
    ) -> CandidateCode:
        """Propose improved code based on feedback history"""
        iter_num = current_best.iteration + 1
        logger.info("proposer.propose", iteration=iter_num,
                     history_size=len(feedback_history))

        if feedback_history:
            fb_parts = []
            for i, entry in enumerate(feedback_history, 1):
                code_preview = entry.candidate.code[:200] if entry.candidate.code else "(empty)"
                fb_parts.append(
                    f"## Failed Attempt {i}\nCode:\n```python\n{code_preview}\n```\n"
                    f"Why it failed: {entry.rationale}"
                )
            history_block = "\n\n".join(fb_parts)
            prompt = f"""Fix the code. Previous attempts FAILED. DO NOT repeat these mistakes:

{history_block}

Current best:\n```python\n{current_best.code[:300]}\n```

Output CORRECT ```python``` only."""
        else:
            prompt = f"""Improve this code:\n```python\n{current_best.code[:300]}\n```\nOutput ```python```."""

        code = _run_async(generate_candidate(prompt))
        code = extract_code(code) or code
        logger.info("proposer.propose_done", iteration=iter_num,
                     code_len=len(code) if code else 0)
        return CandidateCode(code=code or "", iteration=iter_num)


class CodeEvaluator:
    """执行 E2E + 候选回放的 Evaluator"""

    def evaluate(
        self, current_best: CandidateCode, candidate: CandidateCode
    ) -> EvaluationResult:
        logger.info("evaluator.start", iteration=candidate.iteration)

        # Apply candidate to target file
        restore()
        inject_hallucination()
        replace_code(candidate.code)

        # Run parallel tests
        test_results = _run_async(run_combined_tests())
        all_passed = all(r["passed"] for r in test_results)

        # Build rationale
        result_parts = []
        score = 0.0
        for r in test_results:
            if r["passed"]:
                score += 1.0
                result_parts.append(f"{r['test']}: PASSED")
            else:
                result_parts.append(f"{r['test']}: FAILED ({r['output'][:150]})")
        rationale = "; ".join(result_parts)
        score = score / len(test_results) if test_results else 0.0

        # Compute parent score for comparison
        restore()
        inject_hallucination()
        replace_code(current_best.code)
        parent_results = _run_async(run_combined_tests())
        parent_score = sum(1.0 for r in parent_results if r["passed"]) / len(parent_results) if parent_results else 0.0

        logger.info("evaluator.done", iteration=candidate.iteration,
                     score=score, parent_score=parent_score,
                     preferred=score >= parent_score, rationale=rationale[:150])

        return EvaluationResult(
            preference_for_candidate=(score > parent_score),
            rationale=rationale,
            score_best=parent_score,
            score_candidate=score,
        )


# ═══════════════════════════════════════════════════════════════
# main()
# ═══════════════════════════════════════════════════════════════

async def main():
    logger.info("demo.start")

    restore()

    # 注入 hallucination 确认初始状态
    inject_hallucination()
    logger.info("demo.hallucination_injected")

    initial_tests = await run_combined_tests()
    for r in initial_tests:
        logger.info("demo.initial_test", test=r["test"], passed=r["passed"])

    restore()

    # 创建 FeedbackDescent 实例
    fd = FeedbackDescent(
        proposer=CodeProposer(),
        evaluator=CodeEvaluator(),
        max_iterations=5,
        no_improvement_limit=3,
    )

    logger.info("demo.feedback_descent.start")
    result = fd.run(problem="fix nickname_ocr_simple.py: remove self.config.get and implement overlap area")
    logger.info("demo.feedback_descent.done", iterations=result.iterations,
                 improved=result.improved, best_len=len(result.best.code))

    # 持久化反馈历史
    for i, entry in enumerate(result.feedback_history, 1):
        append_feedback(
            FEEDBACK_PATH,
            iteration=f"iter-{i}",
            proposal=entry.candidate.code[:200],
            justification=entry.rationale,
            outcome="discarded",
        )

    # 最终验证
    restore()
    inject_hallucination()
    replace_code(result.best.code)
    final_tests = await run_combined_tests()
    all_pass = all(r["passed"] for r in final_tests)

    logger.info("demo.final", all_pass=all_pass, iterations=result.iterations,
                 improved=result.improved)
    for r in final_tests:
        logger.info("demo.final_test", test=r["test"], passed=r["passed"])

    # 恢复原文件
    restore()

    # 打印反馈历史
    logger.info("demo.feedback_history", path=str(FEEDBACK_PATH))
    fb_content = read_feedback_history(FEEDBACK_PATH)
    print(f"\n=== 反馈历史 ({FEEDBACK_PATH}) ===")
    print(fb_content[:3000])

    logger.info("demo.done", success=all_pass)
    return all_pass


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
