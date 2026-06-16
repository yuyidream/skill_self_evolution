"""Test scheme 3 AI hallucination: self.config.get in module-level function."""
import subprocess, sys, os
from pathlib import Path

os.environ["DB_PASSWORD"] = "local_root_123"

target = Path("E:/projects/housekeeping_ai_match/scripts/wx_match/processor/nickname_ocr_simple.py")
backup = target.read_text(encoding="utf-8")

old_line = "            click_area = (cx, cy, cx + 2.0, cy + 2.0)"
new_block = """            click_area = (cx, cy, cx + 2.0, cy + 2.0)
            click_w = click_area[2] - click_area[0]
            click_h = click_area[3] - click_area[1]
            click_area_size = click_w * click_h
            min_overlap_area_ratio = self.config.get("card_binding", {}).get("min_overlap_area_ratio", 0.3)
            ambiguity_tie_ratio = self.config.get("card_binding", {}).get("ambiguity_tie_ratio", 0.05)"""

modified = backup.replace(old_line, new_block, 1)
target.write_text(modified, encoding="utf-8")

lines = modified.split("\n")
for i, line in enumerate(lines):
    if "click_area = (cx, cy, cx + 2.0" in line:
        print(f"=== Changed line {i+1} ===")
        for j in range(max(0, i-1), min(len(lines), i+10)):
            print(f"  {j+1}: {lines[j]}")
        break

print()
print("=== pytest ===")
result = subprocess.run(
    [sys.executable, "-m", "pytest",
     "tests/test_wx_match/test_processor_nickname_ocr_simple.py",
     "-x", "-q", "--tb=long", "--no-header"],
    cwd="E:/projects/housekeeping_ai_match/backend",
    capture_output=True, text=True, timeout=120,
)
out = result.stdout
print(out[-3000:] if len(out) > 3000 else out)
if result.stderr:
    print("STDERR:", result.stderr[-1000:])
print(f"Exit: {result.returncode}")

target.write_text(backup, encoding="utf-8")
print("Restored")
