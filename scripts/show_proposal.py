import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

proposal_path = Path(r'C:\data\skill-logs\nickname-selector\proposals\2026-06-14_proposal.json')
if proposal_path.exists():
    with open(proposal_path, encoding='utf-8') as f:
        proposal = json.load(f)
    print('=== Evolver 自进化提案 ===\n')
    print(f'失败样本数: {proposal.get("failure_count", "?")}')
    print(f'已应用: {proposal.get("applied", False)}')
    print()
    if proposal.get('rules_changes'):
        print('--- 规则变更建议 ---')
        print(json.dumps(proposal['rules_changes'], ensure_ascii=False, indent=2))
        print()
    if proposal.get('prompt_changes'):
        print('--- Prompt 变更建议 ---')
        print(json.dumps(proposal['prompt_changes'], ensure_ascii=False, indent=2)[:1000])
        print()
    if proposal.get('analysis_raw'):
        print('--- AI 分析 ---')
        print(proposal['analysis_raw'][:500])
else:
    print(f'Proposal not found at {proposal_path}')
    # Search
    base = Path(r'C:\data\skill-logs\nickname-selector')
    for f in base.rglob('*'):
        print(f'  {f}')
