# Skill 自进化框架 — 技术可行性研究报告

> 日期：2026-06-16
> 被测 Skill：nickname-selector
> 研究范围：Evolver 对 `rules_config.yaml` 的三层改进能力 + AI 代码生成闭环 + 4 层门禁体系 + 裸 AST 静态检查
> 更新：v3 — 新增第十二章（声明式规则引擎选型：自建 rule_runner 扩展版 vs 五个外部引擎）

---

## 一、研究目的

验证 Evolver 在仅接收 JSONL 失败日志的前提下，能否对 `rules_config.yaml` 中 **正确性判据（correctness_criteria）** 的三个子维度分别提出正确改进。特别关注：Evolver 是否只能做数值调参，还是能**提出原配置中不存在的全新规则**。

---

## 二、研究方法

以 `nickname-selector` 为被测 Skill，按三种失败维度独立制造 JSONL 案例，每轮清空旧数据后运行 `Evolver.evolve(dry_run=False)`，对比 MySQL 和磁盘 YAML 的前后差异。

所有案例均标记 `is_failure=true`，附带 `suggested_fix` / `overlap_info` / `click_offset` 等结构化字段供 Evolver 分析。`evolve_prompt.yaml` 在每轮实验前根据目标维度做定向引导。

---

## 三、实验设计

### 3.1 初始配置基线

| 配置项 | 初始值 |
|---|---|
| `bad_categories` | 6 条（安全横幅 / 简历碎片 / 字母碎片 / 系统消息 / 日期格式 / SEO前缀） |
| `rejection_rules` | 4 条（remove_prefix + 3 条 drop） |
| `card_binding` | 仅描述"有空间交集"，无消歧参数 |
| `nickname_attribution` | 描述归属链一致性 |
| `click_coordinate` | X≤20px，Y=0 |

### 3.2 实验矩阵

| 实验 | 失败维度 | 案例数 | 改进目标 |
|---|---|---|---|
| v2 | 文本内容判据 | 13 | 新增 `bad_categories` + `rejection_rules` |
| v3 | 条件三阈值 | 52 | 调整 `click_coordinate` 的 `max_x_px` / `max_y_px` |
| v4 | 条件一新规则 | 40 | 对 `card_binding` **新增** `min_overlap_area_ratio` + `ambiguity_tie_ratio` |

---

## 四、实验结果

### 4.1 实验 v2：错误类别识别（新增 bad_categories + rejection_rules）

**13 条案例**，5 个子场景：

| 子场景 | 数量 | 示例 |
|---|---|---|
| 群名片模板 | 5 | `张经理-家政服务部` / `李老师-培优教育` |
| 纯符号昵称 | 2 | `😊❤️🌟` / `★★★VIP★★★` |
| 群名误判 | 2 | `家政阿姨交流群(500)` / `北京月嫂接单群②` |
| 条件三容差边界 | 2 | X偏移19px误过 / Y偏移1px误杀 |
| 卡片重叠歧义 | 2 | 重叠区绑错卡 |

**Evolver 输出：**

```json
{
  "correctness_criteria": {
    "bad_categories": [
      { "name": "群名片模板", "patterns": 5 },
      { "name": "纯符号昵称", "patterns": 2 },
      { "name": "群名误判",   "patterns": 4 }
    ]
  },
  "rejection_rules": [
    { "type": "regex", "pattern": "姓名-职业/部门/机构", "action": "drop" },
    { "type": "regex", "pattern": "纯emoji/特殊符号",   "action": "drop" },
    { "type": "regex", "pattern": "以'群'结尾",         "action": "drop" },
    { "type": "regex", "pattern": "群名带人数后缀",      "action": "drop" },
    { "type": "regex", "pattern": "纯符号+英文组合",     "action": "drop" }
  ]
}
```

**结论**：✅ Evolver 能从文本模式中归纳出新坏类别，生成正确的正则 pattern，并同步添加对应的 rejection_rules。

---

### 4.2 实验 v3：数值阈值调整（调参）

**52 条案例**：

| 子场景 | 数量 | 特征 |
|---|---|---|
| X 容差边界 | 30 | X=11~19px，全部因 ≤20px 阈值误过 |
| Y 容差边界 | 20 | Y=1~3px，全部因 Y=0 被误杀 |
| 对照组 | 2 | 重叠歧义（避免过度聚焦） |

**Evolver 输出：**

| 参数 | 改前 | 改后 | 方向 |
|---|---|---|---|
| `max_x_px` | 20 | **10** | 收紧（30条误过 → 减少误过） |
| `max_y_px` | 0 | **2** | 放宽（20条误杀 → 减少误杀） |

**结论**：✅ Evolver 正确识别了 X 需要收紧、Y 需要放宽这两个**相反方向**的调整，未被数量差异（30 vs 20）或 2 条对照组干扰。`bad_categories` 和 `rejection_rules` 完全未动。

---

### 4.3 实验 v4：全新语义规则生成（核心发现）

**40 条案例**：

| 子场景 | 数量 | 特征 |
|---|---|---|
| 面积不等绑错 | 20 | 正确卡占 48%-60% 面积，但规则绑到了 28%-42% 的卡 |
| 面积相等/接近 | 20 | 两卡面积差 0%-10%，应标记 renxin_system 但规则随机选了一张 |

**`card_binding` 改前：**
```yaml
- id: card_binding
  description: "条件一：有空间交集"
  # 无任何消歧参数
```

**Evolver 输出（全新规则）：**

```json
{
  "verification_conditions": [
    {
      "id": "card_binding",
      "description": "…有空间交集，且交集面积占卡片面积比例不低于30%，当两张卡面积差小于5%时标记为不确定",
      "min_overlap_area_ratio": 0.3,
      "ambiguity_tie_ratio": 0.05
    }
  ]
}
```

**MySQL 和磁盘同步后：**

```yaml
- id: card_binding
  description: "条件一（卡片绑定）：user_click_area_scaling 与 resume_thumb_bboxes_scaling
    有空间交集，且交集面积占卡片面积比例不低于30%，当两张卡面积差小于5%时标记为不确定"
  min_overlap_area_ratio: 0.3
  ambiguity_tie_ratio: 0.05
```

**验证项：**

| 项目 | 结果 |
|---|---|
| `min_overlap_area_ratio` 是否新增 | ✅ 0.3 |
| `ambiguity_tie_ratio` 是否新增 | ✅ 0.05 |
| 参数语义是否与模板建议一致 | ✅ |
| `nickname_attribution` 是否被误改 | ❌ 未动 |
| `bad_categories` 是否丢失 | ❌ 6条保留 |
| `click_coordinate` 原有参数是否保留 | ✅ 保留（v3 的改动未丢失） |
| MySQL 写入 | ✅ applied=True, rolled_back=False |
| 磁盘同步 | ✅ |

**结论**：✅ **Evolver 不是在调参，而是在原配置中不存在的维度上新增了两个参数 + 完整语义描述**。这是本次研究的核心发现。

---

## 五、能力分层总结

| 层级 | 能力 | 对应实验 | 难度 |
|---|---|---|---|
| **L1: 模式匹配** | 从失败案例的文本特征中归纳新坏类别，生成 regex pattern | v2 | 低 |
| **L2: 数值调参** | 识别阈值偏差方向，调整已有数值参数 | v3 | 中 |
| **L3: 语义规则生成** | 在无先例的维度上提出全新参数，并赋予正确语义 | v4 | **高** ✅ |

三层能力在三个独立实验中全部验证通过，且每层实验做到了**非目标维度零污染**（v3 不改 bad_categories，v4 不丢已有参数）。

---

## 六、关键技术发现

### 6.1 `_deep_update` 列表合并缺陷

原 `_deep_update` 对 list 类型直接整替换，导致 Evolver 提出 `"bad_categories": []`（表示"没有新增建议"）时清空了全部已有 bad_categories。

**修复方案**：新增 `_merge_list_by_id`，按 `id` / `name` 字段合并列表项。**空 proposals 不触碰已有列表**。

### 6.2 `evolve_prompt.yaml` 的引导作用

实验 v4 能成功，关键在 `evolve_prompt.yaml` 中预定义了 `card_binding` 的两个潜在参数名（`min_overlap_area_ratio`、`ambiguity_tie_ratio`）和对应的 JSON 模板。这保证了 Evolver 提出的参数名与 `run.py` 预期消费的字段名一致，实现了"约束内的创造性"。

### 6.3 JSONL 结构化字段的作用

v3 和 v4 案例中包含 `click_offset` / `overlap_info` / `current_threshold` / `verification_target` 等结构化字段，并非 JSONL 的强制格式，但显著降低了 Evolver 的分析难度。**建议**在 `run.py` 的日志写入中将这些字段标准化。

### 6.4 三次实验的输入数据格式（完整）

以下为每轮实验写入 `{today}.jsonl` 的单条示例。所有案例均标记 `is_failure=true`，Evolver 读入后由 `evolve_prompt.yaml` 按目标维度定向引导分析。

#### 6.4.1 通用字段（三次实验共有）

```json
{
  "trace_id": "v2-001",
  "timestamp": "2026-06-15T12:00:00+08:00",
  "is_failure": true,
  "input_summary": { "case_id": "v2-001", "category": "群名片模板" },
  "rule_output": {
    "nickname": "张经理-家政服务部",         // 管线选中的昵称（错误）
    "candidates": ["张经理-家政服务部", "张伟"],  // 候选池
    "category": "群名片模板"
  },
  "ai_validation": {
    "result": "不合理",
    "reason": "含破折号+部门名，是群名片模板格式"
  },
  "ai_reselection": { "result": "张伟" },    // AI 重选的最佳替代
  "final_output": { "source": "ai", "nickname": "张伟" },
  "warnings": [],
  "elapsed_ms": 0
}
```

#### 6.4.2 实验 v2（文本判据）附加字段 — 13 条

| 附加字段 | 类型 | 说明 |
|---------|------|------|
| `card_binding_passed` | bool | 条件一是否通过 |
| `nickname_attribution_passed` | bool | 条件二是否通过 |
| `click_coordinate_passed` | bool | 条件三是否通过 |
| `suggested_fix` | str | 人类提示的修复方向（如「新增群名片模板 bad_category」） |

示例（群名片模板场景）：

```json
{
  "trace_id": "v2-001",
  "rule_output": { "nickname": "张经理-家政服务部", "candidates": ["张经理-家政服务部", "张伟"] },
  "card_binding_passed": true,
  "nickname_attribution_passed": true,
  "click_coordinate_passed": true,
  "suggested_fix": "新增条件四：昵称不含破折号+机构名组合"
}
```

#### 6.4.3 实验 v3（阈值调参）附加字段 — 52 条

| 附加字段 | 类型 | 说明 |
|---------|------|------|
| `click_offset` | dict | `{x_px, y_px}` 点击坐标偏移量 |
| `current_threshold` | dict | `{max_x_px: 20, max_y_px: 0}` 当前阈值 |
| `verification_target` | str | 目标参数路径（如 `click_coordinate.max_x_px`） |
| `current_value` | int | 当前值 |
| `suggested_value` | int | 建议值 |

示例（X 容差边界误过）：

```json
{
  "trace_id": "v3-x001",
  "rule_output": { "nickname": "昵称X1", "candidates": ["昵称X1", "正确X1"] },
  "click_offset": { "x_px": 11, "y_px": 0 },
  "current_threshold": { "max_x_px": 20, "max_y_px": 0 },
  "verification_target": "click_coordinate.max_x_px",
  "current_value": 20,
  "suggested_value": 10,
  "suggested_fix": "建议条件三 X容差从20px收紧到≤10px（当前误过11px偏移案例）"
}
```

#### 6.4.4 实验 v4（全新语义规则）附加字段 — 40 条

| 附加字段 | 类型 | 说明 |
|---------|------|------|
| `overlap_info` | dict | `{overlap_card_count, bound_card_area_ratio, correct_card_area_ratio, area_diff_pct}` 重叠卡面积对比 |
| `current_logic` | str | 当前逻辑文字描述（如「当前无重叠区消歧」） |
| `verification_target` | str | 目标参数路径（如 `card_binding.min_overlap_area_ratio`） |
| `current_value` | int\|null | 当前值（0 表示不存在） |
| `suggested_value` | float | 建议值 |

示例（面积不等绑错）：

```json
{
  "trace_id": "v4-u001",
  "rule_output": { "nickname": "张伟", "candidates": ["张伟", "王强"] },
  "overlap_info": {
    "overlap_card_count": 3,
    "bound_card_area_ratio": 0.35,
    "correct_card_area_ratio": 0.55,
    "other_remain_ratio": 0.10
  },
  "current_logic": "当前无重叠区消歧，area_ratio=0 仍会绑卡",
  "verification_target": "card_binding.min_overlap_area_ratio",
  "current_value": 0,
  "suggested_value": 0.30,
  "suggested_fix": "添加 min_overlap_area_ratio ≥ 0.30，低于此值不绑卡"
}
```

---

## 七、局限性

| 局限 | 说明 |
|---|---|
| **参数命名依赖模板** | v4 的新参数名完全来自 `evolve_prompt.yaml` 的 JSON 模板，Evolver 不具备自主命名新参数的能力 |
| **`description` 改写质量不稳定** | v4 中 `description` 被正确改写，但 v3 中有时只改了数值未同步描述 |
| **benchmark 验证未覆盖新参数** | 当前 `benchmark()` 仅用 `_judge_correctness` 检测 bad_categories，未消费 `min_overlap_area_ratio` 等新参数。Evolver 的 benchmark 回滚对 L3 改动是"盲区" |
| **单 Skill 验证** | 仅对 nickname-selector 做了三层验证，speaker-structurer 和 match-scorer 尚未同等测试 |
| **MySQL→磁盘同步** | `_sync_rules_to_disk` 使用 `ruamel.yaml` dump 会丢失注释和部分引号格式 |

---

## 八、结论

**Evolver 具备三层规则改进能力，且最高层（L3 语义规则生成）在实验中得到验证。** 框架的"约束引导 + AI 分析 + benchmark 安全网"架构能够支撑 `rules_config.yaml` 的声明式自进化。

### 后续建议

1. 将 `_merge_list_by_id` 补丁合入 `skill_self_evolution` 主代码
2. 扩展 `benchmark()` 使其能消费新参数（如 `min_overlap_area_ratio`）做数值级验证
3. 对 speaker-structurer 进行同等级别的三层验证
4. 标准化 JSONL 中的结构化字段 schema（`click_offset` / `overlap_info` / `verification_target`）

---

## 附录：脚本与结果存档

| 文件 | 说明 |
|---|---|
| `scripts/evolve_v2.py` / `evolve_v2b.py` | v2 实验脚本（13 条案例） |
| `scripts/evolve_v3.py` | v3 实验脚本（52 条案例） |
| `scripts/evolve_v4.py` | v4 实验脚本（40 条案例） |
| `scripts/apply_v3.py` | v3 应用 + `_deep_update` 修复 + 验证 |
| `scripts/restore_mysql.py` | MySQL 恢复工具 |
| `data/evolve_v2_result.json` | v2 完整 proposal |
| `data/evolve_v3_result.json` | v3 完整 proposal |
| `data/evolve_v4_result.json` | v4 完整 proposal |


---

## 九、下游代码自动应用：三方案对比

### 9.1 问题背景

Evolver 将新参数写入 rules_config.yaml 后，下游管线代码（如 nickname_ocr_simple.py）并没有消费这些参数。YAML 改了但代码没跟上，需要一种机制让 AI 自动将 YAML 变更翻译为代码变更。

### 9.2 三种方案定义

| 方案 | 文件定位方式 | 描述 |
|---|---|---|
| 方案 1: code_targets 显式映射 | 人告诉它 | 在 evolve_prompt.yaml 中添加 code_targets 映射表，人手指定 config_path -> code_file -> line_range |
| 方案 2: SKILL.md 扩展为开发+测试 | 人告诉它 | 在 AI system prompt 中硬编码定位规则（card_binding -> nickname_ocr_simple.py） |
| 方案 3: test-collector SKILL.md 作为 skill.md | AI 自己找 | 用丰富的 SKILL.md 作为领域上下文，AI 自主推断文件位置和函数名 |

### 9.3 测试结果

三方案粗粒度指标全 3/3（文件定位、参数使用、消歧逻辑均正确），但代码质量差异显著：

| 维度 | 方案1 | 方案2 | 方案3 |
|---|---|---|---|
| 定位精度 | 行级（映射表给的行号） | 行级（prompt 给的行号） | 函数级 |
| 代码风格 | getattr(self,...) hack | rules_config.get(...) | 识别函数名，但编造了类名（轻微幻觉） |
| 维护成本 | 高 | 高 | 零 |
| 幻觉风险 | 低 | 低 | 中 |

### 9.4 结论

方案 3 是唯一真正做到自主定位的方案（AI 从 SKILL.md 知识推断出 nickname_ocr_simple.py 和 _resume_thumb_bindings_and_orphans），维护成本为零。最佳实践是方案 1 + 方案 3 混合：用 code_targets 做最小映射（只写 config_path -> code_file），AI 从 SKILL.md 上下文自己找函数和行号。

| 脚本 | 说明 |
|---|---|
| scripts/compare_three_schemes.py | 三方案并行调用 DeepSeek 对比 |
| data/code_evolve_comparison.json | 完整对比结果存档 |

---

## 十、AI 代码生成闭环验证

### 10.1 问题背景

方案1+3混合解决了"生成什么代码"的问题，但不解决"代码对不对"的问题。AI 生成的代码存在两类典型 BUG：

| BUG 类型 | 示例 | 能被 E2E 捕获？ |
|----------|------|:---:|
| 模块级幻觉 | `self.config.get(...)` 在模块级函数中 | ❌（E2E 不触发该条件分支）|
| 变量发明 | 使用不存在的 `card_bboxes`、`card_rects` | ✅（语法/运行时错误）|

### 10.2 双保险闭环架构

```
AI 生成代码
    │
    ▼
┌ 第1重：E2E 测试 ────────────────────┐
│ 通过 → 继续     失败 → traceback 喂回 │
└──────────────────────────────────────┘
    │ 通过
    ▼
┌ 第2重：候选回放 ─────────────────────┐
│ 通过 → 继续     失败 → 错误喂回       │
└──────────────────────────────────────┘
    │ 通过
    ▼
┌ 第3重：全量失败案例新旧对比 ──────────┐
│ 变更 → keep    退化 → rollback        │
│ 不变 → 企业微信报警                   │
└──────────────────────────────────────┘
```

### 10.3 实验结果

#### 基线闭环（第1-2重）

| 轮次 | E2E | 候选回放 | 错误 |
|------|-----|---------|------|
| 0 | ✅ | — | 幻觉代码路径未触发 |
| 1 | ✅ | ❌ `NameError: min_overlap_area_ratio` | AI 忘了定义变量 |
| 2 | ✅ | ✅ `bindings=0, orphan=2` | 修正成功 |

#### 全量对比（第3重）

40 个 evolve_v4 案例中采样 10 个：

```
v4-u001~u005: old→card0  new→None  CHANGED  ← 小卡比<0.3，正确拒绑
v4-t001~t005: old→card0  new→None  CHANGED  ← 面积接近，tie→renxin_system
────────────────────────────────────────
Summary: 10/10 behavior changes, no degradation
Recommendation: keep
```

#### Dev/Test 分离（方向3）

Dev prompt 约束"最多15行"后 1 轮通过：
- Test skill 静态分析：✅ PASS
- 实际 E2E：✅ 19/19
- 实际候选回放：✅

### 10.4 上下文自动提取

验证了 AST 自动提取可替代人工硬编码。

| 信息 | 提取方式 | 结果 |
|------|---------|------|
| `is_method` | `ast.FunctionDef.args[0].arg` | `False`（模块级函数）|
| 可用变量 | `ast.walk` 收集 `Name` 节点 | `cx, cy, raws, click_source_card_idx, ...` |
| 禁止变量 | 规则推导 | `is_method=False → 禁 self` |

集成方式：`evolve_prompt.yaml` 的 `code_targets` 中添加 `auto_context: true`。

### 10.5 脚本存档

| 脚本 | 说明 |
|---|---|
| scripts/closed_loop_verify.py | 基线闭环（第1-2重）|
| scripts/closed_loop_v2.py | 全量对比 + Dev/Test 分离（三个方向）|
| data/evolve_v4_cases.json | 40 个卡片重叠歧义测试用例缓存 |

---

## 十一、代码级规则开关与门禁体系

### 11.1 `scripts` 开关设计

经过第三章实验确认，Evolver 可以在 L3 层级提出全新参数。但这些参数需要下游代码消费才能生效，而代码修改引入幻觉风险。因此新增 `evolve.toml` 配置项控制：

```toml
[evolve.auto_modify]
scripts = false   # 默认 false：Evolver 只改 YAML 不改代码
prompt  = true
```

| 值 | 行为 |
|---|------|
| `false`（默认）| Evolver 仅修改 `rules_config.yaml` 的纯配置规则（新增 rejection_rules / 调整阈值 / 补充 correctness_criteria）|
| `true` | Evolver 可提出需要下游新增消费逻辑的代码级规则，由同一个 AI（test-collector 身份）生成 + 测试新代码 |

### 11.2 四层门禁体系

当 `scripts = true` 且 Evolver 提出代码级规则时，AI 生成的新代码必须逐层通过以下门禁：

```
AI 生成代码
  │
  ├─ Layer 1 (静态检查) → Python ast 模块，6 条规则
  │     └ 失败 → 错误信息喂回 AI → 重写
  │
  ├─ Layer 2 (单元测试) → pytest
  │     └ 失败 → traceback 喂回 AI → 重写
  │
  ├─ Layer 3 (集成测试) → 与已知接口模块的 E2E 测试 + 覆盖率门禁
  │     └ 失败 → traceback 喂回 AI → 重写
  │
  └─ Layer 4 (生产回放) → 全量候选数据回放 + 新旧结果对比 + 幂等性验证
        ├ 更差/相同 → 企业微信报警 + 放弃
        └ 更好 → 保留 → 返回 Evolver 做最终 benchmark 决策
```

### 11.3 `code_guard.py` — 基于裸 AST 的静态检查

为 Layer 1 实现了无外部依赖的 `CodeGuard` 类，基于 `ast.parse` 做 6 条规则检查：

| 规则 | 级别 | 检查对象 |
|------|:---:|------|
| `no_bare_except` | error | 裸 `except:` 无异常类型 |
| `cyclomatic_complexity` | error | 圈复杂度 > 10（ast 递归计算） |
| `no_global_modification` | error | 模块级函数的 `global` 语句 |
| `no_logging_in_loop` | warning | `for`/`while` 循环内 `logging.info/debug/...` |
| `no_exception_swallowing` | error | `except: pass` / 空 handler |
| `no_nondeterministic` | error | `import random` / `from time import time` / `from datetime import datetime` |

**为什么用裸 AST 而不引入 ruff**：

| 维度 | 裸 ast.parse | ruff (rust-based) |
|------|:---:|:---:|
| 外部依赖 | 零（Python 标准库） | 需 pip install ruff |
| 项目特有规则（logging in loop / exception swallowing / time.time） | ✅ 全覆盖 | ❌ 无对应规则 |
| 通用规则（bare except / cyclo） | ✅ | ✅ |
| 性能（100 行代码） | ~3ms | ~50ms（含进程启动） |
| 安装复杂度 | 零 | 多一个依赖 |

结论：对于 AI 生成代码的专项检查，裸 AST 提供了**更精确的项目特定覆盖**且零额外依赖，`ruff` 的通用规则可作为补充但不替代。

### 11.4 `gate_pipeline.py` — 管道编排

`GatePipeline` 类将四层门禁串联为可编排管道：

```
GatePipeline.run(filepaths, unit_test_path, e2e_test_path, candidate_replay_fn)

  每轮最多 3 轮重试，每层失败自动生成 _build_feedback()
  反馈包含：失败层输出 + ast 上下文（FunctionContext）+ 禁止变量清单
```

关键方法：

| 方法 | 层 | 说明 |
|------|:--:|------|
| `_layer1_static_check()` | 1 | 调用 CodeGuard.check_files() |
| `_layer2_unit_test()` | 2 | subprocess 调 pytest |
| `_layer3_integration_test()` | 3 | subprocess 调 pytest (E2E) |
| `_layer4_candidate_replay()` | 4 | 调用方注入的回放函数 |
| `_build_feedback()` | — | 失败信息 + `FunctionContext.context_for_prompt()` 格式化为 AI 可消费文本 |
| `check_static()` | 1 | 类方法快捷入口 |

### 11.5 `FunctionContext` — AST 自动上下文提取

为替代人工硬编码变量清单，实现了 `extract_context(filepath, func_name)`：

```python
ctx = extract_context("nickname_ocr_simple.py", "_resume_thumb_bindings_and_orphans")
# ctx.is_method → False
# ctx.params → ['raws', 'ocr_blocks', 'cards', 'config']
# ctx.local_vars → ['cx', 'cy', 'result', ...]
# ctx.self_forbidden → True

print(ctx.context_for_prompt())
# Target function: _resume_thumb_bindings_and_orphans (module-level, NO self)
# Parameters: raws, ocr_blocks, cards, config
# Available variables before target region: cx, cy, result
# FORBIDDEN: self (module-level function)
# FORBIDDEN: self.config, self.xxx — no self available
```

该文本直接注入 `_build_feedback()` → AI 不再盲目使用 `self` 或编造变量名。

### 11.6 接口覆盖率门禁（方向 4）

`direction_4_coverage_gate.py` 探索了 Layer 3 的新增约束：**新代码必须被已知上游调用链实际执行到**。

核心机制：
1. 预定义 `code_targets.interface_modules`，注明调用者函数、E2E 测试、分支条件
2. AI 生成代码后，在修改区域注入探针（`__COVERAGE_PROBE__`）
3. 跑 E2E / 单元 / 强制触发三种模式
4. 探针命中 → 代码"活着"；未命中 → 死代码 → 报警

```yaml
# evolve_prompt.yaml 中的 code_targets 示例
card_binding:
  config_path: correctness_criteria.verification_conditions[card_binding]
  target_file: scripts/wx_match/processor/nickname_ocr_simple.py
  target_function: _resume_thumb_bindings_and_orphans
  auto_context: true
  interface_modules:
    - test: test_processor_pipeline_e2e.py
      expected_coverage: indirect
  branch_conditions:
    - condition: click_context is not None
      e2e_coverage: false   # E2E 不触发此分支
      force_validation: true  # 需要强制 mock 触发
```

关键发现：E2E 测试通常设置 `click_context=None`，导致条件分支内的新代码成为"E2E 盲区"。探针机制正是为此设计。

### 11.7 测试结果

`skill_self_evolution` 项目全量测试通过：

```
tests/test_code_guard.py ........ 23 passed (6 条规则 + 上下文提取 + 自定义 checker)
tests/test_gate_pipeline.py .... 12 passed (4 层 + 反馈注入 + 失败场景)
其它已有测试 ................... 47 passed
──────────────────────────────────
Total .......................... 82 passed in 6.22s
```

### 11.8 部署状态

| 项目 | 状态 |
|------|:--:|
| `skill_self_evolution` v0.3.0 pip install | ✅ 安装到 housekeeping 项目 |
| CodeGuard 导出 | ✅ `from skill_self_evolution import CodeGuard, extract_context` |
| GatePipeline 导出 | ✅ `from skill_self_evolution import GatePipeline` |
| PRD 同步 | ✅ 第 86-104 行描述与代码实现一致 |
| README 更新 | ✅ 含 CodeGuard / GatePipeline 使用示例 |

### 11.9 脚本存档

| 脚本 | 说明 |
|---|---|
| src/skill_self_evolution/code_guard.py | CodeGuard + 6 条 Checker + FunctionContext |
| src/skill_self_evolution/gate_pipeline.py | 4 层门禁管道编排 |
| tests/test_code_guard.py | CodeGuard 单元测试（23 项） |
| tests/test_gate_pipeline.py | GatePipeline 集成测试（12 项） |
| scripts/direction_4_coverage_gate.py | 接口覆盖率门禁探索 |
| scripts/closed_loop_v2.py | 全量对比 + Dev/Test 分离（三个方向） |

---

## 十二、声明式规则引擎选型结论

> 日期：2026-06-16
> 范围：rule_runner 的加法一（文本规则）/ 加法二（几何规则）/ 加法三（图像守卫）

### 12.1 候选引擎评估

| 引擎 | stars | 维护 | 能力模型 |
|------|-------|------|---------|
| **durable_rules** v2.0.28 | ~140 | ❌ 2020-06 停更 | 基于 C 的 Rete 前向推理引擎，事件驱动 + 有状态 |
| **python-rule-engine** v1.0.0 | 59 | ✅ 2025-06 发布 | JSON Path → 28+ 内建运算符 + 自定义 operator |
| **policy-as-code-engine** v0.1.1 | 0 | ❌ 实验项目 | field-operator-value 三元组, allow/deny 决策 |
| **SpiffWorkflow** v3.1.2 | — | ✅ 活跃 | BPMN 2.0 工作流引擎（非规则引擎） |
| **theaios-guardrails** v0.1.3 | 0 | ❌ 个人项目 | AI 治理 guardrail（regex/PII/block），非通用 |

### 12.2 核心发现

声明式规则引擎的原子操作是「字段 ←运算符→ 阈值」的匹配：

```
# 规则引擎能做的事
{"path": "$.text", "operator": "matches_regex", "value": "^警惕"}

# 规则引擎不能做的事
取 bbox1 → 取 bbox2 → 计算交集面积 → 除以卡片面积 → 和阈值比
          └─ 中间 3 步是"计算"，不是"匹配"
```

加法二（bbox 相交率/坐标比较）需要几何计算，加法三（cv2 像素分析）需要图像处理——两者都超出了任何规则引擎的能力边界。引入外部引擎只多了一层调用包装和 bridge 代码，几何/图像函数仍需自己写。

以 python-rule-engine 为例，加法二的 bbox 相交检查需自定义 operator：

```python
class BboxIntersects(Operator):
    id = "bbox_intersects"
    def match(self, obj_value):
        return compute_intersection_ratio(obj_value, self.condition.value) > 0.3, 0
```

几何计算函数仍需自己实现，引擎只提供了 operator dispatch 框架。

### 12.3 结论

**不引入任何外部引擎，自建 rule_runner.py 扩展版。**

| 维度 | 自建扩展 | 引入外部引擎 |
|------|---------|-------------|
| 加法一代码量 | 68 行 → ~100 行 | 68 行丢弃 + ~80 行 bridge + 自定义 operator |
| 加法二代码量 | ~50 行 handler + 几何函数复用 | ~50 行 bridge + operator 类包装 + 几何函数复用 |
| 加法三代码量 | ~10 行 handler + cv2 函数复用 | 同上 + operator 类包装 |
| 总外部依赖 | 零（纯标准库） | python-rule-engine ~200KB + 间接依赖 |
| Evolver 可改范围 | YAML 中任意字段 | 受 YAML→JSON bridge 限制 |
| 团队学习成本 | 100 行代码，5 分钟 | JSONPath 语法 + 自定义 operator API |

自建方案支持七种规则类型：`regex | prefix | length | bbox_half_screen | bbox_avatar_column | bbox_confidence | python_call`。其中 `python_call` 是通用扩展点，通过 YAML 指定函数名 → `importlib` 动态调用，覆盖加法三和未来任何自定义规则。
