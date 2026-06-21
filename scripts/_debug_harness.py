import asyncio, os, sys, json
sys.path.insert(0, 'src')
from skill_self_evolution.harness.opencode.executor import execute_query

async def debug():
    options = {
        'provider_id': 'deepseek',
        'model_id': 'deepseek-chat',
        'mode': 'build',
        'cwd': os.getcwd(),
        'system': 'You are a Python expert. Reply with ONLY a python code block.',
    }
    result = await execute_query(options, 'write a function that adds two numbers. output ```python``` block only.')
    payload = result[0]
    print('keys:', list(payload.keys()))
    msgs = payload.get('messages', [])
    print('msg count:', len(msgs))
    for i, m in enumerate(msgs):
        info = m.get('info', {})
        print(f"msg[{i}] role={info.get('role','?')} info_keys={list(info.keys())[:15]}")
        if info.get('error'):
            print(f"  ERROR: {info['error']}")
        parts = m.get('parts', [])
        print(f"  parts count: {len(parts)}")
        for j, p in enumerate(parts):
            ptype = p.get('type', '?')
            if ptype == 'text':
                print(f"  part[{j}] text: {p.get('text','')[:500]}")
            else:
                print(f"  part[{j}] type={ptype} keys={list(p.keys())[:5]}")

asyncio.run(debug())
