"""
三方案对比：Evolver 改 YAML 后，AI 如何自动改下游代码
方案1: code_targets 显式映射（人写映射表）
方案2: SKILL.md 开发+测试模式（AI 自主定位文件）
方案3: test-collector SKILL.md 作为 skill.md（丰富的领域上下文）

测试目标：YAML 新增了 card_binding 的 min_overlap_area_ratio + ambiguity_tie_ratio
下游需要：nickname_ocr_simple.py 第 948-959 行实现重叠区消歧逻辑
"""
import json, os, sys, io, asyncio
from pathlib import Path
from ruamel.yaml import YAML

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

# ══ YAML diff（目标） ══
yaml_diff = """
card_binding 条件新增两参数:
  min_overlap_area_ratio: 0.3   — 点击区与卡片交集面积 ≥ 30% 才绑定
  ambiguity_tie_ratio: 0.05     — 两卡面积差 < 5% 时标记 renxin_system
"""

# ══ 下游代码片段（nickname_ocr_simple.py 948-959 行） ══
target_code = '''\
            # 构造 2×2 虚拟区域
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
                click_source_card_idx = matching_cards[0]
'''

# ══ 正确改法（golden） ══
golden_code = '''\
            # 构造 2×2 虚拟区域
            click_area = (cx, cy, cx + 2.0, cy + 2.0)
            # 找包含该区域的卡片，按交集面积排序
            matching_cards: list[tuple[int, float]] = []
            for i, raw in enumerate(raws):
                if not raw or len(raw) < 4:
                    continue
                rx1, ry1, rx2, ry2 = raw[0], raw[1], raw[2], raw[3]
                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                    # 计算交集面积占卡片面积的比例
                    card_area = (rx2 - rx1) * (ry2 - ry1)
                    overlap_area = (min(cx + 2.0, rx2) - max(cx, rx1)) * (min(cy + 2.0, ry2) - max(cy, ry1))
                    ratio = overlap_area / card_area if card_area > 0 else 0
                    if ratio >= min_overlap_area_ratio:
                        matching_cards.append((i, ratio))
            if len(matching_cards) == 1:
                click_source_card_idx = matching_cards[0][0]
            elif len(matching_cards) >= 2:
                # 按面积比排序
                matching_cards.sort(key=lambda x: x[1], reverse=True)
                # 前两名面积差 < ambiguity_tie_ratio → 标记为不确定
                if len(matching_cards) >= 2 and abs(matching_cards[0][1] - matching_cards[1][1]) < ambiguity_tie_ratio:
                    click_source_card_idx = None  # renxin_system
                else:
                    click_source_card_idx = matching_cards[0][0]
'''

# ══ DeepSeek 调用 ══
from skill_self_evolution.config import get_deepseek_config
from skill_self_evolution.deepseek import DeepSeekClient

ds = get_deepseek_config()
client = DeepSeekClient(api_key=ds.api_key, api_base=ds.api_base, model=ds.model)

async def ask_ai(system_prompt: str, user_prompt: str) -> str:
    resp = await client.chat([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])
    return resp.content if hasattr(resp, 'content') else str(resp)

# ====== 三方案定义 ======

SCHEME_1_SYSTEM = """你是 Python 代码生成专家。根据 YAML 参数变更修改下游代码。
严格按 code_targets 给出的文件路径和修改位置生成 diff。
只输出代码 diff，不要解释。"""

SCHEME_1_USER = f"""## code_target 映射表
| config_path | code_file | line_range | description |
|---|---|---|---|
| verification_conditions.card_binding | scripts/wx_match/processor/nickname_ocr_simple.py | 948-959 | click_area 匹配段，需加入 min_overlap_area_ratio 和 ambiguity_tie_ratio 消歧逻辑 |

## YAML 变更
{yaml_diff}

## 当前代码
```python
{target_code}
```

## 要求
1. 从 YAML 读取 min_overlap_area_ratio（默认 0.3）和 ambiguity_tie_ratio（默认 0.05）
2. matching_cards 改为记录 (index, area_ratio)
3. 多卡时按面积比选最大，面积差 < ambiguity_tie_ratio 时标记 renxin_system
4. 输出完整的新代码（替换 948-959 行）"""

SCHEME_2_SYSTEM = """你是 collector_phone_android 项目的测试+开发专家。
Skill: test-collector-customized-for-renxin
角色: 原为测试排障，现扩展为开发+测试。
能力: 读取 YAML 配置变更 → 定位下游消费代码 → 生成代码 diff → 跑测试验证。

定位规则:
- card_binding / click_coordinate → scripts/wx_match/processor/nickname_ocr_simple.py
- nickname_attribution → 同上 + backend/app/business/wx_match_business/ocr_session_rule_bridge.py
- bad_categories → scripts/wx_match/processor/nickname_ocr_simple.py + run.py::_judge_correctness
- rejection_rules → run.py::_rule_extract

改动安全:
- 只改函数体内逻辑，不改函数签名
- 新参数必须从 rules_config.yaml 读取
- 改完必须跑 pytest tests/test_wx_match/ 验证"""

SCHEME_2_USER = f"""## 任务
YAML 配置中 card_binding 条件新增了消歧参数:
{yaml_diff}

请:
1. 确定需要修改的文件
2. 定位到具体行
3. 生成代码 diff
4. 说明为什么选这个文件

## 当前关键代码片段（nickname_ocr_simple.py:948-959）
```python
{target_code}
```"""

SCHEME_3_SYSTEM = """你是微信群聊截图测试的专家。你的 SKILL.md 包含:
- 四个测试条件（卡片绑定/昵称归属/点击坐标/反向校验）
- 数据文件对应关系（metadata.json / debug_session_derived.json 等）
- BUG 修复工作流（定位 → 改代码 → 单轮验证 → 全量回归）
- 已知架构知识（nickname_ocr_simple.py 的 _resume_thumb_bindings_and_orphans 等函数）

现在你需要根据 rules_config.yaml 的变更，找到下游消费代码并修改。

重要: 先搜索代码确认文件位置，不要猜测。只输出代码 diff。"""

SCHEME_3_USER = f"""## YAML 变更 (rules_config.yaml)
card_binding 条件新增:
{yaml_diff}

## 当前关键代码片段（nickname_ocr_simple.py 约 948-959 行，点击区域匹配逻辑）
```python
{target_code}
```

## 你的任务
1. 根据 SKILL.md 中的知识，确定这段代码在哪个文件哪个函数
2. 根据 YAML 变更，生成正确的代码修改
3. 只输出代码 diff"""

async def main():
    results = {}
    y = YAML(typ="safe")

    # ═══ 方案 1 ═══
    print("=" * 60)
    print("=== 方案 1: code_targets 显式映射 ===")
    print("=" * 60)
    r1 = await ask_ai(SCHEME_1_SYSTEM, SCHEME_1_USER)
    has_file = "nickname_ocr_simple.py" in r1
    has_min_ratio = "min_overlap_area_ratio" in r1
    has_tie = "ambiguity_tie_ratio" in r1
    has_rename = "renxin_system" in r1 or "ambiguous" in r1.lower() or "不确定" in r1
    results["方案1"] = {
        "file_correct": has_file,
        "params_used": has_min_ratio and has_tie,
        "logic_correct": has_rename,
        "output_preview": r1[:600],
    }
    print(f"文件定位正确: {has_file}")
    print(f"参数使用正确: {has_min_ratio and has_tie}")
    print(f"消歧逻辑: {has_rename}")
    print(f"---\n{r1[:800]}\n---")

    # ═══ 方案 2 ═══
    print("\n" + "=" * 60)
    print("=== 方案 2: SKILL.md 开发+测试模式 ===")
    print("=" * 60)
    r2 = await ask_ai(SCHEME_2_SYSTEM, SCHEME_2_USER)
    has_file2 = "nickname_ocr_simple.py" in r2
    has_min_ratio2 = "min_overlap_area_ratio" in r2
    has_tie2 = "ambiguity_tie_ratio" in r2
    results["方案2"] = {
        "file_correct": has_file2,
        "params_used": has_min_ratio2 and has_tie2,
        "logic_correct": "renxin_system" in r2 or "tie" in r2.lower(),
        "output_preview": r2[:600],
    }
    print(f"文件定位正确: {has_file2}")
    print(f"参数使用正确: {has_min_ratio2 and has_tie2}")
    print(f"消歧逻辑: {results['方案2']['logic_correct']}")
    print(f"---\n{r2[:800]}\n---")

    # ═══ 方案 3 ═══
    print("\n" + "=" * 60)
    print("=== 方案 3: test-collector SKILL.md 作为 skill.md ===")
    print("=" * 60)
    r3 = await ask_ai(SCHEME_3_SYSTEM, SCHEME_3_USER)
    has_file3 = "nickname_ocr_simple.py" in r3 or "nickname_ocr" in r3.lower()
    has_min_ratio3 = "min_overlap_area_ratio" in r3
    has_tie3 = "ambiguity_tie_ratio" in r3
    has_logic3 = "renxin_system" in r3 or "面积差" in r3 or "tie" in r3.lower()
    results["方案3"] = {
        "file_correct": has_file3,
        "params_used": has_min_ratio3 and has_tie3,
        "logic_correct": has_logic3,
        "output_preview": r3[:600],
    }
    print(f"文件定位正确: {has_file3}")
    print(f"参数使用正确: {has_min_ratio3 and has_tie3}")
    print(f"消歧逻辑: {has_logic3}")
    print(f"---\n{r3[:800]}\n---")

    # ═══ 汇总 ═══
    print("\n" + "=" * 60)
    print("=== 三方案对比汇总 ===")
    print("=" * 60)
    print(f"{'维度':<20} {'方案1(code_targets)':<22} {'方案2(SKILL扩展)':<22} {'方案3(SKILL替换)':<22}")
    print("-" * 86)
    for dim, keys in [("文件定位", ["file_correct"]), ("参数使用", ["params_used"]), ("消歧逻辑", ["logic_correct"])]:
        vals = []
        for s in ["方案1", "方案2", "方案3"]:
            ok = all(results[s].get(k, False) for k in keys)
            vals.append("✅" if ok else "❌")
        print(f"{dim:<20} {vals[0]:<22} {vals[1]:<22} {vals[2]:<22}")

    # 综合评分
    print(f"\n{'方案':<20} {'得分':<10} {'关键弱点':<30}")
    print("-" * 60)
    for s in ["方案1", "方案2", "方案3"]:
        r = results[s]
        score = sum([r["file_correct"], r["params_used"], r["logic_correct"]])
        if s == "方案1":
            weakness = "需人手维护code_targets"
        elif s == "方案2":
            weakness = "定位规则需在prompt硬编码"
        else:
            weakness = "skill.md与skill不匹配"
        print(f"{s:<20} {score}/3{'':<6} {weakness:<30}")

    # 保存完整结果
    out = Path("E:/projects/skill_self_evolution/data/code_evolve_comparison.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n完整结果: {out}")

if __name__ == "__main__":
    asyncio.run(main())
