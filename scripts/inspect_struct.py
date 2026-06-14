import json

p = r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060/20260611/session_20260611191110_ahxvcp3910405060/debug_session_derived.json'
with open(p, encoding='utf-8') as f:
    d = json.load(f)

s = d['screenshots'][0]
sid = s['screenshot_id']
print(f'Screenshot: {sid}')
spk = s.get('speaker_bands', [])
print(f'speaker_bands type: {type(spk).__name__}, len={len(spk)}')
if spk:
    for i, band in enumerate(spk[:3]):
        print(f'  band[{i}] type={type(band).__name__}, len={len(band)}')
        if isinstance(band, list) and band:
            print(f'    first: {type(band[0]).__name__} = {json.dumps(band[0], ensure_ascii=False)[:100]}')
blocks = s.get('blocks', [])
print(f'blocks count={len(blocks)}')
for b in blocks[:5]:
    cls = b.get('class', '?')
    txt = b.get('text', '')[:60]
    band = b.get('band', '')
    print(f'  class={cls} band={band} text={txt}')
