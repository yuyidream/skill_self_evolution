"""从 debug_session_derived.json 中提取所有规则会选到但实际错误的昵称。

模拟 _rule_extract 的行为：
1. 取每个 band 的第一个 nickname_candidate
2. 过滤 band=None
3. 剩下的是规则输出
4. 检查是否错误
"""
import json, sys, re
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060')

BAD_PATTERNS = [
    (r'群$', '群名误判'),
    (r'^警惕', '安全横幅'),
    (r'^勒索', '安全横幅'),
    (r'^招聘', '招聘信息'),
    (r'禁止发单', '群规公告'),
    (r'^wo$', '拼音碎片'),
    (r'^A{3,}', 'SEO前缀'),
    (r'^\d{11}$', '电话号码'),
    (r'^姓名[：:]', '简历碎片'),
    (r'^性别[：:]', '简历碎片'),
    (r'^年龄[：:]', '简历碎片'),
    (r'^技能[：:]', '简历碎片'),
    (r'^点击查看', '系统消息'),
    (r'对方正在输入', '系统消息'),
    (r'撤回了一条消息', '系统消息'),
    (r'条新消息', '系统消息'),
    (r'^\d{1,2}:\d{2}', '时间戳'),
    (r'^[#*]{2,}', '符号乱码'),
    (r'^$', '空文本'),
    (r'^[）\)]', 'OCR碎片'),
    (r'^：$', '标点碎片'),
    (r'^[A-Za-z]$', '字母碎片'),
    (r'^全$', '单字碎片'),
    (r'^\d{2,4}年', '日期碎片'),
]

def is_bad(text):
    for pat, cat in BAD_PATTERNS:
        if re.search(pat, text):
            return cat
    return ''

def _get_screenshots(debug):
    if isinstance(debug, list):
        return debug
    if isinstance(debug, dict):
        return debug.get('screenshots', [])
    return []

bad_cases = []
all_rule_outputs = 0

for date_dir in sorted(BASE.iterdir()):
    if not date_dir.is_dir():
        continue
    for session_dir in sorted(date_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        debug_path = session_dir / 'debug_session_derived.json'
        meta_path = session_dir / 'metadata.json'
        if not debug_path.exists() or not meta_path.exists():
            continue

        with open(debug_path, encoding='utf-8') as f:
            debug = json.load(f)

        for scr in _get_screenshots(debug):
            if not isinstance(scr, dict):
                continue
            sid = scr.get('screenshot_id', '')
            blocks = scr.get('blocks', [])

            # 按 band 收集 nickname_candidate
            band_candidates = {}
            for blk in blocks:
                if not isinstance(blk, dict):
                    continue
                if blk.get('class') != 'nickname_candidate':
                    continue
                txt = blk.get('text', '').strip()
                if not txt:
                    continue
                band = str(blk.get('band', ''))
                if band not in band_candidates:
                    band_candidates[band] = []
                if txt not in band_candidates[band]:
                    band_candidates[band].append(txt)

            # 模拟 _rule_extract: 过滤 band=None, 取第一个
            for band, candidates in band_candidates.items():
                if band == 'None' or band == '':
                    # band=None 被规则过滤
                    continue
                if not candidates:
                    continue
                rule_pick = candidates[0]
                all_rule_outputs += 1

                bad_cat = is_bad(rule_pick)
                if not bad_cat:
                    continue

                good_candidates = [c for c in candidates[1:] if not is_bad(c)]

                bad_cases.append({
                    'session_name': session_dir.name,
                    'screenshot_id': sid,
                    'band_id': band,
                    'nickname': rule_pick,
                    'candidates': candidates[:10],
                    'good_candidates': good_candidates[:5],
                    'category': bad_cat,
                    'metadata_path': str(meta_path),
                    'debug_session_derived_path': str(debug_path),
                })

print(f'Total rule outputs (band != None): {all_rule_outputs}')
print(f'Bad cases found: {len(bad_cases)}')

cats = Counter(c['category'] for c in bad_cases)
print(f'Categories: {dict(cats)}')

for i, c in enumerate(bad_cases[:40]):
    print(f'  [{i}] {c["session_name"][:40]}/{c["screenshot_id"]} band={c["band_id"]}')
    print(f'       rule={c["nickname"][:60]} ({c["category"]})')
    print(f'       candidates={[x[:40] for x in c["candidates"][:4]]}')
    if c["good_candidates"]:
        print(f'       good={[x[:40] for x in c["good_candidates"][:4]]}')

# Save
out_path = Path(r'E:/projects/skill_self_evolution/data/real_failure_cases.json')
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(bad_cases, f, ensure_ascii=False, indent=2)
print(f'\nSaved {len(bad_cases)} cases to {out_path}')
