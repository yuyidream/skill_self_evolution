# 产品需求说明书（PRD）

> 本文件为项目产品需求说明书模板。
>
> **使用说明**：基于脚手架创建业务项目后，在此文件中编写具体的产品需求。
>
> **安全要求**：本文件已添加到 `.gitignore`，不会上传到 GitHub。

> **安全要求**：新项目的第一件事，请为新项目新建数据库（里面的表和字段可复用，但必须是新库）并删除项目里原有数据库所有信息，避免修改其它项目的数据库。

---

## 修订记录

| 版本号 | 修订日期 | 修订内容 | 需求提出人 | 产品经理 | 备注 |
|--------|----------|----------|------------|----------|------|
| V 0.1  |          | 新建     |            |          |      |

---

## 1. 项目概述

### 1.1 项目背景

公司


### 1.2 项目目标

（在此描述项目目标）

### 1.3 项目范围



---

## 2. 功能需求

### 2.1 功能模块总览

| 序号 | 模块名称 | 功能描述 | 优先级 |
|------|----------|----------|--------|
| 1    |          |          |        |

### 2.2 功能详细描述



#### 2.2.1 产品架构（各系统之间的交互）


架构图

```
┌───────────────────────────────┐  ┌───────────────────────────────────┐
│  数据处理规则结果判断            │  │  prompt结果判断                     │
│  Skill A: nickname-selector    │  │  Skill B: match-scorer             │
│  Skill C: speaker-structurer   │  │                                    │
│                                │  │  AI 按 prompt 返回语义分 (0-22)     │
│  候选池 → 规则引擎 → 最终数据    │  │         ↓                          │
│         ↓                      │  │  H5 页面展示匹配结果                │
│  AI 验证 → 不合理 → AI 重选     │  │         ↓                          │
│         ↓                      │  │  用户反馈「匹配不正确」              │
│  JSONL (is_failure)            │  │         ↓                          │
│                                │  │  wx_match_feedback 表              │
└───────────────┬────────────────┘  └───────────────┬───────────────────┘
                │                                   │
                │  JSONL 日志                        │  用户负面反馈
                ▼                                   ▼
┌───────────────────────────────────────────────────────────────────────┐
│                          Evolver（离线进化）                            │
│                                                                        │
│  上游1: JSONL (数据处理规则结果判断)                                      │
│         → DeepSeek 分析 → 优化 rules_config.yaml → benchmark 验证        │
│                                                                        │
│  上游2: wx_match_feedback (prompt结果判断)                               │
│         → DeepSeek 分析 → 优化 prompt.yaml → 人工确认                     │
│         → 同时可优化 rules_config 每维度分值 (full_score/penalty)          │
└───────────────────────────────────────────────────────────────────────┘
```

文字描述

框架有两条并列的上游链路，共同接入 Evolver（离线进化）：

**上游1：数据处理规则结果判断**（Skill A: nickname-selector / Skill C: speaker-structurer）。调用方提供候选池数据（candidates），SkillExecutor 管线的规则阶段通过声明式规则引擎（rules_config.yaml）+ 薄执行层（run.py）从候选池中筛选并产出 result（规则确认的最终数据）。若 AI 验证（DeepSeek 按 prompt.yaml 常识判断）判定 result 不合理，则从候选池中重选最佳替代，并写 JSONL 日志标记 `is_failure=true`。Evolver 读取 JSONL 失败案例，经 DeepSeek 分析后优化 rules_config.yaml，通过 benchmark 确定性对比决定自动接受或回滚。

**上游2：prompt结果判断**（Skill B: match-scorer）。AI 按 prompt 对简历-订单匹配进行语义评分（0-22 分），结果在 H5 页面展示。用户点击「匹配不正确」（可选补充不正确的原因）后写入 wx_match_feedback 表。Evolver 读取用户负面反馈，经 DeepSeek 分析后优化 prompt.yaml（需人工确认，因 prompt 结果具有概率性），同时可优化 rules_config 中各维度的分值与权重。

| | 上游1: 数据处理规则结果判断 | 上游2: prompt结果判断 |
|---|---|---|
| 适用范围 | Skill A / C | Skill B |
| 失败信号 | AI 纠正了规则输出 → JSONL | 用户点击「匹配不正确」 → wx_match_feedback |
| 信号来源 | 机器（AI 自我检测） | 人类（H5 用户反馈） |
| Evolver 优化 | rules_config.yaml | prompt.yaml + rules_config 维度分值 |
| 写入方式 | 自动 + benchmark 回滚 | 规则数值自动，prompt 人工确认 |




#### 2.2.2 功能一




---

## 3. 非功能需求

### 3.1 性能需求

每天1000人访问


### 3.2 安全需求

使用华为云安全相关功能


### 3.3 可用性需求

系统稳定，99.9%的时间可访问

---
### 3.3 分阶段实施安排

实施计划

**一期：路径 1（数据处理规则结果判断 → JSONL → Evolver）**

路径 1 基本通车，需补两个洞即可形成完整闭环。

已实现部分：

- JSONL 写入 — Skill A/C（correction 角色）会写 `is_failure=true`

```
def _compute_is_failure(ai_role, rule_output, ai_validation, ai_reselection) -> bool:
    if ai_role == "enhancement":
        return False  # ← Skill B 永远不写 is_failure
    if ai_role == "correction":
        if ai_validation and ai_validation.result == "不合理":
            return True
        if ai_reselection and ai_reselection.result == "不合理":
            return True
        // ...
```

- Evolver 读 JSONL — 已实现

```
failures = self._load_failure_logs(date_str)
proposal.failure_count = len(failures)
```

- Evolver 改 YAML — 框架已实现 `_apply_rules_changes` + `_apply_prompt_changes`
- Evolver benchmark 验证 — 框架已实现前/后对比 + 退化自动回滚
- **配置版本管理** — MySQL 双表 `skill_config`（当前版本）+ `skill_config_history`（全量历史），`save()` 写入时自动递增 version 并归档旧版，`rollback(v)` 按版本号恢复。每次替换自动留档，不丢历史。

待补：

| 改动 | 说明 |
|---|---|
| `_apply_rules_changes` 升级 deep-merge | 当前只处理 int/float，需支持列表项增删（复用已有 `_deep_update`） |
| Skill A benchmark() 填充真实案例 | 64 条真实案例（已有 `real_failure_cases.json`），跑完整规则引擎验证 |
| Skill C benchmark() 填充真实案例 | M 条已标注原文，验证正则提取正确率 |
| Skill A run.py 读 rules_config 声明式规则 | 薄执行层消费 rejection_rules 做过滤 |
| Skill B run.py 每维度分值为 YAML 可配置 | full_score / penalty 从 rules_config 读取 |
| `evolve.toml` mode `threshold_only` → `full` | 允许 Evolver 增删非数值规则 |

**二期：路径 2（prompt结果判断 → wx_match_feedback → Evolver）**

路径 2 上游（H5 反馈 → MySQL）已实现，Evolver 端完全缺失。

已实现部分：

- wx_match_feedback 表

```
CREATE TABLE IF NOT EXISTS `wx_match_feedback` (
  `id`            BIGINT        NOT NULL AUTO_INCREMENT,
  `match_id`      BIGINT        NOT NULL,
  `source_md5`    VARCHAR(64)   NOT NULL,
  `match_score`   DECIMAL(5,1)  DEFAULT NULL,
  `feedback_type` VARCHAR(20)   NOT NULL DEFAULT 'match_incorrect',
  `match_direction` TINYINT     NOT NULL DEFAULT 1,
  `human_verdict` TINYINT       DEFAULT NULL,   -- 0=合理 1=不合理
  `human_note`    TEXT          DEFAULT NULL,
  ...
```

- H5 反馈 API：`POST /feedback/match_result` — 已可用

完全缺失（Evolver 端）：

Evolver 当前只有一个 `evolve()` 方法，只读 JSONL，无 MySQL 依赖，无读取用户反馈的代码路径。

待新增：

| 新增 | 说明 |
|---|---|
| Evolver MySQL 依赖 | 当前 Evolver 纯文件系统操作，需引入 DB 连接 |
| `Evolver._load_user_feedback()` | 从 wx_match_feedback 表读 `feedback_type='match_incorrect'` 记录 |
| `Evolver._analyze_feedback_failures()` | 聚合用户负面反馈 → DeepSeek 分析 → prompt_changes |
| `evolve_prompt()` 方法 | 只优化 prompt，不触发 benchmark 确定性对比（prompt 具有概率性） |
| 人工确认机制 | prompt 改动无法确定性验证，需管理后台人工审核后合并 |

| 对比维度 | 路径 1 (JSONL) | 路径 2 (wx_match_feedback) |
|---|---|---|
| 上游数据生成 | ✅ 已实现 | ✅ 已实现（H5 API + 表） |
| Evolver 读数据 | ✅ 已实现 | ❌ 完全缺失 |
| Evolver 分析 | ✅ 已实现 | ❌ 完全缺失 |
| Evolver 改配置 | ⚠️ 仅 int/float | ❌ 完全缺失 |
| Evolver 验证 | ⚠️ benchmark 空桩 | ❌ 不适用（需人工确认） |

---

### 3.4 路径 1 执行计划（一期）

#### 3.4.1 总目标

完成"候选池 → 声明式规则引擎 → result → AI 验证 → 不合理 → 重选 → JSONL → Evolver 分析 → 优化 rules_config.yaml → benchmark 验证 → 自动接受/回滚"的完整闭环。

#### 3.4.2 前置条件

| 条件 | 状态 | 说明 |
|---|---|---|
| SkillExecutor 完整管线 | ✅ 已实现 | execute → validate → reselect → JSONL 就绪 |
| Evolver 读 JSONL + DeepSeek 分析 | ✅ 已实现 | `_load_failure_logs` + `_analyze_failures` |
| Evolver benchmark 框架 | ✅ 已实现 | 前/后对比 + 退化自动回滚 |
| `_apply_rules_changes` deep-merge | ❌ 待改 | 当前仅处理 int/float |
| 薄执行层 `rule_runner.py` | ❌ 待新建 | 通用规则遍历引擎 |
| Skill A run.py 消费 rules_config | ❌ 当前不读 | 需对接声明式规则 |
| Skill A rules_config.yaml | ❌ 当前无声明式规则 | 需补充 rejection_rules |
| Skill A / C benchmark() | ❌ 当前空桩 | 需填充真实案例 |
| `evolve.toml` mode | ❌ 当前 threshold_only | 需放开为 full |

#### 3.4.3 执行步骤

| 序号 | 步骤 | 文件 | 改动说明 | 预估工作量 | 依赖 |
|---|---|---|---|---|---|
| 1 | `_apply_rules_changes` 升级 | `evolver.py` | 用 `_deep_update` 替换正则数值替换，支持列表项增删、嵌套 dict 修改 | ~10 行 | — |
| 2 | 新增 `rule_runner.py` | `skill_self_evolution/rule_runner.py` | 通用函数：遍历规则链，执行 regex/prefix/length 匹配 + drop/remove_prefix 动作 | ~30 行 | — |
| 3 | Skill A run.py 对接规则 | `skill/nickname-selector/scripts/run.py` | `_rule_extract()` 增加：读 `config["rules_config"]["rejection_rules"]`，对每条 candidate 调 `rule_runner` 过滤 | ~20 行 | 2 |
| 4 | Skill A rules_config 补充 | `skill/nickname-selector/rules_config.yaml` | 新增 `rejection_rules` 列表（正则/前缀/长度），覆盖现有 `system_prefix_drops` | 纯配置 | — |
| 5 | Skill A benchmark 填充 | `skill/nickname-selector/scripts/run.py` | 读 `real_failure_cases.json`（64 条），调 `execute()` 跑完整链路，统计通过数 | ~30 行 | 3 |
| 6 | Skill C benchmark 填充 | `skill/speaker-structurer/scripts/run.py` | 预置 M 条已标注原文 + 期望字段，验证提取正确率 | ~30 行 | — |
| 7 | evolve.toml mode → full | Skill A / C 的 `evolve.toml` | `mode = "threshold_only"` → `"full"` | 1 行 | 1 |
| 8 | 端到端集成测试 | 测试脚本 | 造 JSONL → 跑 Evolver → 验 YAML 变更 → 验 benchmark 通过/回滚 | ~40 行 | 1-7 |
| 9 | 切回 pip 安装 | `pip install .` | 全量验证通过后，从 editable `-e` 切回 `pip install .`，确保生产环境使用固化的包副本 | 1 条命令 | 8 |

#### 3.4.4 依赖关系图

```
步骤1 (deep-merge)
  │
步骤2 (rule_runner.py)
  │
  ├──→ 步骤3 (Skill A 对接) ──→ 步骤5 (Skill A benchmark)
  │
  ├──→ 步骤4 (Skill A YAML)
  │
  └──→ 步骤6 (Skill C benchmark)  ← 与 3/4/5 可并行
           │
步骤7 (evolve.toml)  ← 依赖 1
  │
步骤8 (端到端测试)  ← 依赖 1-7 全部
  │
步骤9 (切回 pip 安装)  ← 依赖 8
```

#### 3.4.5 验收标准

| 编号 | 验收项 | 通过标准 | 关联步骤 |
|---|---|---|---|
| V1 | deep-merge 列表项增删 | 给定旧 YAML 含 `rejection_rules: [a, b]`，`changes = {"rejection_rules": [a, b, c]}`，合并后 YAML 含 `[a, b, c]` | 1 |
| V2 | deep-merge 嵌套值修改 | 给定 `nickname_thresholds.min_confidence: 0.7`，`changes = {"nickname_thresholds": {"min_confidence": 0.85}}`，合并后值为 0.85，其他字段不变 | 1 |
| V3 | deep-merge 保留注释 | 合并后 YAML 中方原有注释不丢失 | 1 |
| V4 | rule_runner 正则过滤 | `run_rejection_rules("警惕不实营销信息", [{type: regex, pattern: "^警惕", action: drop}])` → `None` | 2 |
| V5 | rule_runner 前缀去除 | `run_rejection_rules("姓名：张三", [{type: regex, pattern: "^姓名[：:]", action: remove_prefix}])` → `"张三"` | 2 |
| V6 | rule_runner 链式执行 | 输入 `"姓名：@test"`，依次过 remove_prefix → prefix drop，最终 → `None` | 2 |
| V7 | Skill A 规则引擎生效 | 64 条真实案例，拒绝规则生效后"安全横幅""简历碎片"类 nickname 不再作为 result | 3+4 |
| V8 | Skill A 手动新规则提升通过数 | 对 64 条案例手动写入一条新拒绝规则（如过滤时间戳格式 `\d{4}年\d{1,2}月`），benchmark 通过数应上升 | 3+4+5 |
| V9 | Skill A benchmark 返回值正确 | `benchmark(evolver)` 返回 `(pass_count, 64, [...failures])`，`pass_count > 0` 且 `total_count = 64` | 5 |
| V10 | Skill C benchmark 返回值正确 | `benchmark(evolver)` 返回 `(pass_count, total, [...])`，`total_count > 0` | 6 |
| V11 | Evolver rules_changes deep-merge | Evolver 对 JSONL 分析后生成的 `rules_changes` 能正确 deep-merge 到 YAML（含列表项增删） | 1+8 |
| V12 | Evolver 自动写入 | dry_run=False 时，rules_changes 成功写入 MySQL（rules_config.yaml 内容变更） | 1+8 |
| V13 | Evolver 退化回滚 | 故意写入一条会导致 pass_after < pass_before 的坏规则 → 自动 rollback → proposal.rolled_back = True | 8 |
| V14 | Evolver 正常接受 | 写入一条提升通过数的规则 → proposal.applied = True | 8 |
| V15 | pip 安装固化 | `pip install .` 成功后 `pip show skill_self_evolution` 指向 site-packages（非 E:\projects\skill_self_evolution） | 9 |

#### 3.4.6 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| ruamel.yaml round-trip 在 `_deep_update` 合并后可能丢注释 | V3 失败 | 步骤 1 完成后单独验证 V3，若不通过则换用 ruamel 的 `CommentToken` API |
| Skill A 的 `real_failure_cases.json` 依赖本地 session 目录存在 | V7/V8 因文件缺失无法跑 | `execute()` 增加文件不存在的容错（返回错误标记），benchmark 统计中计入 |
| Skill C 没有现成标注数据 | V10 需从零造数据 | 从已有 speaker JSON 中手工标注 M=20 条优先 |
