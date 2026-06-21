"""调试 round 1 执行链路"""
import sys, os
sys.path.insert(0, r'E:\projects\skill_self_evolution\src')

from scripts.closed_loop_opencode_v2 import (
    restore, apply_hallucination, replace_code, run_e2e, run_candidate_replay,
    ask_via_opencode, extract_code, SYSTEM_COMBINED, TARGET, orig_content
)
import asyncio

async def debug_round1():
    # Step 1: restore + inject
    restore()
    ok = apply_hallucination()
    print(f'1. hallucination injected: {ok}')

    # Step 2: show injected code
    lines = TARGET.read_text('utf-8').split('\n')
    for i, l in enumerate(lines[948:962], start=949):
        print(f'  {i}: {l}')

    # Step 3: ask AI
    prompt = """Fix BUGGY code in _resume_thumb_bindings_and_orphans (NO self).
Variables: cx, cy, raws, click_source_card_idx.
Params: min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05 (hardcode).

Original code:
click_area = (cx, cy, cx + 2.0, cy + 2.0)
matching_cards: list[int] = []
for i, raw in enumerate(raws):
    if not raw or len(raw) < 4: continue
    rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
    if rx1 <= cx <= rx2 and ry1 <= cy <= ry2: matching_cards.append(i)
if len(matching_cards) == 1: click_source_card_idx = matching_cards[0]

Output ```python``` block only."""

    ai = await ask_via_opencode(SYSTEM_COMBINED, prompt)
    code = extract_code(ai)
    print(f'3. AI: {len(ai)} chars, has_code={code is not None}')
    if code:
        print(f'   code:\n{code[:300]}')

    if not code or len(code.strip()) < 50:
        print('   NO VALID CODE')
        restore()
        return

    # Step 4: apply fix
    restore()
    apply_hallucination()
    replaced = replace_code(code)
    print(f'4. replace_code: {replaced}')

    if not replaced:
        print('   REPLACE FAILED')
        restore()
        return

    # Step 5: show replaced code
    lines = TARGET.read_text('utf-8').split('\n')
    for i, l in enumerate(lines[948:970], start=949):
        print(f'  {i}: {l}')

    # Step 6: E2E
    e2e_ok, e2e_out, e2e_err = run_e2e()
    print(f'5. E2E: {"PASSED" if e2e_ok else "FAILED"}')
    if not e2e_ok:
        for l in e2e_out.split('\n')[-5:]:
            if l.strip(): print(f'   {l[:120]}')

    # Step 7: Replay
    replay_ok, replay_msg = run_candidate_replay()
    print(f'6. Replay: {"PASSED" if replay_ok else "FAILED"}')
    print(f'   {replay_msg[:300]}')

    restore()
    print('7. restored')

asyncio.run(debug_round1())
