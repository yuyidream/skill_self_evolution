"""从真实 session 数据中提取昵称失败案例，生成可完整链路执行的测试集。

每个案例包含完整的 metadata_path + debug_session_derived_path + screenshot_id，
可以直接通过 run.py 规则提取 → AI 校验 → AI 重选 流程。
"""

import json, os, re, sys
from pathlib import Path

BASE = Path(r'E:/projects/housekeeping_ai_match/build/wx_match_sessions/wechat/ahxvcp3910405060')

# 不合理昵称的识别模式
BAD_PATTERNS = [
    (r'.*群$', '群名误判'),
    (r'.*禁止发单', '群名/公告'),
    (r'^招聘', '招聘信息'),
    (r'^\d{1,2}:\d{2}', '时间误判'),
    (r'^\d{2}:\d{2}:\d{2}', '时间误判'),
    (r'^\d{3,}$', '纯数字'),
    (r'^[#*]{2,}$', '符号乱码'),
    (r'^(对方正在输入|撤回了一条消息)', '系统消息'),
    (r'^\d+条新消息', '系统消息'),
    (r'^警惕不实营销', '微信安全横幅'),
    (r'^勒索病毒紧急预警', '微信安全横幅'),
    (r'^加好友|^群聊$|^举报$|^已收款$|^转账$|^名片$|^语音$|^文件$|^表情$', 'UI标签'),
    (r'^[）\)]?$', 'OCR碎片'),
    (r'^：$', '标点碎片'),
    (r'^[A-Za-z]{1,2}$', '字母碎片'),
    (r'^全$', '单字碎片'),
    (r'^16\）|^\(1[0-9]\)', '数字括号'),
    (r'^新页：', '格式化乱码'),
]

def is_bad_nickname(text: str) -> tuple[bool, str]:
    for pat, cat in BAD_PATTERNS:
        if re.match(pat, text):
            return True, cat
    return False, ''

def main():
    cases = []
    for date_dir in sorted(BASE.glob('202*')):
        for session_dir in sorted(date_dir.glob('session_*')):
            meta_path = session_dir / 'metadata.json'
            debug_path = session_dir / 'debug_session_derived.json'
            if not meta_path.exists() or not debug_path.exists():
                continue

            with open(debug_path, encoding='utf-8') as f:
                debug = json.load(f)
            if not isinstance(debug, dict):
                continue

            for scr in debug.get('screenshots', []):
                sid = scr.get('screenshot_id', '')
                blocks = scr.get('blocks', [])
                # 按 band 收集 candidates
                band_nicks = {}
                for blk in blocks:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get('class') != 'nickname_candidate':
                        continue
                    bd = str(blk.get('band', ''))
                    txt = blk.get('text', '')
                    if bd not in band_nicks:
                        band_nicks[bd] = []
                    if txt:
                        band_nicks[bd].append(txt)

                for band, nicks in band_nicks.items():
                    # 取第一候选作为规则结果
                    rule_pick = nicks[0] if nicks else ''
                    is_bad, category = is_bad_nickname(rule_pick)
                    if is_bad:
                        # 这个 band 中是否有合理的备选昵称？
                        good_candidates = [n for n in nicks if not is_bad_nickname(n)[0]]
                        cases.append({
                            'session_name': session_dir.name,
                            'screenshot_id': sid,
                            'band_id': band,
                            'nickname': rule_pick,
                            'candidates': list(set(nicks))[:10],
                            'good_candidates': good_candidates[:5],
                            'category': category,
                            'metadata_path': str(meta_path),
                            'debug_session_derived_path': str(debug_path),
                        })

    # 按类别分组输出
    from collections import Counter
    cats = Counter(c['category'] for c in cases)
    print(f'Total failure cases: {len(cases)}')
    print(f'Category dist: {dict(cats)}')
    print()

    # 每组最多取 5 个
    per_cat = {}
    for c in cases:
        cat = c['category']
        if cat not in per_cat:
            per_cat[cat] = []
        if len(per_cat[cat]) < 5:
            per_cat[cat].append(c)

    selected = []
    for cat, items in per_cat.items():
        selected.extend(items)
    print(f'Selected {len(selected)} cases (max 5 per category)')

    # 保存 JSON
    out_path = Path(__file__).resolve().parent.parent / 'data' / 'real_failure_cases.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)
    print(f'Saved to {out_path}')

    # 简要打印
    for i, c in enumerate(selected):
        print(f'  [{i}] {c["session_name"]}/{c["screenshot_id"]} band={c["band_id"]}: {c["nickname"][:50]} ({c["category"]})')


if __name__ == '__main__':
    main()
