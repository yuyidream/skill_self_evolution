"""Verify v4 new params can be recognized and consumed.
Tests: MySQL load, disk load, cross-condition pollution, _judge_correctness, no-corruption dry_run.
"""
import json, os, sys, io, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from ruamel.yaml import YAML

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["SKILL_LOG_DIR"] = "C:/data/skill-logs"

y = YAML(typ="safe")
passed = 0; failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1; print(f"  OK {name}")
    else:
        failed += 1; print(f"  FAIL {name} -- {detail}")

# ---- Test 1: MySQL load + new param extraction ----
print("=== Test 1: MySQL load ===")
sys.path.insert(0, "E:/projects/skill_self_evolution/src")
from skill_self_evolution.config_loader import ConfigVersionManager

mgr = ConfigVersionManager()
raw = mgr.load_raw("nickname-selector", "rules_config")
check("MySQL raw non-empty", bool(raw and len(raw) > 100), f"len={len(raw) if raw else 0}")

cfg_mysql = y.load(raw)
vc = cfg_mysql["correctness_criteria"]["verification_conditions"]
cb = [v for v in vc if v.get("id") == "card_binding"][0]

check("card_binding id ok", cb.get("id") == "card_binding")
check("min_overlap_area_ratio exists", "min_overlap_area_ratio" in cb)
check("ambiguity_tie_ratio exists", "ambiguity_tie_ratio" in cb)
check("min_overlap_area_ratio == 0.3", cb["min_overlap_area_ratio"] == 0.3)
check("ambiguity_tie_ratio == 0.05", cb["ambiguity_tie_ratio"] == 0.05)
check("both float type", isinstance(cb["min_overlap_area_ratio"], float) and
                         isinstance(cb["ambiguity_tie_ratio"], float))

desc = cb.get("description", "")
check("desc contains 30%", "30%" in desc)
check("desc contains 5%", "5%" in desc)

ORIGINAL_KEYS = {"id", "description", "checkable_in_skill", "note"}
new_keys = set(cb.keys()) - ORIGINAL_KEYS
check("new keys exactly 2", new_keys == {"min_overlap_area_ratio", "ambiguity_tie_ratio"},
      f"new_keys={new_keys}")
mgr.close()
print()

# ---- Test 2: Disk YAML load ----
print("=== Test 2: Disk YAML load ===")
disk_path = Path("E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/rules_config.yaml")
cfg_disk = y.load(disk_path.read_text(encoding="utf-8"))
vc_d = cfg_disk["correctness_criteria"]["verification_conditions"]
cb_d = [v for v in vc_d if v.get("id") == "card_binding"][0]

check("disk: min_overlap_area_ratio == 0.3", cb_d["min_overlap_area_ratio"] == 0.3)
check("disk: ambiguity_tie_ratio == 0.05", cb_d["ambiguity_tie_ratio"] == 0.05)
check("disk: bad_categories count == 6",
      len(cfg_disk["correctness_criteria"]["bad_categories"]) == 6)
check("disk: rejection_rules count == 4",
      len(cfg_disk.get("rejection_rules", [])) == 4)
print()

# ---- Test 3: Cross-condition pollution check ----
print("=== Test 3: Cross-condition pollution ===")
cc = [v for v in vc if v.get("id") == "click_coordinate"][0]
na = [v for v in vc if v.get("id") == "nickname_attribution"][0]

check("click_coordinate !has min_overlap_area_ratio", "min_overlap_area_ratio" not in cc)
check("click_coordinate !has ambiguity_tie_ratio", "ambiguity_tie_ratio" not in cc)
check("nickname_attribution !has min_overlap_area_ratio", "min_overlap_area_ratio" not in na)
check("nickname_attribution !has max_x_px", "max_x_px" not in na)
check("click_coordinate max_x_px == 20", cc.get("max_x_px") == 20)
check("click_coordinate max_y_px == 0", cc.get("max_y_px") == 0)
print()

# ---- Test 4: _judge_correctness consumes 6 bad_categories ----
print("=== Test 4: _judge_correctness ===")
sys.path.insert(0, "E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/scripts")
from run import _judge_correctness

correctness = cfg_mysql["correctness_criteria"]

bad_cases = [
    ("警惕不实营销信息", "安全横幅"),
    ("姓名：张三", "简历碎片"),
    ("年龄：30", "简历碎片"),
    ("QQQQ", "字母碎片"),
    ("@所有人", "系统消息"),
    ("撤回", "系统消息"),
    ("2024年12月", "日期格式"),
    ("3月15日", "日期格式"),
    ("家政阿姨13800138000", "SEO前缀"),
]
for text, cat in bad_cases:
    is_ok, matched = _judge_correctness(text, correctness)
    check(f"'{text}' => bad (cat={cat})", not is_ok,
          f"is_ok={is_ok}, matched={matched}")

good_cases = ["张伟", "王芳", "李经理", "小明123", "阿强"]
for text in good_cases:
    is_ok, matched = _judge_correctness(text, correctness)
    check(f"'{text}' => ok", is_ok, f"is_ok={is_ok}, matched={matched}")
print()

# ---- Test 5: Empty JSONL dry_run won't corrupt new params ----
print("=== Test 5: dry_run no corruption ===")
from skill_self_evolution.config import get_deepseek_config
from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.evolver import Evolver
import skill_self_evolution.evolver as _ev

def _merge_by_id(bl, ul):
    if not ul: return
    kf = None
    for i in ul:
        if isinstance(i, dict):
            if "id" in i: kf="id"; break
            if "name" in i: kf="name"; break
    if not kf: bl.clear(); bl.extend(ul); return
    um = {i[kf]: i for i in ul if isinstance(i, dict) and kf in i}
    for bi in bl:
        if isinstance(bi, dict) and kf in bi:
            k = bi[kf]
            if k in um: _ev._deep_update(bi, um[k]); del um[k]
    for ni in um.values(): bl.append(ni)

_orig_du = _ev._deep_update
def _du2(b, u):
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(b.get(k), dict): _du2(b[k], v)
        elif isinstance(v, list) and isinstance(b.get(k), list): _merge_by_id(b[k], v)
        else: b[k] = v
_ev._deep_update = _du2

async def _test():
    global passed, failed
    log_dir = Path("C:/data/skill-logs/nickname-selector")
    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    safe_case = {
        "trace_id": "v5-safe-001",
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "is_failure": True,
        "rule_output": {"nickname": "test_ok", "candidates": ["test_ok"]},
        "ai_validation": {"result": "unreasonable", "reason": "test"},
        "ai_reselection": {"result": "test_ok"},
        "final_output": {"source": "ai", "nickname": "test_ok"},
        "card_binding_passed": True,
        "click_coordinate_passed": True,
        "warnings": [], "elapsed_ms": 0,
    }
    jsonl_path = log_dir / f"{today}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(safe_case, ensure_ascii=False) + "\n")

    mgr3 = ConfigVersionManager()
    ds = get_deepseek_config()
    client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)
    evolver = Evolver(
        skill_name="nickname-selector",
        skill_base_dir=Path("E:/projects/housekeeping_ai_match/backend/config/services/skill"),
        deepseek=client,
        config_version_manager=mgr3,
    )
    proposal = await evolver.evolve(date_str=today, dry_run=True)
    rc = proposal.rules_changes

    check("dry_run: no bad_categories change",
          not rc.get("correctness_criteria", {}).get("bad_categories"))
    check("dry_run: no verification_conditions change",
          not rc.get("correctness_criteria", {}).get("verification_conditions"))
    check("dry_run: no rejection_rules change",
          not rc.get("rejection_rules"))
    mgr3.close()

asyncio.run(_test())
print()

# ---- Summary ----
print(f"{'='*50}")
print(f"Passed: {passed}  Failed: {failed}")
print(f"{'='*50}")
if failed == 0:
    print("ALL PASSED: new params correctly recognized and applicable")
else:
    print(f"WARNING: {failed} test(s) failed")
