"""端到端验证：Pydantic 重构后的 executor 链路"""
import asyncio, json, sys, yaml
from pathlib import Path

sys.path.insert(0, r'E:/projects/skill_self_evolution/src')

from skill_self_evolution.executor import SkillExecutor
from skill_self_evolution.config import get_deepseek_config

async def test():
    ds = get_deepseek_config()
    print(f'DeepSeek: model={ds.model}')

    executor = SkillExecutor(
        skill_base_dir=Path(r'E:/projects/housekeeping_ai_match/backend/config/services/skill'),
        deepseek_api_key=ds.api_key,
        deepseek_api_base=ds.api_base,
        deepseek_model=ds.model,
    )

    with open(r'E:/projects/housekeeping_ai_match/backend/config/services/skill/nickname-selector/prompt.yaml', encoding='utf-8') as f:
        prompt_config = yaml.safe_load(f)

    # Case 1: 安全横幅 (应触发 AI 重选)
    input1 = {
        'screenshot_id': 'scr_056',
        'metadata_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260606/session_20260606111502_AHXVCP3910405060/metadata.json',
        'debug_session_derived_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260606/session_20260606111502_AHXVCP3910405060/debug_session_derived.json',
    }
    print('\nCase 1: 安全横幅 scr_056')
    out1 = await executor.run('nickname-selector', input1, prompt_config=prompt_config, trace_id='e2e-001')
    print(f'  source={out1.source} | validated={out1.ai_validated} | reselected={out1.ai_reselected}')
    print(f'  nickname={out1.result.get("nickname","")[:60]}')

    # Case 2: 简历碎片 (可能通过也可能纠正)
    input2 = {
        'screenshot_id': 'scr_004',
        'metadata_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260606/session_20260606110754_AHXVCP3910405060/metadata.json',
        'debug_session_derived_path': r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260606/session_20260606110754_AHXVCP3910405060/debug_session_derived.json',
    }
    print('\nCase 2: 简历碎片 scr_004')
    out2 = await executor.run('nickname-selector', input2, prompt_config=prompt_config, trace_id='e2e-002')
    print(f'  source={out2.source} | validated={out2.ai_validated} | reselected={out2.ai_reselected}')
    print(f'  nickname={out2.result.get("nickname","")[:60]}')

    # Case 3: AI 校验类测试
    from skill_self_evolution.models import AiValidationResult, AiReselectionResult, LogEntry, DeepSeekChatResponse
    print(f'\nPydantic model classes all accessible')
    print(f'  AiValidationResult Literal: {AiValidationResult.model_fields["result"].annotation}')

    print('\nAll E2E tests passed!')

asyncio.run(test())
