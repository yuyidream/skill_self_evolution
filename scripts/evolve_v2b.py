"""造 v2 测试数据 + 运行 Evolver（修复编码输出到文件）"""
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

NEW_FAILURES = [
    # ===== 场景1：群名片模板 =====
    {"id":"v2-001","category":"群名片模板","rule_nickname":"张经理-家政服务部","candidates":["张经理-家政服务部","张伟"],"good_candidates":["张伟"],"why_wrong":"含破折号+部门名，是WeChat群名片模板格式","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增条件四：昵称不含破折号+机构名组合"},
    {"id":"v2-002","category":"群名片模板","rule_nickname":"李老师-培优教育","candidates":["李老师-培优教育","李芳"],"good_candidates":["李芳"],"why_wrong":"教师+机构群名片","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增群名片模板bad_category"},
    {"id":"v2-003","category":"群名片模板","rule_nickname":"王阿姨-家政服务13800138000","candidates":["王阿姨-家政服务13800138000","王丽"],"good_candidates":["王丽"],"why_wrong":"职业+破折号+服务+手机号","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增条件：昵称不含手机号"},
    {"id":"v2-004","category":"群名片模板","rule_nickname":"刘主管-行政部","candidates":["刘主管-行政部","刘洋"],"good_candidates":["刘洋"],"why_wrong":"职位+破折号+部门","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增bad_category：职位后缀+机构名"},
    {"id":"v2-005","category":"群名片模板","rule_nickname":"陈医生-人民医院","candidates":["陈医生-人民医院","陈静"],"good_candidates":["陈静"],"why_wrong":"职业+破折号+机构","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"正则：破折号后跟2-6字机构名"},

    # ===== 场景2：条件三容差边界 =====
    {"id":"v2-006","category":"条件三容差边界","rule_nickname":"赵敏","candidates":["赵敏","赵敏敏"],"good_candidates":["赵敏敏"],"why_wrong":"X偏移19px在20容差内通过，实际误点相邻卡","card_binding_ok":True,"nickname_attribution_ok":False,"click_ok":True,"click_offset_x":19,"click_offset_y":0,"suggested_fix":"条件三X容差从20px收紧到15px"},
    {"id":"v2-007","category":"条件三容差边界","rule_nickname":"孙七","candidates":["孙七","孙悟空"],"good_candidates":["孙悟空"],"why_wrong":"Y偏移1px，实现bug：Y<>0但未正确拦截","card_binding_ok":True,"nickname_attribution_ok":False,"click_ok":False,"click_offset_x":10,"click_offset_y":1,"suggested_fix":"条件三Y容差从0放宽到2px"},

    # ===== 场景3：卡片重叠区歧义 =====
    {"id":"v2-008","category":"卡片重叠歧义","rule_nickname":"周涛","candidates":["周涛","周涛涛"],"good_candidates":["周涛涛"],"why_wrong":"点击落入多卡重叠区绑错卡","card_binding_ok":False,"nickname_attribution_ok":False,"click_ok":True,"suggested_fix":"条件一增加重叠区消歧：选面积更大的卡"},
    {"id":"v2-009","category":"卡片重叠歧义","rule_nickname":"吴九","candidates":["吴九","吴九九"],"good_candidates":[],"why_wrong":"重叠区面积相等，应标记renxin_system","card_binding_ok":False,"nickname_attribution_ok":False,"click_ok":True,"suggested_fix":"重叠区面积相等时标记renxin_system"},

    # ===== 场景4：纯符号表情昵称 =====
    {"id":"v2-010","category":"纯符号昵称","rule_nickname":"\U0001f60a\u2764\ufe0f\U0001f31f","candidates":["\U0001f60a\u2764\ufe0f\U0001f31f","小明"],"good_candidates":["小明"],"why_wrong":"纯emoji组合，表情轰炸残留","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增bad_category：纯emoji昵称"},
    {"id":"v2-011","category":"纯符号昵称","rule_nickname":"★★★VIP★★★","candidates":["★★★VIP★★★","李雷"],"good_candidates":["李雷"],"why_wrong":"连续特殊符号+英文","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增bad_category：含连续3个以上特殊符号"},

    # ===== 场景5：群名误判 =====
    {"id":"v2-012","category":"群名误判","rule_nickname":"家政阿姨交流群(500)","candidates":["家政阿姨交流群(500)","黄阿姨"],"good_candidates":["黄阿姨"],"why_wrong":"明显的群名被识别为昵称","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"新增bad_category：含'群'字且长度>8"},
    {"id":"v2-013","category":"群名误判","rule_nickname":"北京月嫂接单群②","candidates":["北京月嫂接单群②","郑阿姨"],"good_candidates":["郑阿姨"],"why_wrong":"群名含圈号数字后缀","card_binding_ok":True,"nickname_attribution_ok":True,"click_ok":True,"suggested_fix":"群名模式：含'群'+圈号或含'群'+括号数字"},
]

async def main():
    today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    log_dir = Path("C:/data/skill-logs/nickname-selector")
    log_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = log_dir / f"{today}.jsonl"

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for case in NEW_FAILURES:
            entry = {
                "trace_id": case["id"],
                "timestamp": datetime.now(BEIJING_TZ).isoformat(),
                "is_failure": True,
                "input_summary": {"case_id": case["id"]},
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
                "suggested_fix": case["suggested_fix"],
                "warnings": [],
                "elapsed_ms": 0,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"JSONL written: {jsonl_path} ({len(NEW_FAILURES)} records)")

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
    print(f"\nMySQL rules_config loaded: {len(current_cfg)} top keys")
    cc = current_cfg.get("correctness_criteria", {})
    print(f"  bad_categories: {len(cc.get('bad_categories',[]))}")
    print(f"  verification_conditions: {len(cc.get('verification_conditions',[]))}")

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
        result_file = Path("E:/projects/skill_self_evolution/data/evolve_v2_result.json")
        result = {
            "failure_count": proposal.failure_count,
            "rules_changes": proposal.rules_changes,
            "prompt_changes": proposal.prompt_changes,
            "has_improvement": bool(proposal.rules_changes or proposal.prompt_changes),
        }
        with open(result_file, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nResult saved to: {result_file}")
        print(f"\n===== SUMMARY =====")
        print(f"failure_count: {proposal.failure_count}")
        print(f"has_improvement: {result['has_improvement']}")
        if proposal.rules_changes:
            rc = proposal.rules_changes
            cc = rc.get("correctness_criteria", {})
            new_cats = cc.get("bad_categories", [])
            new_conds = cc.get("verification_conditions", [])
            print(f"\nNew bad_categories ({len(new_cats)}):")
            for c in new_cats:
                print(f"  - {c.get('name','?')}: {len(c.get('patterns',[]))} patterns")
            if new_conds:
                print(f"New verification_conditions ({len(new_conds)}):")
                for c in new_conds:
                    print(f"  - {c.get('id','?')}: {c.get('description','?')[:60]}")
            rr = rc.get("rejection_rules", [])
            if rr:
                print(f"New rejection_rules ({len(rr)}):")
                for r in rr:
                    print(f"  - {r.get('type','?')}: {r.get('description','?')[:60]}")
    except Exception as e:
        import traceback
        print(f"FAILED: {e}")
        traceback.print_exc()

    mgr.close()

if __name__ == "__main__":
    asyncio.run(main())
