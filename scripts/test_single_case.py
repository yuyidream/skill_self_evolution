"""单案例完整测试 — 含 prompt.yaml"""
import asyncio, json, sys, yaml
from pathlib import Path

sys.path.insert(0, r'E:/projects/skill_self_evolution/src')

from skill_self_evolution.executor import SkillExecutor
from skill_self_evolution.config import get_deepseek_config

async def test():
    ds = get_deepseek_config()
    print(f'DeepSeek: model={ds.model}, base={ds.api_base}')

    executor = SkillExecutor(
        skill_base_dir=Path(r'E:/projects/housekeeping_ai_match/backend/config/services/skill'),
        deepseek_api_key=ds.api_key,
        deepseek_api_base=ds.api_base,
        deepseek_model=ds.model,
    )

    with open(r'E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/prompt.yaml', encoding='utf-8') as f:
        prompt_config = yaml.safe_load(f)

    # 安全横幅案例
    input_data = {
        'screenshot_id': 'scr_056',
        'metadata_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260606/session_20260606111502_AHXVCP3910405060/metadata.json',
        'debug_session_derived_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260606/session_20260606111502_AHXVCP3910405060/debug_session_derived.json',
    }

    print(f'\nCase: 安全横幅 scr_056')
    output = await executor.run('nickname-selector', input_data, prompt_config=prompt_config, trace_id='test-003')
    print(f'  source        = {output.source}')
    print(f'  ai_validated  = {output.ai_validated}')
    print(f'  ai_reselected = {output.ai_reselected}')
    if hasattr(output, 'result') and isinstance(output.result, dict):
        print(f'  nickname      = {output.result.get("nickname","")[:60]}')
        if output.ai_reselected:
            print(f'  selected      = {output.result.get("selected","")[:60]}')
    print(f'  warnings      = {output.warnings[:3]}')

    print('\nDone!')

asyncio.run(test())
