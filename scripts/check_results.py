import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

# 1. JSONL stats
jsonl = Path.home() / '.skill_self_evolution' / 'logs' / 'nickname-selector.jsonl'
if jsonl.exists():
    lines = jsonl.read_text(encoding='utf-8').strip().split('\n')
    print(f'JSONL 日志: {len(lines)} 条记录')
    failures = 0
    sources = {}
    for line in lines:
        try:
            d = json.loads(line)
            if d.get('is_failure'):
                failures += 1
            src = d.get('final_output', {}).get('source', '?')
            sources[src] = sources.get(src, 0) + 1
        except:
            pass
    print(f'  is_failure=true: {failures}')
    print(f'  source 分布: {sources}')
else:
    print('JSONL 日志不存在')

# 2. Bulk results
results_path = Path(r'E:/projects/skill_self_evolution/data/bulk_results.json')
with open(results_path, encoding='utf-8') as f:
    data = json.load(f)
print(f'\nBulk Results:')
print(f'  total={data["total"]}')
print(f'  errors={data["errors"]}')
print(f'  validated={data["validated"]}')
print(f'  ai_overridden={data["ai_overridden"]}')
print(f'  skipped={data["skipped"]}')

# 统计各类别
cats = {}
for r in data['results']:
    cat = r['expected_bad_category']
    if cat not in cats:
        cats[cat] = {'total': 0, 'overridden': 0}
    cats[cat]['total'] += 1
    if r['ai_reselected']:
        cats[cat]['overridden'] += 1

print(f'\n各类别 AI 纠正率:')
for cat, stats in sorted(cats.items()):
    pct = stats['overridden'] / stats['total'] * 100
    print(f'  {cat}: {stats["overridden"]}/{stats["total"]} = {pct:.0f}%')

# 3. AI 未纠正的案例（可能漏网）
print(f'\nAI 未纠正的案例（rule=VALIDATED 但实际应为不合理）:')
not_overridden = [r for r in data['results'] if not r['ai_reselected'] and r['expected_bad_category']]
for r in not_overridden[:10]:
    print(f'  [{r["index"]}] {r["session"][:30]}/{r["screenshot_id"]}: {r["original_nickname"][:40]} ({r["expected_bad_category"]})')
