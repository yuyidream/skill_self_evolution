"""方向4: 接口覆盖门禁 — 新代码必须被已知上游调用链实际执行到

核心逻辑:
1. 预定义 code_targets.interface_modules (已知调用者)
2. AI 生成代码后，插入探针行
3. 跑 E2E + 单元测试
4. 验证探针被触发 → 代码"活着"
5. 未触发 → 死代码 → 报警

已知接口（提前写入 evolve_prompt.yaml）:
- _resume_thumb_bindings_and_orphans 被 extract_nicknames (line 1712) 和另一个调用点 (line 1836) 调用
- E2E 测试 cover extract_nicknames → 理论上会触发 _resume_thumb_bindings_and_orphans
- 但 click_context 分支需要特殊场景（屏幕有点击）才会进入
"""
import sys, io, os, json, subprocess, textwrap
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TARGET = Path("E:/projects/housekeeping_ai_match/scripts/wx_match/processor/nickname_ocr_simple.py")
BACKEND = Path("E:/projects/housekeeping_ai_match/backend")
PROBE_FILE = Path("E:/projects/skill_self_evolution/data/coverage_probe_hits.json")

orig_content = TARGET.read_text("utf-8")

# ═══════════════════════════════════════════════════════════════
# 1. 预定义的接口知识 (code_targets.interface_modules)
# ═══════════════════════════════════════════════════════════════

INTERFACE_SPEC = {
    "target_file": "scripts/wx_match/processor/nickname_ocr_simple.py",
    "target_function": "_resume_thumb_bindings_and_orphans",
    "changed_region": "lines 949-959 (click_area block, inside if _click_ctx is not None)",
    "known_callers": [
        {
            "caller_function": "extract_nicknames",
            "call_site": "line 1712",
            "tested_in": "test_processor_pipeline_e2e.py",
            "branch_condition": "click_context is not None → 需要点击场景",
        },
        {
            "caller_function": "extract_nicknames (alt path)",
            "call_site": "line 1836",
            "tested_in": "test_processor_pipeline_e2e.py",
        }
    ],
    "branch_coverage_risk": "HIGH — E2E sets click_context=None, never enters the modified branch"
}

# ═══════════════════════════════════════════════════════════════
# 2. 探针插入
# ═══════════════════════════════════════════════════════════════

def inject_probe():
    """在 click_area block 后插入覆盖率探针"""
    c = TARGET.read_text("utf-8")
    marker = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    if marker not in c:
        return False

    # 找到 click_area 之后的第一个空行，插入探针
    idx = c.index(marker)
    # 往前找一个合适的插入位置：在 click_area 那行之后
    end_of_line = c.index("\n", idx) + 1

    probe_code = (
        "            # __COVERAGE_PROBE__\n"
        "            import os, pathlib, json; "
        "_p = os.environ.get('COVERAGE_PROBE_PATH', ''); "
        "_p and pathlib.Path(_p).write_text("
        "json.dumps({'probe': 'click_area_block', 'hit': True}))\n"
    )

    c = c[:end_of_line] + probe_code + c[end_of_line:]
    TARGET.write_text(c, "utf-8")
    return True

def remove_probe():
    """移除探针，恢复干净文件"""
    c = TARGET.read_text("utf-8")
    lines = c.split("\n")
    cleaned = [l for l in lines if "__COVERAGE_PROBE__" not in l]
    TARGET.write_text("\n".join(cleaned), "utf-8")

# ═══════════════════════════════════════════════════════════════
# 3. 测试执行 + 探针检测
# ═══════════════════════════════════════════════════════════════

def run_tests_with_probe() -> dict:
    """跑 E2E + 单元测试，检测探针是否被触发"""
    PROBE_FILE.unlink(missing_ok=True)

    env = os.environ.copy()
    env["COVERAGE_PROBE_PATH"] = str(PROBE_FILE)
    env["DB_PASSWORD"] = "local_root_123"

    results = {}

    # 3a. E2E 测试
    r = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/test_wx_match/test_processor_pipeline_e2e.py",
        "-q", "--tb=short", "--no-header", "-W", "ignore"
    ], cwd=str(BACKEND), capture_output=True, text=True, timeout=120, env=env)
    e2e_hit = PROBE_FILE.exists()
    results["e2e"] = {
        "passed": "failed" not in r.stdout and r.returncode == 0,
        "probe_hit": e2e_hit,
        "output": r.stdout[-500:],
    }
    if e2e_hit:
        results["e2e"]["probe_data"] = json.loads(PROBE_FILE.read_text())

    PROBE_FILE.unlink(missing_ok=True)

    # 3b. 单元测试
    r2 = subprocess.run([
        sys.executable, "-m", "pytest",
        "tests/test_wx_match/test_processor_nickname_ocr_simple.py",
        "-q", "--tb=short", "--no-header", "-W", "ignore"
    ], cwd=str(BACKEND), capture_output=True, text=True, timeout=120, env=env)
    unit_hit = PROBE_FILE.exists()
    results["unit"] = {
        "passed": "failed" not in r2.stdout and r2.returncode == 0,
        "probe_hit": unit_hit,
        "output": r2.stdout[-500:],
    }
    if unit_hit:
        results["unit"]["probe_data"] = json.loads(PROBE_FILE.read_text())

    PROBE_FILE.unlink(missing_ok=True)

    # 3c. 强制触发：构造一个带 click_context 的调用
    force_hit = force_probe_hit(env)
    results["force"] = {
        "passed": force_hit,
        "probe_hit": force_hit,
        "note": "mock with click_context → 绕过 E2E 盲区"
    }

    return results

def force_probe_hit(env) -> bool:
    """构造带 click_context 的调用验证新代码起码能跑"""
    script = r"""
import sys, os, json
sys.path.insert(0, r"E:\projects\housekeeping_ai_match")
sys.path.insert(0, r"E:\projects\housekeeping_ai_match\backend")
os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["COVERAGE_PROBE_PATH"] = r"{probe}"
from unittest.mock import MagicMock
from scripts.wx_match.processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig

s = MagicMock()
s.resume_thumb_bboxes = [[100, 200, 400, 500]]
s.original_resolution = MagicMock(width=720, height=1600)
ctx = MagicMock()
ctx.click_coords = [250, 350]  # 点击在卡片内
s.click_context = ctx

cfg = NicknameOcrConfig()
result = _resume_thumb_bindings_and_orphans(
    screenshot=s, blocks=[], classes=[],
    claimed_indices=set(), nicknames=(),
    config=cfg, original_width=720, image_size=(720, 1600)
)
print("OK")
""".format(probe=str(PROBE_FILE).replace("\\", "\\\\"))

    r = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=15,
        cwd=str(BACKEND), env=env
    )
    return PROBE_FILE.exists()

# ═══════════════════════════════════════════════════════════════
# 4. 主流程
# ═══════════════════════════════════════════════════════════════

def restore():
    TARGET.write_text(orig_content, "utf-8")
    PROBE_FILE.unlink(missing_ok=True)

def apply_ai_code():
    """模拟 AI 生成的代码（硬编码默认值，无 self）"""
    c = TARGET.read_text("utf-8")
    old = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    new = """            click_area = (cx, cy, cx + 2.0, cy + 2.0)
            min_overlap_area_ratio = 0.3
            ambiguity_tie_ratio = 0.05
            # 找唯一包含该区域的卡片
            matching_cards: list[int] = []
            for i, raw in enumerate(raws):
                if not raw or len(raw) < 4:
                    continue
                rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                    # 计算重叠面积占比
                    ox1 = max(cx, rx1); oy1 = max(cy, ry1)
                    ox2 = min(cx + 2.0, rx2); oy2 = min(cy + 2.0, ry2)
                    overlap = max(0, ox2 - ox1) * max(0, oy2 - oy1)
                    card_area = (rx2 - rx1) * (ry2 - ry1)
                    if card_area > 0 and overlap / card_area >= min_overlap_area_ratio:
                        matching_cards.append(i)
            if len(matching_cards) == 1:
                click_source_card_idx = matching_cards[0]
            elif len(matching_cards) >= 2:
                # 多卡重叠 → 计算面积差
                ratios = []
                for idx in matching_cards:
                    raw = raws[idx]
                    ox1 = max(cx, raw[0]); oy1 = max(cy, raw[1])
                    ox2 = min(cx + 2.0, raw[2]); oy2 = min(cy + 2.0, raw[3])
                    overlap = max(0, ox2 - ox1) * max(0, oy2 - oy1)
                    ratios.append((idx, overlap / ((raw[2]-raw[0])*(raw[3]-raw[1]))))
                ratios.sort(key=lambda x: x[1], reverse=True)
                if abs(ratios[0][1] - ratios[1][1]) / max(ratios[0][1], 1e-6) <= ambiguity_tie_ratio:
                    click_source_card_idx = None  # tie → renxin_system
                else:
                    click_source_card_idx = ratios[0][0]"""
    if old not in c:
        return False
    TARGET.write_text(c.replace(old, new, 1), "utf-8")
    return True

def main():
    print("="*60)
    print("DIRECTION 4: Interface Coverage Gate")
    print("="*60)

    print(f"\nKnown interface modules:")
    for caller in INTERFACE_SPEC["known_callers"]:
        print(f"  {caller['caller_function']} → {caller['tested_in']}")
    print(f"  Branch risk: {INTERFACE_SPEC['branch_coverage_risk']}")

    # Step 1: Apply AI code
    restore()
    print("\n--- Step 1: Apply AI-generated code ---")
    ok = apply_ai_code()
    print(f"  Applied: {ok}")

    # Step 2: Inject probe
    print("\n--- Step 2: Inject coverage probe ---")
    ok = inject_probe()
    print(f"  Probe injected: {ok}")

    # Step 3: Run tests with probe
    print("\n--- Step 3: Run tests + detect probe hits ---")
    results = run_tests_with_probe()

    for suite, data in results.items():
        icon = "✅" if data["probe_hit"] else "❌"
        print(f"  {suite:8s}: passed={data['passed']}  probe_hit={data['probe_hit']}  {icon}")
        if data["probe_hit"] and "probe_data" in data:
            print(f"           data: {json.dumps(data['probe_data'])}")
        if not data["probe_hit"]:
            print(f"           note: {data.get('note', 'CODE NOT EXERCISED — DEAD CODE')}")

    # Step 4: Gate decision
    print("\n--- Step 4: Gate Decision ---")
    any_hit = any(d["probe_hit"] for d in results.values())
    e2e_hit = results.get("e2e", {}).get("probe_hit", False)
    force_hit = results.get("force", {}).get("probe_hit", False)

    if any_hit:
        if e2e_hit:
            print("  ✅ PASS: New code exercised in E2E tests")
        elif force_hit:
            print("  ⚠ WARN: Code only exercised in forced test, not in E2E")
            print("  → Recommendation: extend E2E tests to cover click_context scenario")
            print("  → Or add to evolve_prompt.yaml: code_targets.require_e2e_extension: true")
        else:
            print("  ✅ PASS: Code exercised in unit tests")
    else:
        print("  ❌ FAIL: New code NEVER executed — DEAD CODE")
        print("  → REJECT this code change")

    # Step 5: Show what should be in evolve_prompt.yaml
    print("\n--- Step 5: evolve_prompt.yaml code_targets template ---")
    print("""code_targets:
  card_binding:
    config_path: correctness_criteria.verification_conditions[card_binding]
    target_file: scripts/wx_match/processor/nickname_ocr_simple.py
    target_function: _resume_thumb_bindings_and_orphans
    region_marker: "click_area = (cx, cy, cx + 2.0, cy + 2.0)"
    auto_context: true  # AST 自动提取变量/self检查
    interface_modules:   # 新: 接口覆盖门禁
      - test: test_processor_pipeline_e2e.py
        expected_coverage: indirect  # 通过调用链 cover，不是直接调用
      - test: test_processor_nickname_ocr_simple.py
        expected_coverage: direct
    branch_conditions:   # 新: 条件分支覆盖
      - condition: click_context is not None
        e2e_coverage: false  # E2E 不触发此分支
        force_validation: true  # 需要强制触发验证""")

    # Cleanup
    remove_probe()
    restore()
    print("\nRestored. Direction 4 complete.")

if __name__ == "__main__":
    main()
