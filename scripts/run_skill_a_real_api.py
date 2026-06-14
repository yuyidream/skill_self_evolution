"""
Skill A (nickname-selector) 真实 DeepSeek API 执行脚本。

流程：
1. 清除 MySQL 旧数据 → 写入新版 rules_config/prompt
2. 从真实 session 提取昵称案例
3. 用 SkillExecutor + 真实 DeepSeek API 执行 AI 验证/重选
4. 输出结果供用户确认
"""

import asyncio, json, logging, os, sys
from pathlib import Path

_PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJ / "src"))

from skill_self_evolution import SkillExecutor, ConfigVersionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("skill_a_real_api")

API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-6447e6c91a6f45a0b29373af216ea530")
DB_CONFIG = {"host": "127.0.0.1", "port": 3306, "user": "rootyuyi", "password": "YU820124yi", "database": "housekeeping_ai_match_dev"}
SKILL_BASE = Path("E:/projects/housekeeping_ai_match/backend/config/services/skill")
SESSION_BASE = Path("E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060")


def load_yaml(skill_name, fn):
    return (SKILL_BASE / skill_name / fn).read_text(encoding="utf-8")


def extract_cases(limit=20):
    """从 session 提取昵称案例。每个案例含截图内所有 candidate + 上下文。"""
    cases = []
    for date_dir in sorted(SESSION_BASE.glob("202*")):
        for session_dir in sorted(date_dir.glob("session_*")):
            dp = session_dir / "debug_session_derived.json"
            if not dp.exists():
                continue
            with open(dp, encoding="utf-8") as f:
                debug = json.load(f)
            if not isinstance(debug, dict):
                continue
            for scr in debug.get("screenshots", []):
                sid = scr.get("screenshot_id", "")
                blocks = scr.get("blocks", [])
                # 按 band 分组
                band_blocks = {}
                for blk in blocks:
                    if not isinstance(blk, dict):
                        continue
                    band = str(blk.get("band", ""))
                    if band not in band_blocks:
                        band_blocks[band] = {"candidates": [], "bubbles": []}
                    cls = blk.get("class", "")
                    txt = blk.get("text", "")
                    if cls == "nickname_candidate":
                        band_blocks[band]["candidates"].append(txt)
                    elif cls == "bubble_text":
                        band_blocks[band]["bubbles"].append(txt[:60])
                for band, data in band_blocks.items():
                    if data["candidates"]:
                        cases.append({"screenshot_id": sid, "band": band, "candidates": list(set(data["candidates"]))[:10],
                                      "bubbles": data["bubbles"][:3], "session": session_dir.name})
                        if len(cases) >= limit:
                            break
                if len(cases) >= limit:
                    break
            if len(cases) >= limit:
                break
        if len(cases) >= limit:
            break
    return cases


async def main():
    # Step 1: 写入配置到 MySQL
    mgr = ConfigVersionManager(DB_CONFIG)
    mgr.ensure_tables()
    for fn in ["rules_config.yaml", "prompt.yaml"]:
        t = "rules_config" if fn.startswith("rules") else "prompt"
        mgr.save("nickname-selector", t, load_yaml("nickname-selector", fn))
    logger.info("nickname-selector 配置已写入 MySQL")

    # Step 2: 提取案例
    cases = extract_cases(limit=15)
    logger.info("提取 %d 个昵称案例", len(cases))

    # Step 3: 执行
    executor = SkillExecutor(skill_base_dir=SKILL_BASE, deepseek_api_key=API_KEY, deepseek_api_base="https://api.deepseek.com/v1", deepseek_model="deepseek-chat")
    logger.info("SkillExecutor 初始化: model=deepseek-chat, api=api.deepseek.com")

    results = []

    for case in cases:
        logger.info("处理: %s (band=%s)", case["screenshot_id"], case["band"])
        try:
            date_str = case["session"].split("_")[1][:8]  # session_20260611... → 20260611
            session_dir = SESSION_BASE / date_str / case["session"]
            metadata_path = str(session_dir / "metadata.json")
            debug_path = str(session_dir / "debug_session_derived.json")

            if not Path(metadata_path).exists() or not Path(debug_path).exists():
                logger.warning("  跳过 %s (文件缺失)", case["screenshot_id"])
                continue

            output = await executor.run("nickname-selector", {
                "screenshot_id": case["screenshot_id"],
                "metadata_path": metadata_path,
                "debug_session_derived_path": debug_path,
            })
            results.append({
                "screenshot_id": case["screenshot_id"],
                "rule_nickname": output.result.get("rule_nickname", case["candidates"][0]),
                "final_nickname": output.result.get("nickname", output.result.get("value", "")),
                "source": output.source,
                "ai_validated": output.ai_validated,
                "ai_reselected": output.ai_reselected,
                "warnings": output.warnings,
            })
            logger.info("  规则: %s → AI验证=%s 重选=%s → 最终: %s (source=%s)",
                        case["candidates"][0][:40], output.ai_validated, output.ai_reselected,
                        output.result.get("nickname", "?")[:40], output.source)
        except Exception as e:
            logger.error("  失败: %s", e)
            results.append({"screenshot_id": case["screenshot_id"], "error": str(e)})

    # 汇总
    logger.info("\n" + "=" * 60)
    logger.info("Skill A 真实 API 执行汇总 (%d 案例)", len(results))
    logger.info("=" * 60)
    rule_pass = sum(1 for r in results if r.get("source") == "rule" and not r.get("error"))
    ai_selected = sum(1 for r in results if r.get("source") == "ai")
    errors = sum(1 for r in results if r.get("error"))
    logger.info("规则直通: %d | AI重选: %d | 错误: %d", rule_pass, ai_selected, errors)

    for r in results:
        if r.get("source") == "ai":
            logger.info("  🔄 [%s] AI重选: %s → %s", r["screenshot_id"], r.get("rule_nickname", "")[:40], r.get("final_nickname", "")[:40])
        elif r.get("error"):
            logger.info("  ❌ [%s] 错误: %s", r["screenshot_id"], r["error"][:80])
        else:
            logger.info("  ✅ [%s] 规则结果: %s", r["screenshot_id"], r.get("final_nickname", "")[:40])

    logger.info("\n请在以上结果中确认 AI 重选是否合理。确认后可继续 Skill B + C。")
    mgr.close()


asyncio.run(main())
