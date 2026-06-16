"""
closed_loop_cursor.py — 用 Cursor Agent 替代自定义 DeepSeek 客户端复现闭环实验。

方案对比：
  closed_loop_v2.py: 639行
    DeepSeek API → extract_code() → replace_code() → subprocess.run(pytest)
    → 手动拼 feedback → for rnd in range(1,4) 重试

  本脚本: ~100行编排 + Cursor Agent（真正的编程智能体）
    注入幻觉 → 输出实验 prompt → Cursor Agent 自动分析/编辑/测试 → 验证

实验步骤：
  python closed_loop_cursor.py inject   # 注入幻觉，跑 E2E 确认破坏
  # 把输出的 prompt 发给 Cursor Chat → Cursor Agent 自动修复
  python closed_loop_cursor.py verify   # 验证修复：E2E + 候选回放
"""

import subprocess
import sys
from pathlib import Path

PROJECT = Path("E:/projects/housekeeping_ai_match")
TARGET = PROJECT / "scripts/wx_match/processor/nickname_ocr_simple.py"

# ═══════════════════════════════════════════════════════════════
# 注入 & 恢复
# ═══════════════════════════════════════════════════════════════

_BUGGY_CODE = """            # BUGGY: 模块级函数中使用了 self，会导致 NameError
            click_area = (cx, cy, cx + 2.0, cy + 2.0)
            matching_cards: list[int] = []
            card_binding = self.config.get("card_binding", {})
            min_overlap = card_binding.get("min_overlap_area_ratio", 0.3)
            ambiguity_tie = card_binding.get("ambiguity_tie_ratio", 0.05)
            for i, raw in enumerate(raws):
                if not raw or len(raw) < 4:
                    continue
                rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                    matching_cards.append(i)
            if len(matching_cards) == 1:
                click_source_card_idx = matching_cards[0]"""

_ORIGINAL_CODE = """            # 构造 2×2 虚拟区域
            click_area = (cx, cy, cx + 2.0, cy + 2.0)
            # 找唯一包含该区域的卡片
            matching_cards: list[int] = []
            for i, raw in enumerate(raws):
                if not raw or len(raw) < 4:
                    continue
                rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                    matching_cards.append(i)
            if len(matching_cards) == 1:
                click_source_card_idx = matching_cards[0]"""


def inject():
    """注入幻觉代码并验证 E2E 被破坏"""
    c = TARGET.read_text("utf-8")
    assert _ORIGINAL_CODE in c, "original code block not found"
    c = c.replace(_ORIGINAL_CODE, _BUGGY_CODE, 1)
    TARGET.write_text(c, "utf-8")
    assert "self.config.get" in TARGET.read_text("utf-8"), "injection failed"

    # 跑 E2E 验证破坏
    print("=" * 60)
    print("Injected hallucination: self.config.get() in module-level function")
    print("Running E2E to verify breakage...")
    print("=" * 60)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_wx_match/test_processor_pipeline_e2e.py",
         "-q", "--tb=line", "--no-header", "-W", "ignore", "-x"],
        cwd=str(PROJECT / "backend"), capture_output=True, text=True, timeout=120
    )
    print(r.stdout[-2000:])
    if r.stderr:
        print(r.stderr[-500:])

    # 输出 Cursor Agent 提示
    print("=" * 60)
    print("EXPERIMENT PROMPT for Cursor Agent:")
    print("=" * 60)
    print("""
@E:\projects\skill_self_evolution\scripts\closed_loop_cursor.py @E:\projects\housekeeping_ai_match\scripts\wx_match\processor\nickname_ocr_simple.py

我做了一个代码开发/测试闭环实验：

1. 我在 nickname_ocr_simple.py 的 _resume_thumb_bindings_and_orphans 函数中注入了一段 BUGGY 代码：
   - 在模块级函数（无 self 参数）中使用了 self.config.get()
   - E2E 测试已确认真实报错: handler_error

2. 请帮我修复这个 BUG：
   - 这是模块级函数，不能使用 self
   - 参数 min_overlap_area_ratio=0.3, ambiguity_tie_ratio=0.05 应硬编码
   - 只能使用变量: cx, cy, raws, click_source_card_idx
   - 修复后跑 python -m pytest tests/test_wx_match/test_processor_pipeline_e2e.py 验证

3. 修复完成后，告诉我结果。

本实验目的：验证 Cursor Agent 能否替代 closed_loop_v2.py 的 DeepSeek 客户端，
成为"编程智能体"角色。参考技能：test-collector-customized-for-renxin。
""")


def verify():
    """验证修复结果：E2E + 候选回放"""
    print("=" * 60)
    print("Verification after Cursor Agent fix")
    print("=" * 60)

    # 确认 self.config.get 已移除
    c = TARGET.read_text("utf-8")
    if "self.config.get" in c:
        print("FAIL: self.config.get still present in file!")
        return False

    # E2E
    print("\n--- E2E Tests ---")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_wx_match/test_processor_pipeline_e2e.py",
         "-q", "--tb=line", "--no-header", "-W", "ignore"],
        cwd=str(PROJECT / "backend"), capture_output=True, text=True, timeout=120
    )
    e2e_ok = "failed" not in r.stdout
    print(r.stdout[-1500:])

    # 候选回放
    print("--- Candidate Replay ---")
    replay_script = r"""
import sys
sys.path.insert(0, r'E:\projects\housekeeping_ai_match\scripts\wx_match')
from unittest.mock import MagicMock
from processor.nickname_ocr_simple import _resume_thumb_bindings_and_orphans, NicknameOcrConfig
s = MagicMock()
s.resume_thumb_bboxes = [[100, 200, 400, 500], [350, 200, 600, 500]]
s.original_resolution = MagicMock(width=720, height=1600)
ctx = MagicMock(); ctx.click_coords = [375, 350]
s.click_context = ctx
cfg = NicknameOcrConfig()
result = _resume_thumb_bindings_and_orphans(
    screenshot=s, blocks=[], classes=[],
    claimed_indices=set(), nicknames=(),
    config=cfg, original_width=720, image_size=(720, 1600)
)
bindings, orphan, excluded = result
print(f'OK|bindings={len(bindings) if bindings else 0}|orphan={orphan}')
"""
    r2 = subprocess.run(
        [sys.executable, "-c", replay_script],
        cwd=str(PROJECT), capture_output=True, text=True, timeout=30
    )
    replay_ok = r2.stdout.strip().startswith("OK|")
    print(r2.stdout.strip())

    print(f"\n{'=' * 60}")
    print(f"E2E: {'PASSED' if e2e_ok else 'FAILED'}")
    print(f"Replay: {'PASSED' if replay_ok else 'FAILED'}")
    print(f"{'=' * 60}")
    return e2e_ok and replay_ok


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "inject":
        inject()
    elif cmd == "verify":
        ok = verify()
        sys.exit(0 if ok else 1)
    else:
        print(__doc__)
        print("\nUsage:")
        print("  python closed_loop_cursor.py inject   # 注入幻觉 + 输出 Cursor Agent 提示")
        print("  python closed_loop_cursor.py verify   # 验证修复结果")
        sys.exit(1)
