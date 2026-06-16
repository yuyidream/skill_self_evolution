"""Apply v3 proposal: fix _deep_update list merge, then evolve(dry_run=False) + verify MySQL."""
import json, asyncio, os, sys, io
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["SKILL_LOG_DIR"] = "C:/data/skill-logs"
os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

BEIJING_TZ = timezone(timedelta(hours=8))

# Patch _deep_update: merge list items by id/name
import skill_self_evolution.evolver as _ev

def _merge_list_by_id(base_list: list, updates_list: list) -> None:
    # 空 proposals 不触碰 base_list（"我没有新建议" ≠ "清空所有"）
    if not updates_list:
        return

    key_field = None
    for item in updates_list:
        if isinstance(item, dict):
            if "id" in item:
                key_field = "id"; break
            if "name" in item:
                key_field = "name"; break

    # 无 id/name 字段，直接替换为新列表
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

def _deep_update_v2(base: dict, updates: dict) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update_v2(base[key], value)
        elif isinstance(value, list) and isinstance(base.get(key), list):
            _merge_list_by_id(base[key], value)
        else:
            base[key] = value

_ev._deep_update = _deep_update_v2
print("Patched _deep_update: support list merge by id/name\n")

async def main():
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    sys.path.insert(0, "E:/projects/skill_self_evolution/src")
    from skill_self_evolution.config_loader import ConfigVersionManager
    from skill_self_evolution.deepseek import DeepSeekClient
    from skill_self_evolution.config import get_deepseek_config
    from skill_self_evolution.evolver import Evolver
    from ruamel.yaml import YAML

    mgr = ConfigVersionManager()
    y = YAML(typ="safe")

    # BEFORE snapshot
    before = y.load(mgr.load_raw("nickname-selector", "rules_config") or "")
    vc_b = before.get("correctness_criteria", {}).get("verification_conditions", [])
    bc_b = before.get("correctness_criteria", {}).get("bad_categories", [])
    print("=== BEFORE (MySQL) ===")
    print(f"  verification_conditions: {len(vc_b)}")
    for v in vc_b:
        print(f"    {v.get('id')}: {v.get('description','')[:60]}")
    print(f"  bad_categories: {len(bc_b)}")
    for c in bc_b:
        print(f"    - {c.get('name')}")
    print()

    # APPLY (dry_run=False)
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
    print(f"benchmark_before={proposal.benchmark_before[:2] if proposal.benchmark_before else 'N/A'}")
    print(f"benchmark_after={proposal.benchmark_after[:2] if proposal.benchmark_after else 'N/A'}")

    # AFTER snapshot
    after = y.load(mgr.load_raw("nickname-selector", "rules_config") or "")
    vc_a = after.get("correctness_criteria", {}).get("verification_conditions", [])
    bc_a = after.get("correctness_criteria", {}).get("bad_categories", [])

    print("\n=== AFTER (MySQL) ===")
    print(f"  verification_conditions: {len(vc_a)}")
    for v in vc_a:
        extra = ""
        if 'max_x_px' in v:
            extra = f" max_x_px={v.get('max_x_px')} max_y_px={v.get('max_y_px')}"
        print(f"    {v.get('id')}: {v.get('description','')[:60]}{extra}")
    print(f"  bad_categories: {len(bc_a)}")
    for c in bc_a:
        print(f"    - {c.get('name')}")

    # VERIFY: card_binding & nickname_attribution survived
    ids_a = {v.get('id') for v in vc_a}
    print("\n=== VERIFY ===")
    print(f"  count: {len(vc_b)} -> {len(vc_a)} (expect 3->3)")
    print(f"  card_binding preserved: {'card_binding' in ids_a}")
    print(f"  nickname_attribution preserved: {'nickname_attribution' in ids_a}")
    print(f"  click_coordinate present: {'click_coordinate' in ids_a}")

    # DISK sync check
    disk = Path("E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/rules_config.yaml")
    if disk.exists():
        disk_y = y.load(disk.read_text(encoding="utf-8"))
        vc_d = disk_y.get("correctness_criteria", {}).get("verification_conditions", [])
        cc = [v for v in vc_d if v.get('id') == 'click_coordinate']
        print("\n=== DISK ===")
        if cc:
            print(f"  click_coordinate: X<={cc[0].get('max_x_px','?')}px, Y<={cc[0].get('max_y_px','?')}px")
            print(f"  X: 20 -> {cc[0].get('max_x_px')}")
            print(f"  Y: 0 -> {cc[0].get('max_y_px')}")
        else:
            print("  click_coordinate NOT found!")

    # Version history
    print("\n=== HISTORY (top 3) ===")
    hist = mgr.history("nickname-selector", "rules_config")
    for i, h in enumerate(hist[:3]):
        print(f"  v{h.get('version',i)}: {h.get('updated_at','?')} — {h.get('change_type','?')}")

    mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
