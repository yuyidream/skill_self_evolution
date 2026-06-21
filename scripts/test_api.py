import asyncio, httpx, os
from dotenv import load_dotenv; load_dotenv()

API_KEY = os.getenv("DEEPSEEK_API_KEY")

async def test():
    async with httpx.AsyncClient(timeout=20, http2=False, trust_env=False) as c:
        r = await c.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "Say hello in 3 words"}], "max_tokens": 20, "temperature": 0.1}
        )
        print(f"Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            print(f"Response: {content}")
        else:
            print(f"Error: {r.text[:300]}")

asyncio.run(test())
