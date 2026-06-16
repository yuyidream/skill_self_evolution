"""Closed-loop verification: AI code gen -> E2E -> fail feedback -> fix -> candidate replay
Max 3 rounds, 2 gates
"""
import json, os, sys, io, asyncio, subprocess
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

TARGET = Path("E:/projects/housekeeping_ai_match/scripts/wx_match/processor/nickname_ocr_simple.py")
BACKEND = Path("E:/projects/housekeeping_ai_match/backend")

orig_content = TARGET.read_text("utf-8")

def restore():
    TARGET.write_text(orig_content, "utf-8")
    for k in list(sys.modules.keys()):
        if "nickname_ocr" in k or "ntest" in k:
            del sys.modules[k]

def apply_hallucination():
    c = TARGET.read_text("utf-8")
    old = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    new = old.rstrip() + "\n            click_w = click_area[2] - click_area[0]\n            click_h = click_area[3] - click_area[1]\n            click_area_size = click_w * click_h\n            min_overlap_area_ratio = self.config.get('card_binding', {}).get('min_overlap_area_ratio', 0.3)\n            ambiguity_tie_ratio = self.config.get('card_binding', {}).get('ambiguity_tie_ratio', 0.05)"
    if old not in c:
        print("  WARN: hallucination marker not found")
        return False
    TARGET.write_text(c.replace(old, new, 1), "utf-8")
    return True

def run_e2e():
    r = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/test_wx_match/test_processor_pipeline_e2e.py",
        "-q", "--tb=long", "--no-header", "-W", "ignore"
    ], cwd=str(BACKEND), capture_output=True, text=True, timeout=120)
    ok = True
    for line in r.stdout.split("\n"):
        if line.strip().endswith(" failed"):
            ok = False
    return ok, r.stdout[-3000:], r.stderr[-1000:] if r.stderr else ""

def run_candidate_replay():
    """用 subprocess 调用目标函数，避免 importlib 导入冲突"""
    script = f'''
import sys, os
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match")
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match\\backend")
os.environ["DB_PASSWORD"] = "local_root_123"
from unittest.mock import MagicMock
from scripts.wx_match.processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig
s = MagicMock()
s.resume_thumb_bboxes = [[100, 200, 400, 500], [350, 200, 600, 500]]
s.original_resolution = MagicMock(width=720, height=1600)
ctx = MagicMock()
ctx.click_coords = [375, 350]
s.click_context = ctx
cfg = NicknameOcrConfig()
try:
    result = _resume_thumb_bindings_and_orphans(
        screenshot=s, blocks=[], classes=[],
        claimed_indices=set(), nicknames=(),
        config=cfg, original_width=720, image_size=(720, 1600)
    )
    bindings, orphan, excluded = result
    print(f"OK|bindings={{len(bindings) if bindings else 0}}|orphan={{orphan}}")
except Exception as e:
    import traceback
    print(f"ERROR|{{type(e).__name__}}: {{e}}")
    traceback.print_exc()
'''
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND), capture_output=True, text=True, timeout=30
    )
    out = (r.stdout + r.stderr).strip()
    if out.startswith("OK|"):
        return True, out
    else:
        return False, out[-800:]

# AI
from skill_self_evolution.config import get_deepseek_config
from skill_self_evolution.deepseek import DeepSeekClient
ds = get_deepseek_config()
client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)

SYSTEM = """You are the test-collector-customized-for-renxin dev+test expert.
Fix code that fails tests/candidate replay.

Target: scripts/wx_match/processor/nickname_ocr_simple.py
Function: _resume_thumb_bindings_and_orphans (module-level, NO self!)
Area: click_area matching block

New params from rules_config.yaml:
  min_overlap_area_ratio: 0.3 (intersection/card >= 0.3 to bind)
  ambiguity_tie_ratio: 0.05 (area diff < 5% -> renxin_system)

Output: ONLY ```python code block``` (replacement for lines 949-959)."""

async def ask(prompt):
    resp = await client.chat([{"role":"system","content":SYSTEM},{"role":"user","content":prompt}])
    return resp.content if hasattr(resp,'content') else str(resp)

def extract_code(ai_text):
    lines = ai_text.split("\n")
    start = -1
    for i, l in enumerate(lines):
        if l.strip().startswith("```python"): start = i + 1
        elif l.strip() == "```" and start >= 0: return "\n".join(lines[start:i])
    return None

def replace_code(new_code):
    c = TARGET.read_text("utf-8")
    lines = c.split("\n")
    marker = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    end_marker = "for ci, raw in enumerate(raws):"
    start_line = end_line = None
    for i, l in enumerate(lines):
        if marker in l: start_line = i
        if start_line is not None and end_marker in l:
            # 往后退一个空行（如果有）
            end_line = i
            if end_line > 0 and lines[end_line - 1].strip() == "":
                end_line = end_line - 1
            break
    if start_line is None or end_line is None:
        print(f"  Marker err: start={start_line}, end={end_line}")
        return False
    import textwrap
    dedented = textwrap.dedent(new_code)
    raw_lines = dedented.strip().split("\n")
    ind = "            "
    fixed = []
    for nl in raw_lines:
        if not nl.strip(): fixed.append(""); continue
        fixed.append(ind + nl)
    print(f"  dedented preview: {dedented[:200]}")
    c = "\n".join(lines[:start_line] + fixed + lines[end_line:])
    TARGET.write_text(c, "utf-8")
    return True

def show_block():
    lines = TARGET.read_text("utf-8").split("\n")
    for i, l in enumerate(lines):
        if "click_area = (cx, cy, cx + 2.0, cy + 2.0)" in l:
            return "\n".join(lines[i:i+12])
    return "(not found)"

async def main():
    restore()

    print("STEP 0: Apply hallucination")
    if not apply_hallucination(): return
    print(show_block()[:400])

    print("\n--- Initial E2E (expect FAIL) ---")
    ok0, out0, err0 = run_e2e()
    print(f"  {'PASSED' if ok0 else 'FAILED (expected)'}")
    init_fail = out0[-2000:] if not ok0 else ""

    last_fb = ""
    for rnd in range(1, 4):
        print(f"\n{'='*60}\nROUND {rnd}/3\n{'='*60}")

        if rnd == 1:
            # Include the function context so AI knows what variables exist
            prompt = f"""Fix the BUGGY code in _resume_thumb_bindings_and_orphans (module-level, NO self!).

Function signature: def _resume_thumb_bindings_and_orphans(screenshot, blocks, classes, claimed_indices, nicknames, config, original_width, image_size)

Available variables in scope before the target block:
  - cx, cy: click coordinates (float)
  - raws: list of resume thumb bboxes
  - click_source_card_idx: int|None (already declared as None)
  - card_rects: dict (MUST NOT use - renamed to raws)
  - card_volumes: list (MUST NOT use)

The BUGGY block adds self.config which doesn't exist in module-level functions:
{show_block()[:500]}

Original clean code before the bug was:
```python
click_area = (cx, cy, cx + 2.0, cy + 2.0)
matching_cards: list[int] = []
for i, raw in enumerate(raws):
    if not raw or len(raw) < 4:
        continue
    rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
        matching_cards.append(i)
if len(matching_cards) == 1:
    click_source_card_idx = matching_cards[0]
```

Task: Replace the BUGGY block with a version that implements min_overlap_area_ratio (0.3) and ambiguity_tie_ratio (0.05) using ONLY existing variables (cx, cy, raws, click_source_card_idx). NO self, NO config.get, NO card_bboxes. Output ONLY ```python``` block."""
        else:
            prompt = last_fb

        ai = await ask(prompt)
        code = extract_code(ai)
        print(f"AI: {len(ai)} chars, code={code is not None}")
        if not code:
            print("  No code")
            last_fb = "No ```python block found. Output ONLY the code block."
            continue

        print(f"  {len(code)} chars extracted")
        restore()
        if not apply_hallucination(): break
        replace_code(code)
        print(f"  Block now:\n{show_block()[:350]}")

        print("\n--- E2E ---")
        ok1, out1, err1 = run_e2e()
        print(f"  {'PASSED' if ok1 else 'FAILED'}")
        if not ok1:
            err_lines = [l.strip()[:200] for l in out1.split("\n") if "Error" in l or "FAILED" in l]
            last_fb = f"""E2E FAILED. Fix.

Errors:
{chr(10).join(err_lines[:8])}

Last code:
{code[:500]}

Available variables: cx, cy (float), raws (list), click_source_card_idx (int|None).
DO NOT: self, config.get, card_bboxes, card_rects.
Output ```python```."""
            continue

        print("\n--- Candidate Replay ---")
        ok2, msg2 = run_candidate_replay()
        print(f"  {msg2[:200]}")
        if not ok2:
            last_fb = f"""Replay FAILED: {msg2[:800]}

Available variables: cx, cy (float), raws (list of bboxes), click_source_card_idx (int|None).
DO NOT use: self, config.get, card_bboxes, card_rects, card_volumes.

Last generated code:
{code[:500]}

Fix: use ONLY the available variables. Output ```python```."""
            continue

        print(f"\n{'='*60}\nSUCCESS after {rnd} round(s)\n{'='*60}")
        restore()
        return

    print(f"\n{'='*60}\nFAILED after 3 rounds\n{'='*60}")
    restore()

asyncio.run(main())
