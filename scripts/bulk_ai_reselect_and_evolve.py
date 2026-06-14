"""用真实 session 数据批量执行 Skill A → AI 校验 → AI 重选 → 触发自进化。

每个案例都有 metadata_path + debug_session_derived_path + screenshot_id，
走完整的 _rule_extract 文件读取 → AI validate → AI reselect 链路。
"""

import json, os, sys, asyncio, yaml
from pathlib import Path
from datetime import datetime, timezone

SKILL_EVO = Path(r'E:/projects/skill_self_evolution/src')
if str(SKILL_EVO) not in sys.path:
    sys.path.insert(0, str(SKILL_EVO))

from skill_self_evolution.executor import SkillExecutor
from skill_self_evolution.config import get_deepseek_config

SKILL_NAME = "nickname-selector"
CASES_FILE = Path(r'E:/projects/skill_self_evolution/data/real_failure_cases.json')
PROMPT_PATH = Path(r'E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/prompt.yaml')


async def run_one(executor: SkillExecutor, prompt_config: dict, case: dict, index: int) -> dict:
    sid = case['screenshot_id']
    session_name = case['session_name']
    nickname = case.get('nickname', '')
    category = case.get('category', '')

    input_data = {
        "screenshot_id": sid,
        "metadata_path": case['metadata_path'],
        "debug_session_derived_path": case['debug_session_derived_path'],
    }

    trace_id = f"bulk-{index:04d}-{sid}"

    try:
        print(f"[{index}] {session_name}/{sid} ", end='', flush=True)
        output = await executor.run(
            skill_name=SKILL_NAME,
            input_data=input_data,
            prompt_config=prompt_config,
            trace_id=trace_id,
        )

        rule_nick = output.result.get('nickname', '') if isinstance(output.result, dict) else ''
        status = "OVERRIDE" if output.ai_reselected else ("VALIDATED" if output.ai_validated else "RULE_ONLY")
        print(f"→ {status} | {rule_nick[:40]} | wrn={len(output.warnings)}")

        return {
            'index': index,
            'session': session_name,
            'screenshot_id': sid,
            'expected_bad_category': category,
            'original_nickname': nickname,
            'rule_nickname': rule_nick,
            'source': output.source,
            'ai_validated': output.ai_validated,
            'ai_reselected': output.ai_reselected,
            'warnings': output.warnings or [],
            'error': None,
        }
    except Exception as e:
        print(f"→ ERROR: {e}")
        return {
            'index': index,
            'session': session_name,
            'screenshot_id': sid,
            'expected_bad_category': category,
            'original_nickname': nickname,
            'rule_nickname': '',
            'source': 'error',
            'ai_validated': False,
            'ai_reselected': False,
            'warnings': [str(e)],
            'error': str(e),
        }


async def main():
    # 1. 加载案例和 prompt
    with open(CASES_FILE, encoding='utf-8') as f:
        cases = json.load(f)
    with open(PROMPT_PATH, encoding='utf-8') as f:
        prompt_config = yaml.safe_load(f)

    print(f"Cases: {len(cases)}, Prompt loaded: {list(prompt_config.keys())}")

    # 2. 初始化 SkillExecutor
    ds_cfg = get_deepseek_config()
    print(f"DeepSeek: model={ds_cfg.model}, base={ds_cfg.api_base[:50]}...")

    executor = SkillExecutor(
        skill_base_dir=Path(r'E:/projects/housekeeping_ai_match/backend/config/services/skill'),
        deepseek_api_key=ds_cfg.api_key,
        deepseek_api_base=ds_cfg.api_base,
        deepseek_model=ds_cfg.model,
    )

    # 3. 逐条执行（Semaphore 控制并发）
    sem = asyncio.Semaphore(3)

    async def bounded(case, idx):
        async with sem:
            return await run_one(executor, prompt_config, case, idx)

    tasks = [bounded(case, i) for i, case in enumerate(cases)]
    all_results = await asyncio.gather(*tasks)

    # 4. 汇总
    total = len(all_results)
    errors = [r for r in all_results if r['error']]
    validated = [r for r in all_results if r['ai_validated']]
    reselected = [r for r in all_results if r['ai_reselected']]
    skipped = [r for r in all_results if not r['ai_validated'] and not r['error']]

    print(f"\n{'='*60}")
    print(f"批量执行完成: {total} 个案例")
    print(f"  错误: {len(errors)}")
    print(f"  AI 校验过: {len(validated)}")
    print(f"  AI 重选（规则不合理）: {len(reselected)}")
    print(f"  跳过 AI（熔断/降级）: {len(skipped)}")

    if errors:
        print(f"\n错误详情 (前 5):")
        for e in errors[:5]:
            print(f"  [{e['index']}] {e['session'][:30]}/{e['screenshot_id']}: {e['error'][:100]}")

    if reselected:
        print(f"\nAI 重选详情 (前 10):")
        for r in reselected[:10]:
            print(f"  [{r['index']}] {r['original_nickname'][:40]} → 被AI纠正")

    # 保存结果
    summary_path = Path(r'E:/projects/skill_self_evolution/data/bulk_results.json')
    summary = {
        'total': total,
        'errors': len(errors),
        'validated': len(validated),
        'ai_overridden': len(reselected),
        'skipped': len(skipped),
        'results': all_results,
    }
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n汇总: {summary_path}")
    print(f"JSONL 日志: {Path.home() / '.skill_self_evolution' / 'logs' / 'nickname-selector.jsonl'}")


if __name__ == '__main__':
    asyncio.run(main())
