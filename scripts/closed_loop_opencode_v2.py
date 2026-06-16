"""闭环验证 v2 — EvoSkill OpenCode Harness 版

与 closed_loop_v2.py 相同逻辑，但 AI 调用由 DeepSeekClient 换为
EvoSkill harness 的 execute_query（管理 opencode serve HTTP API）。
"""
import json, os, sys, io, subprocess, textwrap, ast, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

# ── 路径 & 环境 ─────────────────────────────────────────────────
sys.path.insert(0, r"E:\projects\skill_self_evolution\src")
os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DB_PASSWORD"] = "local_root_123"

TARGET = Path("E:/projects/housekeeping_ai_match/scripts/wx_match/processor/nickname_ocr_simple.py")
BACKEND = Path("E:/projects/housekeeping_ai_match/backend")

orig_content = TARGET.read_text("utf-8")
_BACKUP = Path(str(TARGET) + ".orig.bak")
_BACKUP.write_text(orig_content, "utf-8")  # 独立备份，不受文件状态影响

# ── harness 选项 ─────────────────────────────────────────────────
HARNESS_OPTIONS = {
    "provider_id": "deepseek",
    "model_id": "deepseek-chat",
    "mode": "build",
    "cwd": str(BACKEND),  # opencode serve 以 backend 为工作目录
}

# ═══════════════════════════════════════════════════════════════
# AST 工具
# ═══════════════════════════════════════════════════════════════

@dataclass
class FunctionContext:
    name: str
    is_method: bool
    params: list[str]
    local_vars: list[str]
    used_names: set[str]
    region_start: int
    region_end: int

def extract_context(filepath: Path, func_name: str) -> Optional[FunctionContext]:
    tree = ast.parse(filepath.read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            is_method = node.args.args and node.args.args[0].arg in ("self", "cls")
            params = [a.arg for a in node.args.args]
            local_vars = []
            used_names = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    used_names.add(child.id)
                if isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            local_vars.append(target.id)
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    local_vars.append(child.target.id)
            return FunctionContext(
                name=node.name, is_method=is_method, params=params,
                local_vars=list(dict.fromkeys(local_vars)),
                used_names=used_names,
                region_start=node.lineno, region_end=node.end_lineno or 0,
            )
    return None

# ═══════════════════════════════════════════════════════════════
# 基础工具
# ═══════════════════════════════════════════════════════════════

def restore():
    TARGET.write_text(_BACKUP.read_text("utf-8"), "utf-8")

def apply_hallucination():
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

def run_e2e():
    r = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/test_wx_match/test_processor_pipeline_e2e.py",
        "-q", "--tb=short", "--no-header", "-W", "ignore"
    ], cwd=str(BACKEND), capture_output=True, text=True, timeout=120)
    ok = True
    for line in r.stdout.split("\n"):
        if line.strip().endswith(" failed"):
            ok = False
    return ok, r.stdout[-3000:], r.stderr[-800:] if r.stderr else ""

def run_subprocess_script(script: str, timeout=30) -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND), capture_output=True, text=True, encoding='utf-8', timeout=timeout
    )
    out = (r.stdout + r.stderr).strip()
    if out.startswith("OK|"):
        return True, out
    return False, out[-2000:]

def run_candidate_replay():
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
    return run_subprocess_script(script)

def replace_code(new_code):
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
    dedented = textwrap.dedent(new_code)
    raw_lines = dedented.strip().split("\n")
    ind = "            "
    fixed = [ind + nl if nl.strip() else "" for nl in raw_lines]
    c = "\n".join(lines[:start_line] + fixed + lines[end_line:])
    TARGET.write_text(c, "utf-8")
    return True

# ═══════════════════════════════════════════════════════════════
# AI 客户端 — EvoSkill Harness (opencode serve)
# ═══════════════════════════════════════════════════════════════

from skill_self_evolution.harness.opencode.executor import execute_query

async def ask_via_opencode(system: str, prompt: str) -> str:
    """通过 EvoSkill harness 调用 opencode serve → DeepSeek"""
    options = dict(HARNESS_OPTIONS)
    options["system"] = system
    result = await execute_query(options, prompt)
    msgs = result[0].get("messages", [])
    for m in msgs:
        info = m.get("info", {})
        if info.get("role") == "assistant":
            text = "".join(
                p.get("text", "") for p in m.get("parts", [])
                if p.get("type") == "text"
            )
            return text
    return ""

def extract_code(ai_text):
    lines = ai_text.split("\n")
    start = -1
    for i, l in enumerate(lines):
        if l.strip().startswith("```python"):
            start = i + 1
        elif l.strip() == "```" and start >= 0:
            return "\n".join(lines[start:i])
    # 无代码块则返回 None（拒绝非代码文本）
    return None

# ═══════════════════════════════════════════════════════════════
# 方向1+2: 闭环修复 → 全量对比
# ═══════════════════════════════════════════════════════════════

SYSTEM_COMBINED = """You are a Python code fixer. You have NO tools.
Output ONLY a ```python``` code block to INSERT into a function body.
The code will replace lines 949-959 in _resume_thumb_bindings_and_orphans.
Available LOCAL variables: cx, cy (float), raws (list[list]), click_source_card_idx (int|None).
Params to HARDCODE: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05.
DO NOT: define a function, use self, import anything.
Output ```python``` ONLY. Max 12 lines."""

async def run_baseline_closed_loop() -> tuple[bool, str]:
    restore()
    apply_hallucination()

    print("--- Initial E2E ---")
    ok0, out0, _ = run_e2e()
    print(f"  {'PASSED' if ok0 else 'FAILED'}")

    last_fb = ""
    for rnd in range(1, 4):
        print(f"\n--- Round {rnd}/3 ---")

        if rnd == 1:
            prompt = f"""Insert Python code to replace these lines in _resume_thumb_bindings_and_orphans:

click_area = (cx, cy, cx + 2.0, cy + 2.0)
matching_cards: list[int] = []
for i, raw in enumerate(raws):
    if not raw or len(raw) < 4: continue
    rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2: matching_cards.append(i)
if len(matching_cards) == 1: click_source_card_idx = matching_cards[0]

New logic: overlap area ratio (min 0.3) + tie-breaking (0.05).
Use LOCAL variables: cx, cy, raws, click_source_card_idx. Hardcode params.
Output ```python``` ONLY (code to insert, NOT a function definition)."""
        else:
            prompt = last_fb

        ai = await ask_via_opencode(SYSTEM_COMBINED, prompt)
        code = extract_code(ai)
        # 拒绝过短的"代码"（通常是 AI 的文本响应）
        if code and len(code.strip()) < 50:
            code = None
        print(f"  AI: {len(ai)} chars, code={'yes' if code else 'no'}")

        if not code:
            last_fb = "No ```python``` code block. Output ONLY: ```python\\n<code>\\n```"
            continue

        restore()
        if not apply_hallucination():
            break
        replace_code(code)

        e2e_ok, e2e_out, _ = run_e2e()
        print(f"  E2E: {'PASSED' if e2e_ok else 'FAILED'}")
        if not e2e_ok:
            errs = [l.strip() for l in e2e_out.split("\n") if "Error" in l or "FAILED" in l][:5]
            last_fb = f"E2E FAILED:\n{chr(10).join(errs)}\nOutput ```python``` code to INSERT (not a function def)."
            continue

        replay_ok, replay_msg = run_candidate_replay()
        print(f"  Replay: {replay_msg[:200]}")
        if not replay_ok:
            err_lines = [l for l in replay_msg.split("\n") if l.strip()][-5:]
            err_summary = "\n".join(err_lines)
            # 添加针对性提示
            hint = ""
            if "not defined" in err_summary:
                hint = "Define min_overlap_area_ratio=0.3 and ambiguity_tie_ratio=0.05 at the TOP of your code."
            elif "self" in err_summary:
                hint = "NO self. This is a module-level function."
            last_fb = f"Replay FAILED:\n{err_summary}\n{hint}\nOutput ```python``` code to INSERT."
            continue

        print(f"\n  BASELINE PASSED in {rnd} round(s)")
        return True, code

    print("\n  BASELINE FAILED after 3 rounds")
    restore()
    return False, ""

# ═══════════════════════════════════════════════════════════════
# 方向3: Dev 写代码 + Test skill 测（分离模式）
# ═══════════════════════════════════════════════════════════════

DEV_SYSTEM = """You are a Python developer. Output ONLY ```python``` code to INSERT into a function body.
Keep code SHORT (max 15 lines). NO self, NO function def, NO imports.

Exact overlap formula to implement:
  ox1 = max(cx, rx1); oy1 = max(cy, ry1)
  ox2 = min(cx + 2.0, rx2); oy2 = min(cy + 2.0, ry2)
  overlap_area = (ox2 - ox1) * (oy2 - oy1)
  card_area = (rx2 - rx1) * (ry2 - ry1)
  ratio = overlap_area / card_area if card_area > 0 else 0

Algorithm:
  1. Hardcode: min_overlap_area_ratio = 0.3; ambiguity_tie_ratio = 0.05
  2. For each raw in raws: if overlap ratio >= 0.3 → store (index, ratio)
  3. If 0 candidates → click_source_card_idx = None
  4. If 1 candidate → click_source_card_idx = that index
  5. If 2+ candidates: sort by ratio desc
     If (best_ratio - second_ratio) / best_ratio <= 0.05 → None (tie, ambiguous)
     Else → click_source_card_idx = best index

Available LOCAL variables: cx, cy (float), raws (list[list[float]]), click_source_card_idx (int|None).
Output ONLY ```python``` code block."""

TEST_SYSTEM = """You are a code coach. Output EXACTLY one line:
PASS — code is correct
FIX: <specific fix> — exactly what to change

Checks (in priority order):
1. 'self' used? Say: "FIX: remove self., use local variables only"
2. Variable NOT in [cx, cy, raws, click_source_card_idx]? Say: "FIX: undefined variable X, only use cx,cy,raws,click_source_card_idx"
3. min_overlap_area_ratio or ambiguity_tie_ratio used but not defined? Say: "FIX: add min_overlap_area_ratio=0.3; ambiguity_tie_ratio=0.05 at top"
4. SyntaxError? Say: "FIX: <specific syntax error>"
5. Uses 'or' instead of hardcoded params? Say: "FIX: remove or, hardcode min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05"

Output ONLY "PASS" or "FIX: <instruction>". One line."""

SPEC = """Replace click_area matching block with overlap logic.
Original (lines 949-959):
    click_area = (cx, cy, cx + 2.0, cy + 2.0)
    matching_cards: list[int] = []
    for i, raw in enumerate(raws):
        if rx1 <= cx <= rx2 and ry1 <= cy <= ry2: matching_cards.append(i)
    if len(matching_cards) == 1: click_source_card_idx = matching_cards[0]

New logic: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05 (hardcoded).
Max 15 lines. Only use cx,cy,raws,click_source_card_idx. Output ```python```."""

async def direction_3_dev_test_loop():
    print("\n" + "="*60)
    print("DIRECTION 3: Dev/Test Separation (max 5 rounds, feedback history)")
    print("="*60)

    restore()
    feedback_entries: list[str] = []  # EvoSkill 式反馈历史累积

    for rnd in range(1, 6):
        print(f"\n--- Round {rnd}/5 ---")

        # Phase 1: Dev 生成代码（看到完整历史 + 上次反馈）
        dev_prompt = SPEC
        if rnd > 1 and feedback_entries:
            history = "\n".join(f"## Round {i}\n```python\n{code}\n```\nResult: {fb}"
                                for i, (code, fb) in enumerate(feedback_entries, 1))
            dev_prompt = (
                f"{SPEC}\n\n"
                f"## Previous Attempts (DO NOT repeat these mistakes)\n{history}\n\n"
                f"Fix ALL issues. Produce CORRECT code. Output ```python``` only."
            )

        code_text = await ask_via_opencode(DEV_SYSTEM, dev_prompt)
        code = extract_code(code_text)
        if code and len(code.strip()) < 50:
            code = None
        print(f"  Dev: {len(code_text)} chars, code={'yes' if code else 'no'}")
        if not code:
            fb = "FAIL: No ```python``` code block"
            if rnd > 1:
                feedback_entries.append((code or "(empty)", fb))
            continue

        # Phase 2: Test 静态分析（coach 模式：输出 FIX: <instruction>）
        test_prompt = f"""Review this code to INSERT into _resume_thumb_bindings_and_orphans:

```python
{code[:800]}
```

Verdict:"""
        test_resp = await ask_via_opencode(TEST_SYSTEM, test_prompt)
        static_pass = test_resp.strip().upper().startswith("PASS")
        print(f"  Test static: {'PASS' if static_pass else 'FAIL'}")
        print(f"  Test says: {test_resp[:200]}")

        if not static_pass:
            fb = test_resp.strip()[:400]
            feedback_entries.append((code[:300], fb))
            # 降级：3 轮后跳过静态检查
            if rnd >= 3:
                print("  -> static overridden, trying real tests")
            else:
                continue

        # Phase 3: 实际 E2E + Replay
        restore()
        apply_hallucination()
        replace_code(code)

        e2e_ok, e2e_out, _ = run_e2e()
        print(f"  E2E: {'PASSED' if e2e_ok else 'FAILED'}")

        if not e2e_ok:
            errs = [l.strip() for l in e2e_out.split("\n") if "Error" in l or "FAILED" in l][:3]
            fb = f"FAIL: E2E error: {'; '.join(errs)[:350]}"
            feedback_entries.append((code[:300], fb))
            continue

        replay_ok, replay_msg = run_candidate_replay()
        print(f"  Replay: {'PASSED' if replay_ok else 'FAILED'}")

        if replay_ok:
            print(f"\n  DIRECTION 3 SUCCESS in {rnd} round(s)")
            return
        else:
            err_lines = [l for l in replay_msg.split("\n") if l.strip()][-3:]
            fb = f"FAIL: Replay: {'; '.join(err_lines)[:350]}"
            feedback_entries.append((code[:300], fb))

    print(f"\n  DIRECTION 3 FAILED after 5 rounds")
    restore()

# ═══════════════════════════════════════════════════════════════
# 综合主入口
# ═══════════════════════════════════════════════════════════════

async def main():
    print("="*60)
    print("CLOSED LOOP V2 — EVOSKILL OPENCODE HARNESS")
    print("="*60)

    # ── AST 上下文 ──
    ctx = extract_context(TARGET, "_resume_thumb_bindings_and_orphans")
    if ctx:
        print(f"\nAST Context: {ctx.name}")
        print(f"  is_method={ctx.is_method}, params={ctx.params}")
        local_non_param = [v for v in ctx.local_vars if v not in ctx.params]
        print(f"  local_vars: {local_non_param[:15]}")
    else:
        print("  AST extraction failed")

    # ── 方向1+2: 闭环 + 全量对比 ──
    print("\n" + "="*60)
    print("DIRECTION 1+2: Baseline + Full Comparison")
    print("="*60)

    success, final_code = await run_baseline_closed_loop()
    restore()

    # ── 方向3: 分离模式 ──
    await direction_3_dev_test_loop()

    restore()
    print(f"\n{'='*60}\nALL DIRECTIONS COMPLETE\n{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
