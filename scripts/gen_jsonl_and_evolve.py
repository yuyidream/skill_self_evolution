"""从 bulk_results.json 生成 JSONL 日志，然后触发 Evolver 自进化。"""
import json, sys, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, r'E:/projects/skill_self_evolution/src')

from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.config import get_deepseek_config

async def main():
    # 1. 从 bulk_results.json 生成 JSONL
    results_path = Path(r'E:/projects/skill_self_evolution/data/bulk_results.json')
    with open(results_path, encoding='utf-8') as f:
        data = json.load(f)

    BEIJING_TZ = timezone(timedelta(hours=8))
    today = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d')
    log_dir = Path(r'C:\data\skill-logs\nickname-selector')
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f'{today}.jsonl'

    failure_count = 0
    with open(log_path, 'w', encoding='utf-8') as f:
        for r in data['results']:
            is_failure = r['ai_reselected']  # AI 重选说明原规则不合理
            if is_failure:
                failure_count += 1
            entry = {
                'trace_id': f"bulk-{r['index']:04d}",
                'timestamp': datetime.now(BEIJING_TZ).isoformat(),
                'is_failure': is_failure,
                'input_summary': {
                    'screenshot_id': r['screenshot_id'],
                    'session': r['session'],
                },
                'rule_output': {
                    'nickname': r['original_nickname'],
                    'expected_category': r['expected_bad_category'],
                },
                'ai_validation': {
                    'result': '不合理' if is_failure else '合理',
                },
                'ai_reselection': {
                    'result': r['rule_nickname'] if is_failure else None,
                },
                'final_output': {
                    'source': r['source'],
                    'nickname': r['rule_nickname'],
                },
                'warnings': r.get('warnings', []),
                'elapsed_ms': 0,
            }
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    print(f'JSONL 日志已生成: {log_path}')
    print(f'  总记录: {len(data["results"])}')
    print(f'  is_failure=true: {failure_count}')

    # 2. 触发 Evolver
    from skill_self_evolution.evolver import Evolver
    from skill_self_evolution.loader import SkillLoader
    from skill_self_evolution.config import get_deepseek_config

    ds = get_deepseek_config()
    client = DeepSeekClient(
        api_key=ds.api_key,
        api_base=ds.api_base,
        model=ds.model,
    )

    evolver = Evolver(
        skill_name='nickname-selector',
        skill_base_dir=Path(r'E:/projects/housekeeping_ai_match/backend/config/services/skill'),
        deepseek=client,
    )

    print(f'\n执行 Evolver.evolve()...')
    try:
        proposal = await evolver.evolve(date_str=today, dry_run=True)
        print(f'进化提案:')
        print(f'  失败样本数: {proposal.failure_count}')
        print(f'  规则变更: {json.dumps(proposal.rules_changes, ensure_ascii=False, indent=2)[:500]}')
        print(f'  Prompt变更: {json.dumps(proposal.prompt_changes, ensure_ascii=False, indent=2)[:500]}')
        print(f'  已应用: {proposal.applied}')
        print(f'  AI 分析: {proposal.analysis_raw[:500]}')
    except Exception as e:
        import traceback
        print(f'进化失败: {e}')
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
