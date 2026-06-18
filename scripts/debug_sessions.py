import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

pairs = [
    ('session_20260606110754_AHXVCP3910405060', 'scr_004'),
    ('session_20260606111502_AHXVCP3910405060', 'scr_056'),
]
BASE = Path(r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060')

for sn, sid in pairs:
    for dd in BASE.glob(f'202*/{sn}'):
        dp = dd / 'debug_session_derived.json'
        if not dp.exists():
            continue
        with open(dp, encoding='utf-8') as f:
            debug = json.load(f)
        print(f'\n{sn}: type={type(debug).__name__}')

        if isinstance(debug, list):
            screenshots = debug
        elif isinstance(debug, dict):
            screenshots = debug.get('screenshots', [])
        else:
            screenshots = []

        found = False
        for scr in screenshots:
            if not isinstance(scr, dict):
                continue
            if scr.get('screenshot_id') == sid:
                found = True
                blocks = scr.get('blocks', [])
                nc = [b.get('text','') for b in blocks if isinstance(b, dict) and b.get('class')=='nickname_candidate']
                print(f'  FOUND {sid}: {len(nc)} nickname_candidates, {len(blocks)} blocks')
                band_map = {}
                for b in blocks:
                    if not isinstance(b, dict): continue
                    if b.get('class') == 'nickname_candidate':
                        bd = str(b.get('band', ''))
                        if bd not in band_map:
                            band_map[bd] = []
                        band_map[bd].append(b.get('text','')[:40])
                for bd, texts in band_map.items():
                    print(f'    band={bd}: {texts[:3]}')
                break
        if not found:
            ids = [s.get('screenshot_id','?') for s in screenshots if isinstance(s, dict)]
            print(f'  NOT FOUND {sid}, available first 10: {ids[:10]}')
