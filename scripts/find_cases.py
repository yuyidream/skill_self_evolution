import json, os

base = r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060'
count = 0
for date_dir in sorted(os.listdir(base)):
    dp = os.path.join(base, date_dir)
    if not os.path.isdir(dp):
        continue
    for sd in sorted(os.listdir(dp)):
        f = os.path.join(dp, sd, 'debug_session_derived.json')
        if not os.path.exists(f):
            continue
        with open(f, encoding='utf-8') as fh:
            d = json.load(fh)
        if not isinstance(d, dict):
            continue
        for s in d.get('screenshots', []):
            blocks = s.get('blocks', [])
            nc = [b for b in blocks if isinstance(b, dict) and b.get('class') == 'nickname_candidate']
            if nc:
                sid = s.get('screenshot_id', '?')
                print(f'{date_dir}/{sd} -> {sid}: {len(nc)} nickname_candidates')
                for n in nc[:5]:
                    print(f'  band={n.get("band")} text={n.get("text","")[:80]}')
                count += 1
                if count >= 8:
                    break
        if count >= 8:
            break
    if count >= 8:
        break
