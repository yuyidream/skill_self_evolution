import asyncio, json, sys
sys.path.insert(0, r'E:/projects/skill_self_evolution/src')
from skill_self_evolution import SkillExecutor
from pathlib import Path

async def main():
    executor = SkillExecutor(
        skill_base_dir=Path(r'E:/projects/housekeeping_ai_match/backend/config/services/skill'),
        deepseek_api_key='sk-6447e6c91a6f45a0b29373af216ea530',
        deepseek_api_base='https://api.deepseek.com/v1',
        deepseek_model='deepseek-chat',
    )
    result = await executor.run('nickname-selector', {
        'screenshot_id': 'scr_004',
        'metadata_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260611/session_20260611172434_ahxvcp3910405060/metadata.json',
        'debug_session_derived_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260611/session_20260611172434_ahxvcp3910405060/debug_session_derived.json',
    })
    print(f'Source: {result.source}')
    print(f'AI Validated: {result.ai_validated}')
    print(f'AI Reselected: {result.ai_reselected}')
    print(f'Nickname: {result.result.get("nickname","?")}')
    print(f'All: {json.dumps(result.result, ensure_ascii=False, indent=2)}')

asyncio.run(main())
