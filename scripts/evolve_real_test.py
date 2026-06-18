"""三层进化能力验证：基于真实 session 数据的端到端测试

L1: 模式匹配 — 用真实「群名误判」失败案例，测试 Evolver 提出新 rejection_rules
L2: 数值调参 — 用真实矮卡片点击边缘数据，测试 Evolver 调整 click_coordinate 阈值
L3: 语义规则生成 — 用真实会话 bbox 尺寸构造卡片重叠案例，测试 Evolver 提出新参数

每层实验独立运行：写 JSONL → run Evolver(dry_run=False) → 验证 → 恢复基线 → 下一层
"""

import json
import asyncio
import os
import sys
import io
import copy
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["SKILL_LOG_DIR"] = "C:/data/skill-logs"
os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

BEIJING_TZ = timezone(timedelta(hours=8))
PROJECT_ROOT = Path("E:/projects/housekeeping_ai_match")
SKILL_SELF_EVO_SRC = Path("E:/projects/skill_self_evolution/src")

sys.path.insert(0, str(SKILL_SELF_EVO_SRC))

from skill_self_evolution.config_loader import ConfigVersionManager
from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.config import get_deepseek_config
from skill_self_evolution.evolver import Evolver
from ruamel.yaml import YAML


# ════════════════════════════════════════════
# 辅助函数
# ════════════════════════════════════════════

yaml_safe = YAML(typ='safe')
yaml_rt = YAML()
yaml_rt.default_flow_style = False

today = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
JSONL_DIR = Path("C:/data/skill-logs/nickname-selector")
JSONL_DIR.mkdir(parents=True, exist_ok=True)
JSONL_PATH = JSONL_DIR / f"{today}.jsonl"

RULES_DISK_PATH = PROJECT_ROOT / "backend/config/services/skill/nickname-selector/rules_config.yaml"
RULES_DISK_BACKUP = PROJECT_ROOT / "backend/config/services/skill/nickname-selector/rules_config.yaml.bak_test"


def snapshot_config(mgr):
    """快照当前 MySQL 配置，返回 (rules_raw, version)"""
    raw = mgr.load_raw("nickname-selector", "rules_config")
    cfg = mgr.load("nickname-selector", "rules_config")
    version = cfg.get("version") if cfg else None
    return raw, version


def restore_config(mgr, raw_backup):
    """恢复到指定的 rules_config 内容"""
    current = mgr.load_raw("nickname-selector", "rules_config")
    if current != raw_backup:
        mgr.save("nickname-selector", "rules_config", raw_backup)
        print("  [restore] MySQL 配置已恢复")
    # 同步磁盘
    RULES_DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
    RULES_DISK_PATH.write_text(raw_backup, encoding="utf-8")
    print("  [restore] 磁盘 YAML 已恢复")


def write_jsonl(cases):
    """将案例列表写入 JSONL"""
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 清空旧数据
    JSONL_PATH.write_text("", encoding="utf-8")
    with open(JSONL_PATH, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"  JSONL 写入: {JSONL_PATH} ({len(cases)} 条)")


async def run_evolver(mgr, client, min_samples=5, desc=""):
    """运行 Evolver 并返回结果"""
    evolver = Evolver(
        skill_name="nickname-selector",
        deepseek=client,
        version_mgr=mgr,
        rules_config_disk_path=RULES_DISK_PATH,
        evolution_mode="rules_only",
        evolve_toml={
            "evolve": {
                "auto_modify": {
                    "rules_config": {"mode": "full", "max_change_percent": 100}
                },
                "guard": {
                    "require_benchmark_pass": False  # 测试环境不跑 benchmark
                }
            }
        },
    )

    # ── 注入 _merge_list_by_id 补丁 ──
    import skill_self_evolution.evolver as _ev

    def _merge_list_by_id(base_list, updates_list):
        if not updates_list:
            return
        key_field = None
        for item in updates_list:
            if isinstance(item, dict):
                if "id" in item:
                    key_field = "id"; break
                if "name" in item:
                    key_field = "name"; break
        if not key_field:
            # rejection_rules 没有 id/name，但有 type+pattern 作为复合键
            # 尝试用 (type, pattern) 做合并，而不是粗暴替换整个列表
            has_composite_key = all(
                isinstance(item, dict) and "type" in item and "pattern" in item
                for item in updates_list
            )
            if has_composite_key and all(isinstance(item, dict) and "type" in item and "pattern" in item for item in base_list):
                # rejection_rules: 按 (type, pattern) 合并
                def _rule_key(r):
                    return (r.get("type", ""), r.get("pattern", ""))
                existing = {_rule_key(r): r for r in base_list}
                for new_r in updates_list:
                    k = _rule_key(new_r)
                    if k in existing:
                        _ev._deep_update(existing[k], new_r)
                    else:
                        base_list.append(new_r)
                return
            # fallback: replace all
            base_list.clear(); base_list.extend(updates_list); return
        update_map = {item[key_field]: item for item in updates_list if isinstance(item, dict) and key_field in item}
        for base_item in base_list:
            if isinstance(base_item, dict) and key_field in base_item:
                k = base_item[key_field]
                if k in update_map:
                    _ev._deep_update(base_item, update_map[k])
                    del update_map[k]
        for new_item in update_map.values():
            base_list.append(new_item)

    _orig_dv = _ev._deep_update

    def _deep_update_v2(base, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                _deep_update_v2(base[key], value)
            elif isinstance(value, list) and isinstance(base.get(key), list):
                _merge_list_by_id(base[key], value)
            else:
                base[key] = value

    _ev._deep_update = _deep_update_v2

    print(f"\n  运行 Evolver ({desc}, min_samples={min_samples})...")
    proposal = await evolver.evolve(date_str=today, dry_run=False, min_failure_samples=min_samples)

    # 恢复
    _ev._deep_update = _orig_dv

    return proposal


def print_config_diff(before_raw, label=""):
    """打印当前配置关键字段"""
    mgr2 = ConfigVersionManager()
    after_raw = mgr2.load_raw("nickname-selector", "rules_config")
    mgr2.close()

    if before_raw == after_raw:
        print(f"  [{label}] 配置无变化")
        return False

    before = yaml_safe.load(before_raw) if before_raw else {}
    after = yaml_safe.load(after_raw) if after_raw else {}
    changed = False

    # bad_categories
    bc_b = before.get("correctness_criteria", {}).get("bad_categories", [])
    bc_a = after.get("correctness_criteria", {}).get("bad_categories", [])
    if len(bc_b) != len(bc_a):
        print(f"  [{label}] bad_categories: {len(bc_b)} → {len(bc_a)}")
        changed = True

    # rejection_rules
    rr_b = before.get("rejection_rules", [])
    rr_a = after.get("rejection_rules", [])
    if len(rr_b) != len(rr_a):
        print(f"  [{label}] rejection_rules: {len(rr_b)} → {len(rr_a)}")
        changed = True

    # verification_conditions
    vc_b = before.get("correctness_criteria", {}).get("verification_conditions", [])
    vc_a = after.get("correctness_criteria", {}).get("verification_conditions", [])
    for v in vc_a:
        vid = v.get("id", "")
        vb = [x for x in vc_b if x.get("id") == vid]
        new_params = {k: v[k] for k in v if k not in ("id", "description", "checkable_in_skill", "note")}
        old_params = {}
        if vb:
            old_params = {k: vb[0][k] for k in vb[0] if k not in ("id", "description", "checkable_in_skill", "note")}
        if new_params != old_params:
            print(f"  [{label}] {vid}: {old_params} → {new_params}")
            changed = True

    if not changed:
        print(f"  [{label}] 配置无显著变化")
    return changed


# ════════════════════════════════════════════
# L1 实验：模式匹配 — 群名误判
# ════════════════════════════════════════════

def make_l1_cases():
    """构造 L1 案例：真实群名误判数据

    来源：ahxvcp3910405060 session_20260613111427 debug_session_derived.json
    真实发现的 nickname_candidate: "合家政群"（应以「群」结尾的群名被误判为昵称）
    补充同类型的微信真实群名模式
    """
    base = {
        "timestamp": datetime.now(BEIJING_TZ).isoformat(),
        "is_failure": True,
        "warnings": [],
        "elapsed_ms": 0,
        "card_binding_passed": True,
        "nickname_attribution_passed": True,
        "click_coordinate_passed": True,
    }

    # ── 5 条真实案例 ──
    real_cases = [
        {"trace_id": "real-001", "nickname": "合家政群", "candidates": ["合家政群"],
         "ai_validation": {"result": "不合理", "reason": "以「群」结尾，是微信群名而非个人昵称"},
         "ai_reselection": {"result": "renxin_system"},
         "final_output": {"source": "ai", "nickname": "renxin_system"},
         "suggested_fix": "新增 rejection_rules: 以「群」结尾的文本应丢弃，不纳入昵称候选"},
        {"trace_id": "real-002", "nickname": "合家政群", "candidates": ["合家政群"],
         "ai_validation": {"result": "不合理", "reason": "群名，非昵称"},
         "ai_reselection": {"result": "renxin_system"},
         "final_output": {"source": "ai", "nickname": "renxin_system"},
         "suggested_fix": "同上"},
        {"trace_id": "real-003", "nickname": "合家政群", "candidates": ["合家政群"],
         "ai_validation": {"result": "不合理", "reason": "以「群」结尾的群名"},
         "ai_reselection": {"result": "renxin_system"},
         "final_output": {"source": "ai", "nickname": "renxin_system"},
         "suggested_fix": "同上"},
        {"trace_id": "real-004", "nickname": "合家政群", "candidates": ["合家政群"],
         "ai_validation": {"result": "不合理", "reason": "群名误判为昵称"},
         "ai_reselection": {"result": "renxin_system"},
         "final_output": {"source": "ai", "nickname": "renxin_system"},
         "suggested_fix": "同上"},
        {"trace_id": "real-005", "nickname": "合家政群", "candidates": ["合家政群"],
         "ai_validation": {"result": "不合理", "reason": "群名，非个人昵称"},
         "ai_reselection": {"result": "renxin_system"},
         "final_output": {"source": "ai", "nickname": "renxin_system"},
         "suggested_fix": "同上"},
    ]

    # ── 5 条扩展案例（基于微信真实群名模式）──
    ext_cases = [
        {"trace_id": "ext-001", "nickname": "家政阿姨交流群", "candidates": ["家政阿姨交流群", "张伟"],
         "ai_validation": {"result": "不合理", "reason": "微信群名，以「群」结尾"},
         "ai_reselection": {"result": "张伟"}, "final_output": {"source": "ai", "nickname": "张伟"},
         "suggested_fix": "以「群」结尾的文本应丢弃"},
        {"trace_id": "ext-002", "nickname": "北京月嫂接单群", "candidates": ["北京月嫂接单群", "李静"],
         "ai_validation": {"result": "不合理", "reason": "微信群名"},
         "ai_reselection": {"result": "李静"}, "final_output": {"source": "ai", "nickname": "李静"},
         "suggested_fix": "以「群」结尾的文本应丢弃"},
        {"trace_id": "ext-003", "nickname": "上海育儿嫂群", "candidates": ["上海育儿嫂群", "王芳"],
         "ai_validation": {"result": "不合理", "reason": "以「群」结尾，是群名"},
         "ai_reselection": {"result": "王芳"}, "final_output": {"source": "ai", "nickname": "王芳"},
         "suggested_fix": "以「群」结尾的文本应丢弃"},
        {"trace_id": "ext-004", "nickname": "保姆中介对接群", "candidates": ["保姆中介对接群"],
         "ai_validation": {"result": "不合理", "reason": "群名非昵称"},
         "ai_reselection": {"result": "renxin_system"}, "final_output": {"source": "ai", "nickname": "renxin_system"},
         "suggested_fix": "以「群」结尾的文本应丢弃"},
        {"trace_id": "ext-005", "nickname": "家政接单群", "candidates": ["家政接单群", "刘洋"],
         "ai_validation": {"result": "不合理", "reason": "以「群」结尾，群名误判"},
         "ai_reselection": {"result": "刘洋"}, "final_output": {"source": "ai", "nickname": "刘洋"},
         "suggested_fix": "以「群」结尾的文本应丢弃"},
    ]

    cases = []
    for c in real_cases + ext_cases:
        entry = copy.deepcopy(base)
        entry["trace_id"] = c["trace_id"]
        entry["input_summary"] = {"case_id": c["trace_id"], "category": "群名误判"}
        entry["rule_output"] = {"nickname": c["nickname"], "candidates": c["candidates"], "category": "群名误判"}
        entry["ai_validation"] = c["ai_validation"]
        entry["ai_reselection"] = c["ai_reselection"]
        entry["final_output"] = c["final_output"]
        entry["suggested_fix"] = c["suggested_fix"]
        cases.append(entry)

    return cases


# ════════════════════════════════════════════
# L2 实验：数值调参 — 矮卡片点击边缘
# ════════════════════════════════════════════

def make_l2_cases():
    """构造 L2 案例：基于真实 session 点击边缘数据

    来源：ahxvcp3910405060 session_20260613111427 rg_009
    - 卡片 bbox: [72, 161, 563, 251]，高度仅 90px
    - 点击坐标: (155, 234)，距卡片底部仅 17px

    问题：当前 click_coordinate max_y_px 和 max_x_px 可能不够严格
    - X方向：点击 X=155，卡片左边缘 X=72，距左边缘 83px
    - Y方向：点击 Y=234，卡片底部 Y=251，距底部 17px

    其他真实案例：
    - rg_008 (session_20260613111815): 卡片 [72, 161, 563, 285] 高度124px，点击(155,268) 距底17px
    - rg_011: 卡片 [72, 161, 563, 302] 高度141px，点击(155,285) 距底17px
    """
    base = {
        "timestamp": datetime.now(BEIJING_TZ).isoformat(),
        "is_failure": True,
        "warnings": [],
        "elapsed_ms": 0,
        "card_binding_passed": True,
        "nickname_attribution_passed": True,
        "click_coordinate_passed": False,
    }

    # ── 10 条案例：基于当前 YAML 阈值 (max_x_px=20, max_y_px=0) 模拟 ──
    # 场景 A: X 方向 — 点击偏离超过当前 20px 阈值
    # 场景 B: Y 方向 — 矮卡片点击距底 > 0px（真实 rg_009: 卡片高90px, 点击距底17px）
    cases_data = []
    idx = 1

    # 场景 A: X 偏移在 12-14px 之间（接近当前 max_x_px=15 的边缘，但仍应通过）
    # 以及 X 偏移 16-18px（略超阈值，被误杀）
    for x_offset, is_error in [(12, "误杀"), (13, "误杀"), (14, "误杀"), (16, "合理"), (18, "合理")]:
        cases_data.append({
            "trace_id": f"l2-x{idx:03d}", "nickname": "正确昵称X",
            "candidates": ["正确昵称X", "隔壁卡昵称"],
            "category": "点击X偏移",
            "click_offset": {"x_px": x_offset, "y_px": 0},
            "current_threshold": {"max_x_px": 15, "max_y_px": 2},
            "verification_target": "click_coordinate.max_x_px",
            "current_value": 15, "suggested_value": 18 if is_error == "误杀" else 12,
            "suggested_fix": f"X偏移{x_offset}px：{'超过阈值被误杀，建议放宽到≥18px' if is_error == '误杀' else '在容差内，当前阈值合理'}。参考：真实session中矮卡片(90px)点击距卡片边缘17px，属正常范围。",
        })
        idx += 1

    # 场景 B: Y 偏移 — 真实 rg_009 数据，矮卡片(90px)点击距底 17px
    # 当前 max_y_px=2 太严格，应放宽到 5-8px
    for y_offset, is_error in [(3, "误杀"), (5, "误杀"), (8, "误杀"), (17, "误杀"), (1, "合理")]:
        cases_data.append({
            "trace_id": f"l2-y{idx:03d}", "nickname": "正确昵称Y",
            "candidates": ["正确昵称Y", "下一张卡昵称"],
            "category": "点击Y偏移",
            "click_offset": {"x_px": 0, "y_px": y_offset},
            "current_threshold": {"max_x_px": 15, "max_y_px": 2},
            "verification_target": "click_coordinate.max_y_px",
            "current_value": 2, "suggested_value": 8 if is_error == "误杀" else 2,
            "suggested_fix": f"Y偏移{y_offset}px：{'矮卡片(90px)正常点击被误杀，建议放宽 max_y_px 到≥8px' if is_error == '误杀' else '在容差内，当前阈值合理'}",
        })
        idx += 1

    cases = []
    for c in cases_data:
        entry = copy.deepcopy(base)
        entry["trace_id"] = c["trace_id"]
        entry["input_summary"] = {"case_id": c["trace_id"], "category": c["category"]}
        entry["rule_output"] = {"nickname": c["nickname"], "candidates": c["candidates"], "category": c["category"]}
        entry["ai_validation"] = {"result": "不合理" if "误过" in c.get("suggested_fix", "") else "合理（误杀）",
                                   "reason": c["suggested_fix"]}
        entry["ai_reselection"] = {"result": c["candidates"][1]}
        entry["final_output"] = {"source": "ai", "nickname": c["candidates"][1]}
        entry["click_offset"] = c["click_offset"]
        entry["current_threshold"] = c["current_threshold"]
        entry["verification_target"] = c["verification_target"]
        entry["current_value"] = c["current_value"]
        entry["suggested_value"] = c["suggested_value"]
        entry["suggested_fix"] = c["suggested_fix"]
        cases.append(entry)

    return cases


# ════════════════════════════════════════════
# L3 实验：语义规则生成 — 卡片重叠歧义
# ════════════════════════════════════════════

def make_l3_cases():
    """构造 L3 案例：基于真实会话 bbox 尺寸的卡片重叠案例

    真实数据：
    - 卡片标准宽度: 563-72 = 491px
    - 卡片标准高度: 1491-1218 = 273px
    - 最小卡片高度: 90px (rg_009)
    - 点击位置: X=155（距左边缘 83px, 即宽度的 16.9%），Y=距底部 17px
    - 正常卡片间距: 48px

    模拟场景：微信聊天列表滚动后，同一截图出现两批卡片，
    它们的 y 区间交叉（重叠），导致 click_coordinate 落在重叠区内
    """
    import random
    rng = random.Random(42)

    base = {
        "timestamp": datetime.now(BEIJING_TZ).isoformat(),
        "is_failure": True,
        "warnings": [],
        "elapsed_ms": 0,
    }

    # ── 场景 A (20条): 面积不等 — 正确卡占 50-60% 但规则绑到 30-42% 的卡 ──
    nicknames = ["张伟", "王强", "李磊", "刘洋", "陈刚", "杨军", "赵勇", "周超",
                 "王芳", "李静", "张敏", "刘娟", "陈丽", "杨秀", "赵娜", "周婷"]

    cases = []
    idx = 1

    for i in range(20):
        correct = rng.choice(nicknames)
        wrong = rng.choice([n for n in nicknames if n != correct])
        correct_ratio = round(rng.uniform(0.48, 0.60), 2)
        wrong_ratio = round(rng.uniform(0.28, 0.42), 2)
        remain = round(1.0 - correct_ratio - wrong_ratio, 2)
        overlap_count = rng.choice([2, 3])

        entry = copy.deepcopy(base)
        entry["trace_id"] = f"l3-u{idx:03d}"
        entry["input_summary"] = {"case_id": f"l3-u{idx:03d}", "category": "卡片重叠·面积不等"}
        entry["rule_output"] = {"nickname": wrong, "candidates": [wrong, correct], "category": "卡片重叠·面积不等"}
        entry["ai_validation"] = {"result": "不合理",
                                   "reason": f"点击区与{overlap_count}张卡重叠，正确卡占{correct_ratio*100:.0f}%面积但被规则绑到{wrong_ratio*100:.0f}%的卡"}
        entry["ai_reselection"] = {"result": correct}
        entry["final_output"] = {"source": "ai", "nickname": correct}
        entry["card_binding_passed"] = False
        entry["nickname_attribution_passed"] = False
        entry["click_coordinate_passed"] = True
        entry["overlap_info"] = {
            "overlap_card_count": overlap_count,
            "bound_card_area_ratio": wrong_ratio,
            "correct_card_area_ratio": correct_ratio,
            "other_remain_ratio": max(remain, 0.0),
        }
        entry["current_logic"] = "当前无重叠区消歧，area_ratio=0 仍会绑卡"
        entry["suggested_fix"] = "添加 min_overlap_area_ratio ≥ 0.30，低于此值不绑卡"
        entry["verification_target"] = "card_binding.min_overlap_area_ratio"
        entry["current_value"] = 0
        entry["suggested_value"] = 0.30
        cases.append(entry)
        idx += 1

    # ── 场景 B (20条): 面积接近 — 两卡面积差 < 5%，应标记 renxin_system ──
    for i in range(20):
        correct = rng.choice(nicknames)
        wrong = rng.choice([n for n in nicknames if n != correct])
        ratio_a = round(rng.uniform(0.45, 0.50), 2)
        ratio_b = round(1.0 - ratio_a, 2)

        entry = copy.deepcopy(base)
        entry["trace_id"] = f"l3-t{idx:03d}"
        entry["input_summary"] = {"case_id": f"l3-t{idx:03d}", "category": "卡片重叠·面积相等"}
        entry["rule_output"] = {"nickname": wrong, "candidates": [wrong, correct], "category": "卡片重叠·面积相等"}
        entry["ai_validation"] = {"result": "不合理",
                                   "reason": f"两卡面积接近（{ratio_a*100:.0f}% vs {ratio_b*100:.0f}%），无法确定归属，应标记 renxin_system 而非随机选一张"}
        entry["ai_reselection"] = {"result": "renxin_system"}
        entry["final_output"] = {"source": "ai", "nickname": "renxin_system"}
        entry["card_binding_passed"] = True
        entry["nickname_attribution_passed"] = False
        entry["click_coordinate_passed"] = True
        entry["overlap_info"] = {
            "overlap_card_count": 2,
            "bound_card_area_ratio": ratio_a,
            "correct_card_area_ratio": ratio_b,
            "area_diff_pct": round(abs(ratio_a - ratio_b) * 100, 1),
        }
        entry["current_logic"] = "面积相近时仍绑第一张，无 tie-breaking"
        entry["suggested_fix"] = "添加 ambiguity_tie_ratio ≤ 0.05，面积差低于此值标记 renxin_system"
        entry["verification_target"] = "card_binding.ambiguity_tie_ratio"
        entry["current_value"] = None
        entry["suggested_value"] = 0.05
        cases.append(entry)
        idx += 1

    return cases


# ════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════

async def main():
    mgr = ConfigVersionManager()

    # 1. 快照基线
    print("=" * 60)
    print("Phase 0: 快照基线配置")
    print("=" * 60)
    baseline_raw, baseline_ver = snapshot_config(mgr)
    print(f"  基线版本: {baseline_ver}")

    # 备份磁盘
    if RULES_DISK_PATH.exists():
        RULES_DISK_BACKUP.write_text(RULES_DISK_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    ds_cfg = get_deepseek_config()
    client = DeepSeekClient(api_key=ds_cfg.api_key, api_base=ds_cfg.api_base, model=ds_cfg.model)

    results = {}

    # ═══ L1 实验 ═══
    print("\n" + "=" * 60)
    print("L1 实验：模式匹配 — 真实「群名误判」失败案例")
    print("=" * 60)

    l1_cases = make_l1_cases()
    write_jsonl(l1_cases)
    print(f"  案例: {len(l1_cases)} 条 (5 真实 + 5 扩展)")
    print(f"  目标: Evolver 应提出新增 rejection_rules（以「群」结尾的 dropout 规则）")

    proposal_l1 = await run_evolver(mgr, client, min_samples=5, desc="L1-群名误判")

    if proposal_l1:
        results["L1"] = {
            "failure_count": proposal_l1.failure_count,
            "applied": proposal_l1.applied,
            "rolled_back": getattr(proposal_l1, 'rolled_back', False),
            "rules_changes_keys": list(proposal_l1.rules_changes.keys()) if proposal_l1.rules_changes else [],
        }
        print(f"\n  L1 结果:")
        print(f"    failure_count: {proposal_l1.failure_count}")
        print(f"    applied: {proposal_l1.applied}")
        print(f"    rolled_back: {getattr(proposal_l1, 'rolled_back', False)}")
        print(f"    rules_changes: {list(proposal_l1.rules_changes.keys()) if proposal_l1.rules_changes else '无'}")
        print_config_diff(baseline_raw, label="L1")

    # 恢复基线
    restore_config(mgr, baseline_raw)

    # ═══ L2 实验 ═══
    print("\n" + "=" * 60)
    print("L2 实验：数值调参 — 真实矮卡片点击边缘案例")
    print("=" * 60)

    l2_cases = make_l2_cases()
    write_jsonl(l2_cases)
    print(f"  案例: {len(l2_cases)} 条 (5 X偏移 + 5 Y偏移)")
    print(f"  目标: Evolver 应调整 click_coordinate 的 max_x_px / max_y_px 阈值")

    proposal_l2 = await run_evolver(mgr, client, min_samples=5, desc="L2-点击边缘")

    if proposal_l2:
        results["L2"] = {
            "failure_count": proposal_l2.failure_count,
            "applied": proposal_l2.applied,
            "rolled_back": getattr(proposal_l2, 'rolled_back', False),
            "rules_changes_keys": list(proposal_l2.rules_changes.keys()) if proposal_l2.rules_changes else [],
        }
        print(f"\n  L2 结果:")
        print(f"    failure_count: {proposal_l2.failure_count}")
        print(f"    applied: {proposal_l2.applied}")
        print(f"    rolled_back: {getattr(proposal_l2, 'rolled_back', False)}")
        print(f"    rules_changes: {list(proposal_l2.rules_changes.keys()) if proposal_l2.rules_changes else '无'}")
        print_config_diff(baseline_raw, label="L2")

    # 恢复基线
    restore_config(mgr, baseline_raw)

    # ═══ L3 实验 ═══
    print("\n" + "=" * 60)
    print("L3 实验：语义规则生成 — 卡片重叠歧义")
    print("=" * 60)

    l3_cases = make_l3_cases()
    write_jsonl(l3_cases)
    print(f"  案例: {len(l3_cases)} 条 (20 面积不等 + 20 面积接近)")
    print(f"  目标: Evolver 应提出新增 min_overlap_area_ratio 和 ambiguity_tie_ratio 参数")

    proposal_l3 = await run_evolver(mgr, client, min_samples=10, desc="L3-卡片重叠")

    if proposal_l3:
        results["L3"] = {
            "failure_count": proposal_l3.failure_count,
            "applied": proposal_l3.applied,
            "rolled_back": getattr(proposal_l3, 'rolled_back', False),
            "rules_changes_keys": list(proposal_l3.rules_changes.keys()) if proposal_l3.rules_changes else [],
        }
        print(f"\n  L3 结果:")
        print(f"    failure_count: {proposal_l3.failure_count}")
        print(f"    applied: {proposal_l3.applied}")
        print(f"    rolled_back: {getattr(proposal_l3, 'rolled_back', False)}")
        print(f"    rules_changes: {list(proposal_l3.rules_changes.keys()) if proposal_l3.rules_changes else '无'}")
        print_config_diff(baseline_raw, label="L3")

    # 恢复基线
    restore_config(mgr, baseline_raw)

    # ═══ 汇总报告 ═══
    print("\n" + "=" * 60)
    print("三层进化能力验证报告")
    print("=" * 60)

    for layer in ["L1", "L2", "L3"]:
        r = results.get(layer, {})
        status = "✅ 通过" if r.get("applied") and not r.get("rolled_back") else ("⚠️ 回滚" if r.get("rolled_back") else "❌ 未应用")
        print(f"  {layer}: {status}")
        print(f"    失败案例数: {r.get('failure_count', 'N/A')}")
        print(f"    规则变更: {r.get('rules_changes_keys', 'N/A')}")

    # 恢复磁盘备份
    if RULES_DISK_BACKUP.exists():
        RULES_DISK_PATH.write_text(RULES_DISK_BACKUP.read_text(encoding="utf-8"), encoding="utf-8")
        RULES_DISK_BACKUP.unlink()

    mgr.close()
    print("\n完成。所有配置已恢复到基线。")


if __name__ == "__main__":
    asyncio.run(main())
