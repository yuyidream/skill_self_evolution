"""
造新测试数据（v2）— 目标是让 Evolver 对 A→B→C 三条件提出改进，或新增第四条件。
场景：现有三条件全部通过，但昵称实际上不对。
"""
import json, asyncio, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["SKILL_LOG_DIR"] = "C:/data/skill-logs"
os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

BEIJING_TZ = timezone(timedelta(hours=8))

# ── 新失败场景（v2） ──
# 每条案例模拟：A→B→C 全通过，但昵称实际上错了，需要新增判据
NEW_FAILURES = [
    # ===== 场景1：群名片模板 — 三条件全过，但昵称是群名片不是真人名 =====
    {
        "id": "v2-001", "category": "群名片模板",
        "rule_nickname": "张经理-家政服务部",
        "candidates": ["张经理-家政服务部", "张伟"],
        "good_candidates": ["张伟"],
        "why_wrong": "含破折号+部门名，是WeChat群名片模板格式，非个人昵称",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增条件四：昵称不含破折号+机构名组合"
    },
    {
        "id": "v2-002", "category": "群名片模板",
        "rule_nickname": "李老师-培优教育",
        "candidates": ["李老师-培优教育", "李芳"],
        "good_candidates": ["李芳"],
        "why_wrong": "教师+机构群的群名片格式，非昵称",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增群名片模板 bad_category"
    },
    {
        "id": "v2-003", "category": "群名片模板",
        "rule_nickname": "王阿姨-家政服务13800138000",
        "candidates": ["王阿姨-家政服务13800138000", "王丽"],
        "good_candidates": ["王丽"],
        "why_wrong": "职业+破折号+服务+手机号，典型的推广群名片",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增条件：昵称不含手机号"
    },
    {
        "id": "v2-004", "category": "群名片模板",
        "rule_nickname": "刘主管-行政部",
        "candidates": ["刘主管-行政部", "刘洋"],
        "good_candidates": ["刘洋"],
        "why_wrong": "职位+破折号+部门，群名片而非昵称",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增 bad_category：职位后缀（主管/经理/老师）+机构名"
    },
    {
        "id": "v2-005", "category": "群名片模板",
        "rule_nickname": "陈医生-人民医院",
        "candidates": ["陈医生-人民医院", "陈静"],
        "good_candidates": ["陈静"],
        "why_wrong": "职业+破折号+机构，群名片格式",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "正则：破折号后跟2-6字机构名 → 群名片模板"
    },

    # ===== 场景2：三条件容差边界 — 需要收窄阈值 =====
    {
        "id": "v2-006", "category": "条件三容差边界",
        "rule_nickname": "赵敏",
        "candidates": ["赵敏", "赵敏敏"],
        "good_candidates": ["赵敏敏"],
        "why_wrong": "X偏移19px在20容差内通过，但实际点击了相邻卡的边缘",
        "card_binding_ok": True, "nickname_attribution_ok": False, "click_ok": True,
        "click_offset_x": 19, "click_offset_y": 0,
        "suggested_fix": "条件三 X容差从20px收紧到15px"
    },
    {
        "id": "v2-007", "category": "条件三容差边界",
        "rule_nickname": "孙七",
        "candidates": ["孙七", "孙悟空"],
        "good_candidates": ["孙悟空"],
        "why_wrong": "点击Y偏移=1px但条件三要求Y=0，此处Y≠0仍通过了（实现bug）",
        "card_binding_ok": True, "nickname_attribution_ok": False, "click_ok": False,
        "click_offset_x": 10, "click_offset_y": 1,
        "suggested_fix": "条件三 Y容差从0放宽到2px（卡片对齐有±1px误差）"
    },

    # ===== 场景3：卡片重叠区域歧义绑定 =====
    {
        "id": "v2-008", "category": "卡片重叠歧义",
        "rule_nickname": "周涛",
        "candidates": ["周涛", "周涛涛"],
        "good_candidates": ["周涛涛"],
        "why_wrong": "点击坐标落在两张卡重叠区，card_binding匹配了错误卡片",
        "card_binding_ok": False, "nickname_attribution_ok": False, "click_ok": True,
        "suggested_fix": "条件一增加重叠区消歧：当点击落入多卡重叠区时选面积更大的卡"
    },
    {
        "id": "v2-009", "category": "卡片重叠歧义",
        "rule_nickname": "吴九",
        "candidates": ["吴九", "吴九九"],
        "good_candidates": [],
        "why_wrong": "重叠区点击，两张卡面积相等，应标记为不确定而非选第一张",
        "card_binding_ok": False, "nickname_attribution_ok": False, "click_ok": True,
        "suggested_fix": "重叠区面积相等时标记为renxin_system（无法确定）"
    },

    # ===== 场景4：新坏类别 — 纯表情/符号昵称 =====
    {
        "id": "v2-010", "category": "纯符号昵称",
        "rule_nickname": "😊❤️🌟",
        "candidates": ["😊❤️🌟", "小明"],
        "good_candidates": ["小明"],
        "why_wrong": "纯emoji组合，可能是表情轰炸残留而非昵称",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增 bad_category：纯emoji/符号昵称"
    },
    {
        "id": "v2-011", "category": "纯符号昵称",
        "rule_nickname": "★★★VIP★★★",
        "candidates": ["★★★VIP★★★", "李雷"],
        "good_candidates": ["李雷"],
        "why_wrong": "特殊符号+英文，非正常微信昵称格式",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增 bad_category：含连续3个以上特殊符号"
    },

    # ===== 场景5：群名误判为昵称 =====
    {
        "id": "v2-012", "category": "群名误判",
        "rule_nickname": "家政阿姨交流群(500)",
        "candidates": ["家政阿姨交流群(500)", "黄阿姨"],
        "good_candidates": ["黄阿姨"],
        "why_wrong": "明显的群名格式，被识别为昵称",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "新增 bad_category：含'群'字且长度>8的文本 → 群名非昵称"
    },
    {
        "id": "v2-013", "category": "群名误判",
        "rule_nickname": "北京月嫂接单群②",
        "candidates": ["北京月嫂接单群②", "郑阿姨"],
        "good_candidates": ["郑阿姨"],
        "why_wrong": "群名格式含圈号数字后缀",
        "card_binding_ok": True, "nickname_attribution_ok": True, "click_ok": True,
        "suggested_fix": "群名模式：含'群'+圈号或含'群'+括号数字"
    },
]

async def main():
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    log_dir = Path("C:/data/skill-logs/nickname-selector")
    log_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = log_dir / f"{today}.jsonl"

    # 1. 写 JSONL
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for case in NEW_FAILURES:
            entry = {
                "trace_id": case["id"],
                "timestamp": datetime.now(BEIJING_TZ).isoformat(),
                "is_failure": True,
                "input_summary": {"screenshot_id": case["id"]},
                "rule_output": {
                    "nickname": case["rule_nickname"],
                    "candidates": case["candidates"],
                    "category": case["category"],
                },
                "ai_validation": {
                    "result": "\u4e0d\u5408\u7406",
                    "reason": case["why_wrong"],
                },
                "ai_reselection": {
                    "result": case["good_candidates"][0] if case["good_candidates"] else "\u65e0",
                },
                "final_output": {
                    "source": "ai",
                    "nickname": case["good_candidates"][0] if case["good_candidates"] else case["rule_nickname"],
                },
                "card_binding_passed": case.get("card_binding_ok", True),
                "nickname_attribution_passed": case.get("nickname_attribution_ok", True),
                "click_coordinate_passed": case.get("click_ok", True),
                "suggested_fix": case["suggested_fix"],
                "warnings": [],
                "elapsed_ms": 0,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"JSONL written: {jsonl_path} ({len(NEW_FAILURES)} records)")

    # 2. 查看当前 MySQL 配置
    import sys
    sys.path.insert(0, "E:/projects/skill_self_evolution/src")
    from skill_self_evolution.config_loader import ConfigVersionManager
    from ruamel.yaml import YAML

    mgr = ConfigVersionManager()
    current_raw = mgr.load_raw("nickname-selector", "rules_config") or ""
    y = YAML(typ="safe")
    current_cfg = y.load(current_raw) if current_raw else {}
    print(f"\nMySQL rules_config v{mgr.load_raw('nickname-selector', 'rules_config') and 'loaded'}")
    cc = current_cfg.get("correctness_criteria", {})
    cats = cc.get("bad_categories", [])
    conds = cc.get("verification_conditions", [])
    print(f"  bad_categories: {len(cats)} — {[c.get('name','') for c in cats]}")
    print(f"  verification_conditions: {len(conds)} — {[c.get('id','') for c in conds]}")

    # 3. 运行 Evolver
    from skill_self_evolution.deepseek import DeepSeekClient
    from skill_self_evolution.config import get_deepseek_config
    from skill_self_evolution.evolver import Evolver

    ds = get_deepseek_config()
    client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)

    evolver = Evolver(
        skill_name="nickname-selector",
        skill_base_dir=Path("E:/projects/housekeeping_ai_match/backend/config/services/skill"),
        deepseek=client,
        config_version_manager=mgr,
    )

    print("\nRunning Evolver...")
    try:
        proposal = await evolver.evolve(date_str=today, dry_run=True)
        print(f"\n===== RESULT =====")
        print(f"failure_count: {proposal.failure_count}")
        if proposal.rules_changes:
            rc = proposal.rules_changes
            print(f"\ncorrectness_criteria changes:")
            cc_changes = rc.get("correctness_criteria", {})
            if cc_changes:
                new_cats = cc_changes.get("bad_categories", [])
                print(f"  bad_categories: {len(new_cats)} entries")
                for c in new_cats:
                    print(f"    - {c.get('name','?')}: {len(c.get('patterns',[]))} patterns")
                new_conds = cc_changes.get("verification_conditions", [])
                if new_conds:
                    print(f"  verification_conditions: {len(new_conds)} entries")
                    for c in new_conds:
                        print(f"    - {c.get('id','?')}: {c.get('description','?')}")
            rr_changes = rc.get("rejection_rules", [])
            if rr_changes:
                print(f"\nrejection_rules changes: {len(rr_changes)} rules")
                for r in rr_changes:
                    print(f"    - {r.get('type','?')}: {r.get('description','?')[:40]}")
        print(f"\nfull rules_changes:")
        print(json.dumps(proposal.rules_changes, ensure_ascii=False, indent=2)[:4000])
        print(f"\nhas_improvement: {bool(proposal.rules_changes or proposal.prompt_changes)}")
    except Exception as e:
        import traceback
        print(f"FAILED: {e}")
        traceback.print_exc()

    mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
