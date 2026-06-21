"""造 v3 测试数据 — 聚焦条件三（click_coordinate）容差边界
目标：让 Evolver 提出 verification_conditions 阈值调整
- X ≤ 20px 太宽 → 应收紧到 ≤ 10~15px（有大量 11-19px 的误过案例）
- Y = 0 太严 → 应放宽到 ≤ 2px（有少量 ±1px 误差的误拦案例）
"""
import json, asyncio, os, sys, io
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["SKILL_LOG_DIR"] = "C:/data/skill-logs"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
BEIJING_TZ = timezone(timedelta(hours=8))

def make_x_boundary_case(idx, offset_x, offset_y=0):
    """X 偏移在 11-19px 范围内，当前阈值 ≤20 误过"""
    return {
        "id": f"v3-x{idx:03d}",
        "category": "条件三·X容差边界",
        "rule_nickname": f"昵称X{idx}",
        "candidates": [f"昵称X{idx}", f"正确X{idx}"],
        "good_candidates": [f"正确X{idx}"],
        "why_wrong": f"X偏移={offset_x}px 在当前20px容差内通过，但实际点击了相邻卡片边缘",
        "card_binding_ok": True,
        "nickname_attribution_ok": False,
        "click_ok": True,
        "click_offset": {"x_px": offset_x, "y_px": offset_y},
        "current_threshold": {"max_x_px": 20, "max_y_px": 0},
        "suggested_fix": f"建议条件三 X容差从20px收紧到≤10px（当前误过{offset_x}px偏移案例）",
        "verification_target": "click_coordinate.max_x_px",
        "current_value": 20,
        "suggested_value": 10,
    }

def make_y_boundary_case(idx, offset_x, offset_y):
    """Y 偏移 1-3px 范围内，当前阈值 Y=0 误拦"""
    return {
        "id": f"v3-y{idx:03d}",
        "category": "条件三·Y容差边界",
        "rule_nickname": f"昵称Y{idx}",
        "candidates": [f"昵称Y{idx}", f"正确Y{idx}"],
        "good_candidates": [f"正确Y{idx}"],
        "why_wrong": f"Y偏移={offset_y}px 但因Y≠0被条件三拒绝，实际卡片对齐有±1-2px误差是正常的",
        "card_binding_ok": True,
        "nickname_attribution_ok": False,
        "click_ok": False,
        "click_offset": {"x_px": offset_x, "y_px": offset_y},
        "current_threshold": {"max_x_px": 20, "max_y_px": 0},
        "suggested_fix": f"建议条件三 Y容差从0放宽到≤2px（当前{offset_y}px偏移被误杀）",
        "verification_target": "click_coordinate.max_y_px",
        "current_value": 0,
        "suggested_value": 2,
    }

# ═══════════════════════════════════════════════════════════
# 场景 A: X 容差边界 — 30 条 (X=11~19px，故意不同值)
# ═══════════════════════════════════════════════════════════
X_CASES = []
x_offsets = [11,12,12,13,14,14,15,15,16,16, 17,17,18,18,19,19, 11,12,13,13,14,15,15,16,17,18,19,19,16,12]
for i, ox in enumerate(x_offsets):
    X_CASES.append(make_x_boundary_case(i+1, ox))

# ═══════════════════════════════════════════════════════════
# 场景 B: Y 容差边界 — 20 条 (Y=1,2,3px)
# ═══════════════════════════════════════════════════════════
Y_CASES = []
y_offsets = [(5,1),(8,1),(3,2),(7,2),(4,1),(6,2),(2,1),(9,1),(5,1),(10,3),
             (4,2),(7,1),(6,3),(8,2),(3,1),(9,2),(5,3),(10,1),(2,2),(7,3)]
for i, (ox, oy) in enumerate(y_offsets):
    Y_CASES.append(make_y_boundary_case(i+1, ox, oy))

# ═══════════════════════════════════════════════════════════
# 场景 C: 少量对比 — 卡片重叠歧义 (保留控制组)
# ═══════════════════════════════════════════════════════════
OVERLAP_CASES = [
    {"id":"v3-o001","category":"卡片重叠歧义","rule_nickname":"周涛","candidates":["周涛","周涛涛"],"good_candidates":["周涛涛"],"why_wrong":"点击落入多卡重叠区绑错卡","card_binding_ok":False,"nickname_attribution_ok":False,"click_ok":True,"suggested_fix":"条件一增加重叠区消歧逻辑"},
    {"id":"v3-o002","category":"卡片重叠歧义","rule_nickname":"吴九","candidates":["吴九","吴九九"],"good_candidates":[],"why_wrong":"重叠区面积相等应标记renxin_system","card_binding_ok":False,"nickname_attribution_ok":False,"click_ok":True,"suggested_fix":"重叠区面积相等时标记renxin_system"},
]

ALL_CASES = X_CASES + Y_CASES + OVERLAP_CASES

async def main():
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    log_dir = Path("C:/data/skill-logs/nickname-selector")
    log_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = log_dir / f"{today}.jsonl"

    # 1. 写 JSONL — 每条都标记 is_failure=True
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for case in ALL_CASES:
            entry = {
                "trace_id": case["id"],
                "timestamp": datetime.now(BEIJING_TZ).isoformat(),
                "is_failure": True,
                "input_summary": {
                    "case_id": case["id"],
                    "category": case["category"],
                },
                "rule_output": {
                    "nickname": case["rule_nickname"],
                    "candidates": case["candidates"],
                    "category": case["category"],
                },
                "ai_validation": {
                    "result": "不合理",
                    "reason": case["why_wrong"],
                },
                "ai_reselection": {
                    "result": case["good_candidates"][0] if case["good_candidates"] else "无",
                },
                "final_output": {
                    "source": "ai",
                    "nickname": case["good_candidates"][0] if case["good_candidates"] else case["rule_nickname"],
                },
                "card_binding_passed": case.get("card_binding_ok", True),
                "nickname_attribution_passed": case.get("nickname_attribution_ok", True),
                "click_coordinate_passed": case.get("click_ok", True),
                "click_offset": case.get("click_offset", None),
                "current_threshold": case.get("current_threshold", None),
                "suggested_fix": case["suggested_fix"],
                "verification_target": case.get("verification_target", None),
                "current_value": case.get("current_value", None),
                "suggested_value": case.get("suggested_value", None),
                "warnings": [],
                "elapsed_ms": 0,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    x_count = len(X_CASES)
    y_count = len(Y_CASES)
    print(f"JSONL written: {jsonl_path}")
    print(f"  X 容差边界: {x_count} cases (X=11~19px)")
    print(f"  Y 容差边界: {y_count} cases (Y=1~3px)")
    print(f"  重叠歧义:   {len(OVERLAP_CASES)} cases")
    print(f"  TOTAL:      {len(ALL_CASES)} cases")
    print()
    print("===== X 偏移值分布 =====")
    from collections import Counter
    x_dist = Counter(c["click_offset"]["x_px"] for c in ALL_CASES if c.get("click_offset"))
    for v in sorted(x_dist):
        y_vals = [c["click_offset"]["y_px"] for c in ALL_CASES if c.get("click_offset") and c["click_offset"]["x_px"] == v]
        print(f"  X={v:2d}px: {x_dist[v]} cases (Y={sorted(set(y_vals))})")
    print()
    print("===== Y 偏移值分布 =====")
    y_dist = Counter(c["click_offset"]["y_px"] for c in ALL_CASES if c.get("click_offset") and c["click_offset"]["y_px"] > 0)
    for v in sorted(y_dist):
        print(f"  Y={v:2d}px: {y_dist[v]} cases")

    # 2. 运行 Evolver
    sys.path.insert(0, "E:/projects/skill_self_evolution/src")
    from skill_self_evolution.config_loader import ConfigVersionManager
    from skill_self_evolution.deepseek import DeepSeekClient
    from skill_self_evolution.config import get_deepseek_config
    from skill_self_evolution.evolver import Evolver
    from ruamel.yaml import YAML

    mgr = ConfigVersionManager()
    current_raw = mgr.load_raw("nickname-selector", "rules_config") or ""
    y = YAML(typ="safe")
    current_cfg = y.load(current_raw) if current_raw else {}
    cc = current_cfg.get("correctness_criteria", {})
    vcs = cc.get("verification_conditions", [])
    print("\n===== 当前 MySQL verification_conditions =====")
    for v in vcs:
        print(f"  {v['id']}: {v['description']}")

    ds = get_deepseek_config()
    client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)
    evolver = Evolver(
        skill_name="nickname-selector",
        skill_base_dir=Path("E:/projects/housekeeping_ai_match/backend/config/services/skill"),
        deepseek=client,
        config_version_manager=mgr,
    )

    print(f"\nRunning Evolver (dry_run=True)...")
    try:
        proposal = await evolver.evolve(date_str=today, dry_run=True)

        result = {
            "failure_count": proposal.failure_count,
            "rules_changes": proposal.rules_changes,
            "prompt_changes": proposal.prompt_changes,
            "has_improvement": bool(proposal.rules_changes or proposal.prompt_changes),
        }
        result_file = Path("E:/projects/skill_self_evolution/data/evolve_v3_result.json")
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nResult saved to: {result_file}")

        print(f"\n===== SUMMARY =====")
        print(f"failure_count: {proposal.failure_count}")
        print(f"has_improvement: {result['has_improvement']}")

        rc = proposal.rules_changes
        if rc:
            cc_changes = rc.get("correctness_criteria", {})
            new_cats = cc_changes.get("bad_categories", [])
            new_conds = cc_changes.get("verification_conditions", [])
            print(f"\n--- correctness_criteria ---")
            if new_cats:
                print(f"bad_categories ({len(new_cats)}):")
                for c in new_cats:
                    print(f"  - {c.get('name','?')}: {c.get('description','')[:60]}")
            else:
                print("bad_categories: (none proposed)")

            if new_conds:
                print(f"verification_conditions ({len(new_conds)}):")
                for c in new_conds:
                    print(f"  - {c.get('id','?')}: {c.get('description','')[:80]}")
            else:
                print("verification_conditions: (none proposed)")  # ← 关键！

            rr = rc.get("rejection_rules", [])
            if rr:
                print(f"\nrejection_rules ({len(rr)}):")
                for r in rr:
                    print(f"  - {r.get('type','?')}: {r.get('description','')[:60]}")
            else:
                print("rejection_rules: (none proposed)")

            nt = rc.get("nickname_thresholds", {})
            if nt:
                print(f"\nnickname_thresholds changes: {json.dumps(nt, ensure_ascii=False)}")
            else:
                print("nickname_thresholds: (none proposed)")

    except Exception as e:
        import traceback
        print(f"FAILED: {e}")
        traceback.print_exc()

    mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
