"""造 v4 测试数据 — 聚焦条件一（card_binding）卡片重叠歧义
目标：让 Evolver 提出 card_binding 的消歧规则
- 多卡重叠区绑错卡 → 添加 min_overlap_area_ratio
- 两张卡面积相等 → ambiguity_tie_rule 标记 renxin_system
"""
import json, asyncio, os, sys, io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from random import Random

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["SKILL_LOG_DIR"] = "C:/data/skill-logs"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
BEIJING_TZ = timezone(timedelta(hours=8))
rng = Random(42)

nicknames_male = ["张伟","王强","李磊","刘洋","陈刚","杨军","赵勇","周超","吴建","郑凯"]
nicknames_female = ["王芳","李静","张敏","刘娟","陈丽","杨秀","赵娜","周婷","吴欣","郑妍"]

def make_overlap_unequal(idx, overlap_count, bound_to_wrong=True):
    """多卡重叠但面积不等 — 当前逻辑绑错卡（绑到面积小的/随机第一张）"""
    correct_name = rng.choice(nicknames_male + nicknames_female)
    # 绑错到另一张卡
    wrong_name = rng.choice([n for n in nicknames_male + nicknames_female if n != correct_name])
    # 面积比：正确卡 52-60%，误绑卡 30-45%（面积较小但仍在同区域）
    correct_ratio = round(rng.uniform(0.48, 0.60), 2)
    wrong_ratio = round(rng.uniform(0.28, 0.42), 2)
    remain = round(1.0 - correct_ratio - wrong_ratio, 2)
    return {
        "id": f"v4-u{idx:03d}",
        "category": "卡片重叠·面积不等",
        "rule_nickname": wrong_name,
        "candidates": [wrong_name, correct_name],
        "good_candidates": [correct_name],
        "why_wrong": f"点击区与{overlap_count}张卡重叠，正确卡占{correct_ratio*100:.0f}%面积但被规则绑到{wrong_ratio*100:.0f}%的卡",
        "card_binding_ok": bound_to_wrong,
        "nickname_attribution_ok": False,
        "click_ok": True,
        "overlap_info": {
            "overlap_card_count": overlap_count,
            "bound_card_area_ratio": wrong_ratio,
            "correct_card_area_ratio": correct_ratio,
            "other_remain_ratio": remain if remain > 0 else 0.0,
        },
        "current_logic": "当前无重叠区消歧，area_ratio=0 仍会绑卡",
        "suggested_fix": "添加 min_overlap_area_ratio ≥ 0.30，低于此值不绑卡",
        "verification_target": "card_binding.min_overlap_area_ratio",
        "current_value": 0,
        "suggested_value": 0.30,
    }

def make_overlap_tie(idx, overlap_count):
    """两卡面积相等 或差值 < 5% — 应标记 renxin_system"""
    correct_name = rng.choice(nicknames_male + nicknames_female)
    wrong_name = rng.choice([n for n in nicknames_male + nicknames_female if n != correct_name])
    # 两卡面积几乎相等
    ratio_a = round(rng.uniform(0.45, 0.50), 2)
    ratio_b = round(1.0 - ratio_a, 2)  # 总和约 1.0
    return {
        "id": f"v4-t{idx:03d}",
        "category": "卡片重叠·面积相等",
        "rule_nickname": wrong_name,
        "candidates": [wrong_name, correct_name],
        "good_candidates": [],
        "why_wrong": f"两卡面积接近（{ratio_a*100:.0f}% vs {ratio_b*100:.0f}%），无法确定归属，应标记 renxin_system 而非随机选一张",
        "card_binding_ok": True,
        "nickname_attribution_ok": False,
        "click_ok": True,
        "overlap_info": {
            "overlap_card_count": overlap_count,
            "bound_card_area_ratio": ratio_a,
            "correct_card_area_ratio": ratio_b,
            "area_diff_pct": round(abs(ratio_a - ratio_b) * 100, 1),
        },
        "current_logic": "面积相近时仍绑第一张，无 tie-breaking",
        "suggested_fix": "添加 ambiguity_tie_ratio ≤ 0.05，面积差低于此值标记 renxin_system",
        "verification_target": "card_binding.ambiguity_tie_ratio",
        "current_value": None,
        "suggested_value": 0.05,
    }


# ════════════════════════════════════════════
# 场景 A: 面积不等但绑错 — 20 条
# ════════════════════════════════════════════
UNEQ = [make_overlap_unequal(i, rng.choice([2,3,4])) for i in range(1, 21)]

# ════════════════════════════════════════════
# 场景 B: 面积相等/接近 — 20 条
# ════════════════════════════════════════════
TIE = [make_overlap_tie(i, 2) for i in range(1, 21)]

ALL = UNEQ + TIE

# 统计
from collections import Counter
print(f"Generated {len(ALL)} cases ({len(UNEQ)} unequal + {len(TIE)} tie)")
overlap_counts = Counter(c["overlap_info"]["overlap_card_count"] for c in ALL)
print(f"Overlap counts: {dict(sorted(overlap_counts.items()))}")
area_diffs = [c["overlap_info"].get("area_diff_pct") for c in ALL if c["id"].startswith("v4-t")]
print(f"Tie area_diffs range: {min(area_diffs):.1f}% - {max(area_diffs):.1f}%")
print()

async def main():
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    log_dir = Path("C:/data/skill-logs/nickname-selector")
    log_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = log_dir / f"{today}.jsonl"

    # 1. Write JSONL
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for case in ALL:
            entry = {
                "trace_id": case["id"],
                "timestamp": datetime.now(BEIJING_TZ).isoformat(),
                "is_failure": True,
                "input_summary": {"case_id": case["id"], "category": case["category"]},
                "rule_output": {
                    "nickname": case["rule_nickname"],
                    "candidates": case["candidates"],
                    "category": case["category"],
                },
                "ai_validation": {"result": "不合理", "reason": case["why_wrong"]},
                "ai_reselection": {
                    "result": case["good_candidates"][0] if case["good_candidates"] else "renxin_system",
                },
                "final_output": {
                    "source": "ai",
                    "nickname": case["good_candidates"][0] if case["good_candidates"] else "renxin_system",
                },
                "card_binding_passed": case.get("card_binding_ok", True),
                "nickname_attribution_passed": case.get("nickname_attribution_ok", True),
                "click_coordinate_passed": case.get("click_ok", True),
                "overlap_info": case.get("overlap_info", None),
                "current_logic": case.get("current_logic", ""),
                "suggested_fix": case["suggested_fix"],
                "verification_target": case.get("verification_target", None),
                "current_value": case.get("current_value"),
                "suggested_value": case.get("suggested_value"),
                "warnings": [],
                "elapsed_ms": 0,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"JSONL: {jsonl_path} ({len(ALL)} records)\n")

    # 2. Snapshot & Run Evolver
    sys.path.insert(0, "E:/projects/skill_self_evolution/src")
    from skill_self_evolution.config_loader import ConfigVersionManager
    from skill_self_evolution.deepseek import DeepSeekClient
    from skill_self_evolution.config import get_deepseek_config
    from skill_self_evolution.evolver import Evolver
    from ruamel.yaml import YAML

    # patch list merge
    import skill_self_evolution.evolver as _ev

    def _merge_list_by_id(base_list, updates_list):
        if not updates_list:
            return
        key_field = None
        for item in updates_list:
            if isinstance(item, dict):
                if "id" in item:
                    key_field = "id"; break
                if "name" in item:
                    key_field = "name"; break
        if not key_field:
            base_list.clear(); base_list.extend(updates_list); return
        update_map = {item[key_field]: item for item in updates_list if isinstance(item, dict) and key_field in item}
        for base_item in base_list:
            if isinstance(base_item, dict) and key_field in base_item:
                k = base_item[key_field]
                if k in update_map:
                    _ev._deep_update(base_item, update_map[k])
                    del update_map[k]
        for new_item in update_map.values():
            base_list.append(new_item)

    _orig_dv = _ev._deep_update
    def _deep_update_v2(base, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                _deep_update_v2(base[key], value)
            elif isinstance(value, list) and isinstance(base.get(key), list):
                _merge_list_by_id(base[key], value)
            else:
                base[key] = value
    _ev._deep_update = _deep_update_v2

    mgr = ConfigVersionManager()
    y = YAML(typ="safe")
    before = y.load(mgr.load_raw("nickname-selector", "rules_config") or "")
    vc_b = before.get("correctness_criteria", {}).get("verification_conditions", [])
    bc_b = before.get("correctness_criteria", {}).get("bad_categories", [])

    print("=== BEFORE ===")
    for v in vc_b:
        extras = {k: v[k] for k in v if k not in ("id","description","checkable_in_skill","note")}
        print(f"  {v['id']}: {v['description'][:50]} {extras if extras else ''}")
    print(f"  bad_categories: {len(bc_b)}")
    print()

    ds = get_deepseek_config()
    client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)
    evolver = Evolver(
        skill_name="nickname-selector",
        skill_base_dir=Path("E:/projects/housekeeping_ai_match/backend/config/services/skill"),
        deepseek=client,
        config_version_manager=mgr,
    )

    print("Running Evolver (dry_run=False)...")
    proposal = await evolver.evolve(date_str=today, dry_run=False)

    print(f"\napplied={proposal.applied}  rolled_back={getattr(proposal, 'rolled_back', False)}")

    # AFTER
    after = y.load(mgr.load_raw("nickname-selector", "rules_config") or "")
    vc_a = after.get("correctness_criteria", {}).get("verification_conditions", [])
    bc_a = after.get("correctness_criteria", {}).get("bad_categories", [])

    print(f"\n=== AFTER ===")
    for v in vc_a:
        extras = {k: v[k] for k in v if k not in ("id","description","checkable_in_skill","note")}
        print(f"  {v['id']}: {v['description'][:50]} {extras if extras else ''}")
    print(f"  bad_categories: {len(bc_a)}")

    # VERIFY
    ids_a = {v.get('id') for v in vc_a}
    print(f"\n=== VERIFY ===")
    print(f"  count: {len(vc_b)} -> {len(vc_a)} (expect 3->3)")
    for vid in ['card_binding','nickname_attribution','click_coordinate']:
        print(f"  {vid} present: {vid in ids_a}")

    # DETAIL: card_binding changes
    cb = [v for v in vc_a if v.get('id') == 'card_binding']
    if cb:
        c = cb[0]
        new_params = {k: v for k, v in c.items() if k not in ("id","description","checkable_in_skill","note")}
        print(f"\n  card_binding new params: {new_params if new_params else '(none - only description may have changed)'}")
        print(f"  card_binding desc: {c.get('description','')[:80]}")

    # Save result
    result_file = Path("E:/projects/skill_self_evolution/data/evolve_v4_result.json")
    result = {
        "failure_count": proposal.failure_count,
        "rules_changes": proposal.rules_changes,
        "has_improvement": bool(proposal.rules_changes),
        "applied": proposal.applied,
        "rolled_back": getattr(proposal, 'rolled_back', False),
    }
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nResult saved to: {result_file}")

    # DISK sync check
    disk = Path("E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/rules_config.yaml")
    if disk.exists():
        disk_y = y.load(disk.read_text(encoding="utf-8"))
        vc_d = disk_y.get("correctness_criteria", {}).get("verification_conditions", [])
        cb_d = [v for v in vc_d if v.get('id') == 'card_binding']
        print(f"\n=== DISK card_binding ===")
        if cb_d:
            c = cb_d[0]
            new_params = {k: v for k, v in c.items() if k not in ("id","description","checkable_in_skill","note")}
            print(f"  params: {new_params if new_params else '(none)'}")
            print(f"  desc: {c.get('description','')[:80]}")

    mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
