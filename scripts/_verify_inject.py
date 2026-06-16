"""验证 hallucination 注入 + candidate replay"""
import os, sys, subprocess

os.environ['DB_PASSWORD'] = 'local_root_123'

target = r'E:\projects\housekeeping_ai_match\scripts\wx_match\processor\nickname_ocr_simple.py'
orig = open(target, 'r', encoding='utf-8').read()
old = '            click_area = (cx, cy, cx + 2.0, cy + 2.0)'
print(f'old string found: {old in orig}')

c = orig
new = (old + '\n'
    + '            click_w = click_area[2] - click_area[0]\n'
    + '            click_h = click_area[3] - click_area[1]\n'
    + '            click_area_size = click_w * click_h\n'
    + '            min_overlap_area_ratio = self.config.get("card_binding", {}).get("min_overlap_area_ratio", 0.3)\n'
    + '            ambiguity_tie_ratio = self.config.get("card_binding", {}).get("ambiguity_tie_ratio", 0.05)')
open(target, 'w', encoding='utf-8').write(c.replace(old, new, 1))
print('hallucination injected')

# replay
script = '''
import sys, os
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match")
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match\\backend")
sys.path.insert(0, r"E:\\projects\\housekeeping_ai_match\\scripts\\wx_match")
os.environ["DB_PASSWORD"] = "local_root_123"
from unittest.mock import MagicMock
from scripts.wx_match.processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig
s = MagicMock()
s.resume_thumb_bboxes = [[100, 200, 400, 500], [350, 200, 600, 500]]
s.original_resolution = MagicMock(width=720, height=1600)
ctx = MagicMock(); ctx.click_coords = [375, 350]
s.click_context = ctx
cfg = NicknameOcrConfig()
try:
    result = _resume_thumb_bindings_and_orphans(
        screenshot=s, blocks=[], classes=[],
        claimed_indices=set(), nicknames=(),
        config=cfg, original_width=720, image_size=(720, 1600)
    )
    bindings, orphan, excluded = result
    print(f"OK|bindings={len(bindings) if bindings else 0}|orphan={orphan}")
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    print(f"ERROR|{type(e).__name__}: {e}")
    print(tb[-500:])
'''
r = subprocess.run([sys.executable, '-c', script],
    cwd=r'E:\projects\housekeeping_ai_match\backend',
    capture_output=True, text=True, encoding='utf-8', timeout=30)
print('replay:', r.stdout.strip()[-800:])

# restore
open(target, 'w', encoding='utf-8').write(orig)
print('restored')
