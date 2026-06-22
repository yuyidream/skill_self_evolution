"""从 session_derived_v1.json 中提取所有最终确定的昵称，检查是否匹配坏模式。

读取管线的最终产物 speaker_nicknames，而非 OCR 第一个候选。
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

bad_cases = []
all_nicknames = 0

for date_dir in sorted(BASE.iterdir()):
    if not date_dir.is_dir():
        continue
    for session_dir in sorted(date_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        derived_path = session_dir / 'session_derived_v1.json'
        if not derived_path.exists():
            continue

        with open(derived_path, encoding='utf-8') as f:
            derived = json.load(f)
        if not isinstance(derived, dict):
            continue

        speaker_nicknames = derived.get('speaker_nicknames', [])
        if not isinstance(speaker_nicknames, list):
            continue

        for sn in speaker_nicknames:
            if not isinstance(sn, dict):
                continue
            nickname = sn.get('text', '').strip()
            if not nickname:
                continue
            all_nicknames += 1

            bad_cat = is_bad(nickname)
            if not bad_cat:
                continue

            bad_cases.append({
                'session_name': session_dir.name,
                'screenshot_id': sn.get('screenshot_id', ''),
                'nickname': nickname,
                'band_id': sn.get('band', ''),
                'category': bad_cat,
            })

print(f'Total final nicknames: {all_nicknames}')
print(f'Bad nicknames found: {len(bad_cases)}')

cats = Counter(c['category'] for c in bad_cases)
print(f'Categories: {dict(cats)}')

for i, c in enumerate(bad_cases[:40]):
    print(f'  [{i}] {c["session_name"][:40]}/{c["screenshot_id"]} band={c["band_id"]}')
    print(f'       nickname={c["nickname"][:60]} ({c["category"]})')

# Save
out_path = Path(r'E:/projects/skill_self_evolution/data/real_failure_cases.json')
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(bad_cases, f, ensure_ascii=False, indent=2)
print(f'\nSaved {len(bad_cases)} cases to {out_path}')
