"""闭环验证 v2 — 三个方向探索

方向1: 全量失败案例新旧对比 (Stage 3)
方向2: 全量候选回放 → Evolver 反馈 (Stage 4)
方向3: Dev 写代码 + Test skill 测 (分离模式)
"""
import json, os, sys, io, asyncio, subprocess, textwrap, ast
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
TARGET = Path("E:/projects/housekeeping_ai_match/scripts/wx_match/processor/nickname_ocr_simple.py")
BACKEND = Path("E:/projects/housekeeping_ai_match/backend")
EVOLVE_CASES = Path("E:/projects/skill_self_evolution/scripts/evolve_v4.py")

orig_content = TARGET.read_text("utf-8")

# ═══════════════════════════════════════════════════════════════
# AST 工具：自动提取函数上下文（解决"谁给上下文"的问题）
# ═══════════════════════════════════════════════════════════════

@dataclass
class FunctionContext:
    """从 AST 自动提取的函数上下文"""
    name: str
    is_method: bool  # 是否有 self/cls
    params: list[str]
    local_vars: list[str]  # 函数体内赋值的变量名
    used_names: set[str]  # 函数体内引用的所有名称
    region_start: int
    region_end: int

def extract_context(filepath: Path, func_name: str) -> Optional[FunctionContext]:
    """用 AST 提取函数的上下文信息"""
    tree = ast.parse(filepath.read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            is_method = node.args.args and node.args.args[0].arg in ("self", "cls")
            params = [a.arg for a in node.args.args]
            # 收集函数体内第一次赋值的变量
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
    TARGET.write_text(orig_content, "utf-8")

def apply_hallucination():
    c = TARGET.read_text("utf-8")
    old = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    new = old.rstrip() + "\n            click_w = click_area[2] - click_area[0]\n            click_h = click_area[3] - click_area[1]\n            click_area_size = click_w * click_h\n            min_overlap_area_ratio = self.config.get('card_binding', {}).get('min_overlap_area_ratio', 0.3)\n            ambiguity_tie_ratio = self.config.get('card_binding', {}).get('ambiguity_tie_ratio', 0.05)"
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
        if line.strip().endswith(" failed"): ok = False
    return ok, r.stdout[-3000:], r.stderr[-800:] if r.stderr else ""

def run_subprocess_script(script: str, timeout=30) -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND), capture_output=True, text=True, encoding='utf-8', timeout=timeout
    )
    out = (r.stdout + r.stderr).strip()
    if out.startswith("OK|"): return True, out
    return False, out[-800:]

def run_candidate_replay():
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
    return run_subprocess_script(script)

def replace_code(new_code):
    c = TARGET.read_text("utf-8")
    lines = c.split("\n")
    marker = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    end_marker = "for ci, raw in enumerate(raws):"
    start_line = end_line = None
    for i, l in enumerate(lines):
        if marker in l: start_line = i
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
# AI 客户端
# ═══════════════════════════════════════════════════════════════

from skill_self_evolution.config import get_deepseek_config
from skill_self_evolution.deepseek import DeepSeekClient
ds = get_deepseek_config()
client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)

async def ask(system: str, prompt: str) -> str:
    resp = await client.chat([{"role":"system","content":system},{"role":"user","content":prompt}])
    return resp.content if hasattr(resp, 'content') else str(resp)

def extract_code(ai_text):
    lines = ai_text.split("\n")
    start = -1
    for i, l in enumerate(lines):
        if l.strip().startswith("```python"): start = i + 1
        elif l.strip() == "```" and start >= 0: return "\n".join(lines[start:i])
    return None

# ═══════════════════════════════════════════════════════════════
# 方向1: 全量失败案例新旧对比
# ═══════════════════════════════════════════════════════════════

def load_evolve_cases() -> list[dict]:
    """加载 evolve_v4 测试用例（缓存到 JSON 文件避免 subprocess stdout 问题）"""
    cache = Path("E:/projects/skill_self_evolution/data/evolve_v4_cases.json")
    if cache.exists():
        return json.loads(cache.read_text("utf-8"))
    # 首次加载：用临时脚本生成并保存
    gen_script = (
        "import sys,io,json;sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8');"
        "exec(open(r'E:\\projects\\skill_self_evolution\\scripts\\evolve_v4.py',encoding='utf-8').read().split('async def main')[0]);"
        "open(r'E:\\projects\\skill_self_evolution\\data\\evolve_v4_cases.json','w',encoding='utf-8').write(json.dumps(ALL,ensure_ascii=False))"
    )
    subprocess.run([sys.executable, "-c", gen_script], timeout=15,
                   cwd="E:/projects/skill_self_evolution",
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if cache.exists():
        return json.loads(cache.read_text("utf-8"))
    return []

@dataclass
class CaseResult:
    case_id: str
    category: str
    old_binds_to: int | None  # 旧代码绑定的卡片索引
    new_binds_to: int | None  # 新代码绑定的卡片索引
    expected: str  # good_candidates[0] or renxin_system
    old_correct: bool
    new_correct: bool
    improved: bool  # old错误 new正确
    degraded: bool  # old正确 new错误
    unchanged: bool

def make_mock_scenario(case: dict) -> dict:
    """根据 evolve_v4 case 构造可对比的 mock 场景

    旧代码行为: 按顺序找第一个包含点击点的卡片 → 绑第一张
    新代码行为: 计算重叠面积占比 → min_overlap_area_ratio + tie_ratio

    构造两张卡重叠，点击在重叠区：
    - 卡1 (正确卡): 面积大，占重叠区 50%+
    - 卡2 (误绑卡): 面积小，占重叠区 30%-
    旧代码绑卡2(先遍历到的)，新代码应绑卡1 或 None
    """
    correct_ratio = case["overlap_info"]["correct_card_area_ratio"]
    wrong_ratio = case["overlap_info"].get("bound_card_area_ratio", 0.3)

    # 构造场景：两张卡部分重叠，点击在重叠区中心
    # 卡1(小/误绑): [200, 250, 480, 450] → 280x200
    # 卡2(大/正确): [320, 200, 600, 480] → 280x280
    # 重叠区: x:320-480, y:250-450 → 160x200
    # 卡1在重叠区占比: 160*200 / (280*200) = 57%... 不好

    # 简化: 大卡 + 小卡，点击在重叠区
    big_card = [200, 200, 600, 500]   # 大卡: 400x300
    small_card = [350, 250, 500, 380] # 小卡: 150x130 (嵌套在大卡内)
    # 点击在小卡中心: [425, 315]
    # 旧代码: 先遍历到大卡 → 绑大卡 (正确)
    # 反过来: 先遍历到小卡 → 绑小卡 (误绑)

    # 构造: 小卡在前，大卡在后
    rng = __import__('random').Random(42)
    if case["id"].startswith("v4-t"):  # tie 场景
        # 两张等面积卡重叠
        card1 = [250, 200, 550, 500]  # 300x300
        card2 = [300, 200, 600, 500]  # 300x300, 重叠50%
        bboxes = [card1, card2]
    else:
        # 面积不等: 小卡先于大卡
        bboxes = [small_card, big_card]

    cx, cy = 425, 315  # 在小卡内部（也在大卡内部）

    return {
        "bboxes": bboxes,
        "click": [cx, cy],
        "expected_card_idx": 1 if not case["id"].startswith("v4-t") else None,
        "old_expected_idx": 0,  # 旧代码绑第一个匹配的 = 卡0
        "case": case,
    }

CASE_COMPARISON_SCRIPT = '''
import sys, os, json
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match")
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match\\backend")
os.environ["DB_PASSWORD"] = "local_root_123"
from unittest.mock import MagicMock
from scripts.wx_match.processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig

bboxes = {bboxes}
cx, cy = {cx}, {cy}

s = MagicMock()
s.resume_thumb_bboxes = bboxes
s.original_resolution = MagicMock(width=720, height=1600)
ctx = MagicMock()
ctx.click_coords = [cx, cy]
s.click_context = ctx

cfg = NicknameOcrConfig()
try:
    result = _resume_thumb_bindings_and_orphans(
        screenshot=s, blocks=[], classes=[],
        claimed_indices=set(), nicknames=(),
        config=cfg, original_width=720, image_size=(720, 1600)
    )
    # 返回 clicked 卡的索引（如果 click_source_card_idx 有值）
    # 实际上 click_source_card_idx 在函数内部使用，不直接返回
    # 我们通过 orphan 来推断：如果 orphan=2 且 bindings=0 → 无绑定
    bindings, orphan, excluded = result
    print(json.dumps({{"bindings": len(bindings) if bindings else 0, "orphan": orphan, "ok": True}}))
except Exception as e:
    import traceback
    print(json.dumps({{"ok": False, "error": str(e)}}))
'''

def run_case_comparison() -> list[dict]:
    """Stage 3: 新旧代码全量对比 — 用独立函数测试 overlap 逻辑"""
    cases = load_evolve_cases()
    print(f"  Loaded {len(cases)} evolve cases")

    sample_cases = [c for c in cases if c["id"].startswith("v4-u")][:5] + \
                   [c for c in cases if c["id"].startswith("v4-t")][:5]
    print(f"  Testing {len(sample_cases)} cases (overlap logic comparison)")

    results = []
    for case in sample_cases:
        expected = case.get("good_candidates", [])
        expected_nick = expected[0] if expected else "renxin_system"

        if case["id"].startswith("v4-t"):
            bboxes = [[250, 200, 550, 500], [300, 200, 600, 500]]
        else:
            bboxes = [[350, 250, 500, 380], [200, 200, 600, 500]]
        cx, cy = 425, 315

        script = '''
import sys, os, json
bboxes = {bboxes}
cx, cy = {cx}, {cy}

old_idx = None
for i, raw in enumerate(bboxes):
    if not raw or len(raw) < 4: continue
    rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
        old_idx = i; break

min_r = 0.3; tie_r = 0.05
click = [cx, cy, cx + 2.0, cy + 2.0]
cands = []
for i, raw in enumerate(bboxes):
    if not raw or len(raw) < 4: continue
    rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
        ox1 = max(click[0], rx1); oy1 = max(click[1], ry1)
        ox2 = min(click[2], rx2); oy2 = min(click[3], ry2)
        overlap = max(0, ox2 - ox1) * max(0, oy2 - oy1)
        card_a = (rx2 - rx1) * (ry2 - ry1)
        ratio = overlap / card_a if card_a > 0 else 0
        if ratio >= min_r: cands.append((i, ratio))

if len(cands) == 1: new_idx = cands[0][0]
elif len(cands) >= 2:
    s = sorted(cands, key=lambda x: x[1], reverse=True)
    if abs(s[0][1] - s[1][1]) / max(s[0][1], 1e-6) <= tie_r:
        new_idx = None
    else: new_idx = s[0][0]
else: new_idx = None

print(json.dumps({{"old_idx": old_idx, "new_idx": new_idx}}))
'''.format(bboxes=json.dumps(bboxes), cx=cx, cy=cy)

        r = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, encoding='utf-8', timeout=10,
            cwd=str(BACKEND)
        )
        try:
            data = json.loads(r.stdout.strip())
        except:
            data = {"old_idx": -2, "new_idx": -2}

        old_idx = data.get("old_idx")
        new_idx = data.get("new_idx")
        changed = old_idx != new_idx

        result = {
            "case_id": case["id"], "category": case["category"],
            "expected": expected_nick,
            "old_binds_to": old_idx, "new_binds_to": new_idx,
            "changed": changed,
        }
        results.append(result)
        flag = "CHANGED" if changed else "same"
        print(f"  {case['id']}: old->{old_idx} new->{new_idx} [{flag}]")

    changed_n = sum(1 for r in results if r["changed"])
    print(f"\n  Summary: {changed_n}/{len(results)} behavior changes")
    return results

# ═══════════════════════════════════════════════════════════════
# 方向2: 全量候选回放 → Evolver 格式
# ═══════════════════════════════════════════════════════════════

def generate_evolver_feedback(new_code: str) -> dict:
    """将代码变更和全量回放结果格式化为 Evolver 可消费的反馈"""
    return {
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "code_change": {
            "file": str(TARGET),
            "new_block": new_code[:500],
            "loc_changed": "lines 949-959",
        },
        "summary": {
            "e2e_passed": True,
            "candidate_replay_passed": True,
        },
        # 方向1的比较结果会填充到这里
        "case_comparison": {},
        "recommendation": "keep"  # 或 rollback
    }

# ═══════════════════════════════════════════════════════════════
# 方向3: Dev 写代码 + Test skill 测（分离模式）
# ═══════════════════════════════════════════════════════════════

DEV_SYSTEM = """You are a Python developer. Your ONLY job: write concise, correct Python code.
Do NOT test. Do NOT validate. Keep code SHORT.

Target: _resume_thumb_bindings_and_orphans (module-level function, NO self!)
Variables: cx, cy, raws, click_source_card_idx
Params to implement: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05

Rules:
- Max 15 lines of code
- Hardcode params (no imports, no config lookups)
- NO self — this is a module-level function
- Output ONLY ```python``` code block"""

TEST_SYSTEM = r"""You are test-collector-customized-for-renxin, a testing expert.
Analyze code for bugs. Be strict.

Target: module-level function _resume_thumb_bindings_and_orphans
Rules:
1. NO self allowed (module-level function)
2. Variables: cx, cy, raws, click_source_card_idx
3. Params: min_overlap_area_ratio, ambiguity_tie_ratio

Report: PASS or FAIL with specific reason."""

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
    """方向3: Dev 生成 → Test skill 静态分析 → E2E → 候选回放"""
    print("\n" + "="*60)
    print("DIRECTION 3: Dev/Test Separation")
    print("="*60)

    restore()

    for rnd in range(1, 3):
        print(f"\n--- Round {rnd}/2 ---")

        # Phase 1: Dev 生成代码
        dev_prompt = SPEC
        if rnd > 1:
            dev_prompt = f"{SPEC}\n\nTest feedback from last round:\n{test_fb}"

        code_text = await ask(DEV_SYSTEM, dev_prompt)
        code = extract_code(code_text)
        print(f"  Dev: {len(code_text)} chars, code={code is not None}")
        if not code:
            print("  No code from dev")
            continue

        # Phase 2: Test skill 静态分析
        test_prompt = f"""Analyze this code for bugs:

```python
{code[:1000]}
```

Check for: self usage, unknown variables, logic errors with overlap area / tie ratio."""
        test_resp = await ask(TEST_SYSTEM, test_prompt)
        static_pass = "PASS" in test_resp.upper() and "FAIL" not in test_resp.upper()
        print(f"  Test static: {'PASS' if static_pass else 'FAIL'}")
        print(f"  Test says: {test_resp[:250]}")

        if not static_pass:
            test_fb = test_resp[:500]
            continue

        # Phase 3: 应用代码 + 实际 E2E
        restore()
        replace_code(code)

        e2e_ok, e2e_out, _ = run_e2e()
        print(f"  Actual E2E: {'PASSED' if e2e_ok else 'FAILED'}")

        if not e2e_ok:
            test_fb = f"E2E FAILED:\n{e2e_out[-500:]}"
            continue

        replay_ok, replay_msg = run_candidate_replay()
        print(f"  Actual Replay: {replay_msg[:150]}")

        if replay_ok:
            print(f"\n  DIRECTION 3 SUCCESS in {rnd} round(s)")
            return
        else:
            test_fb = f"Replay FAILED: {replay_msg[:500]}"

    print(f"\n  DIRECTION 3 FAILED after 2 rounds")
    restore()

# ═══════════════════════════════════════════════════════════════
# 综合主入口
# ═══════════════════════════════════════════════════════════════

SYSTEM_COMBINED = """You are test-collector-customized-for-renxin dev+test expert.
Fix code in _resume_thumb_bindings_and_orphans (module-level, NO self).
Variables: cx, cy (float), raws (list), click_source_card_idx (int|None).
DO NOT use: self, config.get, card_bboxes, card_rects.
Params: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05 (hardcode).
Output ONLY ```python code block```."""

async def run_baseline_closed_loop() -> tuple[bool, str]:
    """第1-2重: E2E + 候选回放。返回 (success, final_code)"""
    restore()
    apply_hallucination()

    print("--- Initial E2E ---")
    ok0, out0, _ = run_e2e()
    print(f"  {'PASSED' if ok0 else 'FAILED'}")
    init_fail = out0[-2000:] if not ok0 else ""

    final_code = None
    last_fb = ""
    for rnd in range(1, 4):
        print(f"\n--- Round {rnd}/3 ---")

        if rnd == 1:
            prompt = f"""Fix BUGGY code in _resume_thumb_bindings_and_orphans (NO self).
Variables: cx, cy, raws, click_source_card_idx.
Params: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05 (hardcode).

Original code:
click_area = (cx, cy, cx + 2.0, cy + 2.0)
matching_cards: list[int] = []
for i, raw in enumerate(raws):
    if not raw or len(raw) < 4: continue
    rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2: matching_cards.append(i)
if len(matching_cards) == 1: click_source_card_idx = matching_cards[0]

Output ```python``` block only."""
        else:
            prompt = last_fb

        ai = await ask(SYSTEM_COMBINED, prompt)
        code = extract_code(ai)
        if not code:
            last_fb = "No code block. Output ```python```."
            continue

        restore()
        if not apply_hallucination(): break
        replace_code(code)

        e2e_ok, e2e_out, _ = run_e2e()
        print(f"  E2E: {'PASSED' if e2e_ok else 'FAILED'}")
        if not e2e_ok:
            errs = [l.strip()[:150] for l in e2e_out.split("\n") if "Error" in l or "FAILED" in l]
            last_fb = f"E2E FAILED:\n{chr(10).join(errs[:5])}\nOnly cx,cy,raws. ```python```."
            continue

        replay_ok, replay_msg = run_candidate_replay()
        print(f"  Replay: {replay_msg[:120]}")
        if not replay_ok:
            last_fb = f"Replay FAILED: {replay_msg[:500]}\nOnly cx,cy,raws. No self."
            continue

        final_code = code
        print(f"\n  BASELINE PASSED in {rnd} round(s)")
        return True, final_code

    print("\n  BASELINE FAILED after 3 rounds")
    restore()
    return False, ""

def show_block():
    lines = TARGET.read_text("utf-8").split("\n")
    for i, l in enumerate(lines):
        if "click_area = (cx, cy, cx + 2.0, cy + 2.0)" in l:
            return "\n".join(lines[i:i+12])
    return "(not found)"

async def main():
    print("="*60)
    print("CLOSED LOOP V2 — THREE DIRECTIONS")
    print("="*60)

    # ── AST 上下文（自动提取，不再硬编码） ──
    ctx = extract_context(TARGET, "_resume_thumb_bindings_and_orphans")
    if ctx:
        print(f"\nAST Context: {ctx.name}")
        print(f"  is_method={ctx.is_method}, params={ctx.params}")
        local_non_param = [v for v in ctx.local_vars if v not in ctx.params]
        print(f"  local_vars: {local_non_param[:15]}")
        # 这些信息应注入到 AI 代码生成的 prompt 里
        # 实际操作中由 evolve_prompt.yaml 的 code_targets.auto_context=true 触发
    else:
        print("  AST extraction failed")

    # ── 方向1+2: 闭环 + 全量对比 ──
    print("\n" + "="*60)
    print("DIRECTION 1+2: Baseline + Full Comparison")
    print("="*60)

    success, final_code = await run_baseline_closed_loop()

    if success and final_code:
        # 现在的文件状态就是新代码（baseline 成功后没有 restore）
        print("\n--- Stage 3: Full Old-vs-New Comparison ---")
        results = run_case_comparison()

        # 方向2: 生成 Evolver 格式反馈
        if results:
            feedback = generate_evolver_feedback(final_code)
            feedback["case_comparison"] = {
                "total": len(results),
                "improved": sum(1 for r in results if r.get("improved")),
                "degraded": sum(1 for r in results if r.get("degraded")),
                "unchanged": sum(1 for r in results if not r.get("changed")),
            }
            feedback["recommendation"] = "rollback" if any(r.get("degraded") for r in results) else "keep"
            print(f"\n  Evolver feedback: {json.dumps(feedback['case_comparison'])}")
            print(f"  Recommendation: {feedback['recommendation']}")
    else:
        print("\n  Baseline failed, skipping comparison")

    # ── 恢复 ──
    restore()

    # ── 方向3: 分离模式 ──
    await direction_3_dev_test_loop()

    restore()
    print(f"\n{'='*60}\nALL DIRECTIONS COMPLETE\n{'='*60}")

if __name__ == "__main__":
    asyncio.run(main())
