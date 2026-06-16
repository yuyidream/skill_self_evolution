"""
closed_loop_opencode.py — 用 OpenCode CLI 替代自定义 DeepSeek 客户端，
复现 closed_loop_v2.py 的实验：注入幻觉 → OpenCode 修复 → E2E + 候选回放验证

关键区别：
  - closed_loop_v2.py: DeepSeek API → extract_code() → replace_code() → 手动拼 prompt
  - 本脚本: opencode run（一个命令完成「理解需求 → 读文件 → 编辑 → 跑测试」）
"""

import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
# 路径
# ═══════════════════════════════════════════════════════════════

PROJECT = Path("E:/projects/housekeeping_ai_match")
BACKEND = PROJECT / "backend"
TARGET = PROJECT / "scripts/wx_match/processor/nickname_ocr_simple.py"
assert TARGET.exists(), f"Target not found: {TARGET}"

# 备份用
BACKUP = TARGET.with_suffix(".py.opencode_backup")

# ═══════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════


def backup():
    """备份原始文件"""
    TARGET.copy(BACKUP)
    print(f"[backup] {BACKUP.name}")


def restore():
    """恢复原始文件"""
    if BACKUP.exists():
        BACKUP.replace(TARGET)
        print(f"[restore] restored from backup")


def apply_hallucination() -> bool:
    """注入幻觉代码：在模块级函数中使用 self.config.get()"""
    c = TARGET.read_text("utf-8")
    old = (
        "            # 构造 2×2 虚拟区域\n"
        "            click_area = (cx, cy, cx + 2.0, cy + 2.0)\n"
        "            # 找唯一包含该区域的卡片\n"
        "            matching_cards: list[int] = []\n"
        "            for i, raw in enumerate(raws):\n"
        "                if not raw or len(raw) < 4:\n"
        "                    continue\n"
        "                rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]\n"
        "                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:\n"
        "                    matching_cards.append(i)\n"
        "            if len(matching_cards) == 1:\n"
        "                click_source_card_idx = matching_cards[0]"
    )
    new = (
        "            # 构造 2×2 虚拟区域\n"
        "            click_area = (cx, cy, cx + 2.0, cy + 2.0)\n"
        "            # 找包含该区域的卡片（使用 self.config 计算重叠面积，含 tie ratio）\n"
        "            matching_cards: list[int] = []\n"
        "            card_binding = self.config.get('card_binding', {})\n"
        "            min_overlap = card_binding.get('min_overlap_area_ratio', 0.3)\n"
        "            ambiguity_tie = card_binding.get('ambiguity_tie_ratio', 0.05)\n"
        "            for i, raw in enumerate(raws):\n"
        "                if not raw or len(raw) < 4:\n"
        "                    continue\n"
        "                rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]\n"
        "                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:\n"
        "                    matching_cards.append(i)\n"
        "            if len(matching_cards) == 1:\n"
        "                click_source_card_idx = matching_cards[0]"
    )
    if old not in c:
        print("[hallucination] old code not found, already modified?")
        return False
    c = c.replace(old, new, 1)
    TARGET.write_text(c, "utf-8")
    print("[hallucination] injected self.config.get() bug")
    return True


def run_e2e() -> tuple[bool, str]:
    """执行 E2E 测试"""
    r = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/test_wx_match/test_processor_pipeline_e2e.py",
            "-q", "--tb=short", "--no-header", "-W", "ignore",
        ],
        cwd=str(BACKEND), capture_output=True, text=True, timeout=120,
    )
    ok = " failed" not in r.stdout
    return ok, r.stdout[-3000:]


def run_candidate_replay() -> tuple[bool, str]:
    """执行候选回放测试"""
    script = r"""
import sys, os
sys.path.insert(0, r"E:\projects\housekeeping_ai_match")
sys.path.insert(0, r"E:\projects\housekeeping_ai_match\backend")
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
        screenshot=s, blocks=[], classes=[],
        claimed_indices=set(), nicknames=(),
        config=cfg, original_width=720, image_size=(720, 1600)
    )
    bindings, orphan, excluded = result
    print(f"OK|bindings={len(bindings) if bindings else 0}|orphan={orphan}")
except Exception as e:
    import traceback
    print(f"ERROR|{type(e).__name__}: {e}")
    traceback.print_exc()
"""
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    out = (r.stdout + r.stderr).strip()
    ok = out.startswith("OK|")
    return ok, out[-800:]


def call_opencode(prompt: str, round_num: int) -> tuple[int, str, str]:
    """调用 opencode run，返回 (exit_code, stdout, stderr)"""
    cmd = [
        "opencode", "run",
        "--dir", str(BACKEND),
        "--model", "deepseek/deepseek-v4-pro",
        "--dangerously-skip-permissions",
        "--format", "default",
        prompt,
    ]
    print(f"\n  [opencode round {round_num}] invoking: opencode run --dir {BACKEND} ...")
    print(f"  [opencode round {round_num}] prompt length: {len(prompt)} chars")
    sys.stdout.flush()

    r = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "NO_COLOR": "1"},
    )
    return r.returncode, r.stdout[-3000:] if r.stdout else "", r.stderr[-1000:] if r.stderr else ""


# ═══════════════════════════════════════════════════════════════
# 提示词模板
# ═══════════════════════════════════════════════════════════════

SYSTEM_INSTRUCTION = """You are fixing a Python bug. Your tasks:

1. Read the file: scripts/wx_match/processor/nickname_ocr_simple.py
2. Find function `_resume_thumb_bindings_and_orphans` (line ~846)
3. Find the injected BUGGY code that uses `self.config.get(...)` — this is a MODULE-LEVEL function with NO `self` parameter
4. Replace the buggy block with correct code that:
   - Hardcodes `min_overlap_area_ratio=0.3` and `ambiguity_tie_ratio=0.05` (no config lookups)
   - Keeps the click_area 2x2 logic and matching_cards loop using only cx, cy, raws, click_source_card_idx
   - Does NOT use `self.` anywhere
5. Run the E2E tests: python -m pytest tests/test_wx_match/test_processor_pipeline_e2e.py -q --tb=short
6. If tests fail, analyze the error and fix your code. Retry up to 3 times.
7. When tests pass, confirm success."""


def make_fix_prompt(round_num: int, feedback: str = "") -> str:
    if round_num == 1:
        return SYSTEM_INSTRUCTION
    else:
        return f"""{SYSTEM_INSTRUCTION}

PREVIOUS ATTEMPT FAILED. Here is the feedback:

{feedback}

Fix the issues described above and run the tests again. Do NOT use self.
This is a module-level function. Hardcode min_overlap_area_ratio=0.3 and ambiguity_tie_ratio=0.05."""


# ═══════════════════════════════════════════════════════════════
# 主循环
# ═══════════════════════════════════════════════════════════════


async def closed_loop_with_opencode():
    """用 OpenCode 替代 DeepSeek 客户端的闭环修复循环"""
    print("=" * 60)
    print("CLOSED LOOP — OpenCode Edition")
    print("=" * 60)

    backup()

    # Step 0: 注入幻觉
    if not apply_hallucination():
        restore()
        return False

    # Step 0b: 验证幻觉确实破坏了测试
    print("\n--- Verifying hallucination breaks tests ---")
    ok0, out0 = run_e2e()
    print(f"  E2E with bug: {'PASSED' if ok0 else 'FAILED (expected)'}")
    sys.stdout.flush()

    feedback = ""
    for rnd in range(1, 4):
        print(f"\n{'=' * 40}")
        print(f"ROUND {rnd}/3")
        print(f"{'=' * 40}")

        # 恢复到原始文件 + 重新注入幻觉（因为 opencode 可能已经修改了）
        # 实际上第1轮后文件已被 opencode 修改，不需要重新注入
        # 后续轮次 opencode 在当前文件状态上继续修改

        prompt = make_fix_prompt(rnd, feedback)
        exit_code, stdout, stderr = call_opencode(prompt, rnd)

        print(f"  opencode exit: {exit_code}")
        if stdout:
            # 只打印最后几行，避免刷屏
            tail = "\n".join(stdout.strip().split("\n")[-15:])
            print(f"  stdout (tail):\n{tail}")
        if stderr and "warning" not in stderr.lower()[:50]:
            print(f"  stderr (tail):\n{stderr[-500:]}")

        # 外部 E2E 验证（双重保险：opencode 内部跑过，我们外部再跑一次）
        print("\n  --- External E2E verification ---")
        e2e_ok, e2e_out = run_e2e()
        print(f"  E2E: {'PASSED' if e2e_ok else 'FAILED'}")

        if not e2e_ok:
            err_lines = [l.strip()[:150] for l in e2e_out.split("\n") if "Error" in l or "FAILED" in l]
            feedback = f"E2E FAILED:\n" + "\n".join(err_lines[:5])
            print(f"  Feedback: {feedback[:200]}...")
            continue

        # 候选回放
        print("  --- Candidate replay verification ---")
        replay_ok, replay_msg = run_candidate_replay()
        print(f"  Replay: {replay_msg[:200]}")

        if not replay_ok:
            feedback = f"Replay FAILED: {replay_msg[:500]}"
            continue

        print(f"\n  ✓ SUCCESS in round {rnd}")
        restore()
        return True

    print("\n  ✗ FAILED after 3 rounds")
    restore()
    return False


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

async def main():
    success = await closed_loop_with_opencode()

    print(f"\n{'=' * 60}")
    print(f"RESULT: {'PASSED' if success else 'FAILED'}")
    print(f"{'=' * 60}")

    # 对比：如果用 closed_loop_v2.py 的旧方案，代码行数对比
    v2_lines = len(Path(__file__).parent.joinpath("closed_loop_v2.py").read_text("utf-8").split("\n"))
    my_lines = len(Path(__file__).read_text("utf-8").split("\n"))
    print(f"\nCode size comparison:")
    print(f"  closed_loop_v2.py: {v2_lines} lines (DeepSeek client + extract_code + replace_code)")
    print(f"  closed_loop_opencode.py: {my_lines} lines (orchestrates opencode run)")
    print(f"  Reduction: {v2_lines - my_lines} lines ({100 - my_lines * 100 // v2_lines}%)")


if __name__ == "__main__":
    asyncio.run(main())
