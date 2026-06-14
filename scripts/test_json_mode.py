import asyncio, httpx, json, os

API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-6447e6c91a6f45a0b29373af216ea530")

async def t():
    c = httpx.AsyncClient(timeout=30)
    r = await c.post('https://api.deepseek.com/v1/chat/completions',
        headers={'Content-Type':'application/json','Authorization': f'Bearer {API_KEY}'},
        json={'model':'deepseek-chat','messages':[
            {'role':'system','content':'你是一个JSON输出机器人。你必须只输出一个JSON对象，不要在JSON外添加任何文字、解释或分析。'},
            {'role':'user','content':'北京是中国的首都吗？只输出 {"result": "是"} 或 {"result": "否"}'}
        ],'temperature':0.1,'max_tokens':64})
    print(f'Status: {r.status_code}')
    txt = r.json()['choices'][0]['message']['content']
    print(f'Content: {repr(txt)}')
    try:
        print(f'Parsed: {json.loads(txt)}')
    except Exception as e:
        print(f'Parse error: {e}')

asyncio.run(t())
