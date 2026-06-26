# ADR: 反馈历史学习功能复用评估

> 状态：**已实施** ✅
> 日期：2026-06-16
> 实施日期：2026-06-16
> 源：EvoSkill `feedback_history.md` 机制

---

## 一、EvoSkill 的反馈历史机制

EvoSkill 的 `loop/helpers.py` 中实现了一套反馈历史系统：

```python
append_feedback(
    path, iteration_name, proposal, justification,
    outcome="improved" | "discarded",
    score=child_score, parent_score=parent_score,
    active_skills=[...],
)
```

**核心逻辑**：
1. 每轮进化后，无论成功还是失败，都记录一条反馈条目
2. 包含：提案名称、修改理由、结果（improved/discarded）、分数变化
3. 下次 Proposer 分析失败时，`build_proposer_query()` 中注入反馈历史
4. Proposer 可据此避免重复已失败的策略，或参考成功案例

**我们的现状**：
- `_analyze_failures()` 只发送原始失败日志 + 当前配置给 DeepSeek
- DeepSeek 每次都是"从零开始"分析，不知道之前试过什么
- 如果上一轮改了 confidence 阈值但结果退化，下一轮可能再次提出相同的改动

---

## 二、我们已有的基础设施

### 2.1 进化反馈表 `skill_evolution_feedback`

配置版本历史由 housekeeping **VersionManager** 的 `rules_config_vN.yaml` 文件链承担；进化过程摘要写入下表。

```sql
skill_evolution_feedback (
    id, skill_name, evolution_round, outcome, proposal_summary,
    benchmark_before_pass, benchmark_before_total,
    benchmark_after_pass, benchmark_after_total,
    failure_count, analysis_raw,
    version_before, version_after,  -- 对应 VersionManager 激活版本号
    created_at
)
```

该表记录：
- 这次改动提出的 rules_changes / prompt_changes 摘要
- benchmark 前后通过数
- outcome（improved / discarded / rolled_back）
- 进化前后 VersionManager 版本号

**不记录** YAML 全文（全文在磁盘 `rules_config_vN.yaml`）。

### 2.2 Evolver 已有 proposal 数据结构

```python
proposal = EvolveProposal()
proposal.rules_changes = {...}
proposal.prompt_changes = {...}
proposal.failure_count = N
proposal.benchmark_before = (pass, total, failures)
proposal.benchmark_after = (pass, total, failures)
proposal.applied = True/False
proposal.rolled_back = True/False
```

---

## 三、方案设计

### 3.1 新增反馈记录表

```sql
CREATE TABLE IF NOT EXISTS skill_evolution_feedback (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    skill_name      VARCHAR(128) NOT NULL,
    evolution_round INT NOT NULL COMMENT '进化轮次',
    outcome         ENUM('improved','discarded','rolled_back') NOT NULL,
    proposal_summary TEXT COMMENT 'proposal 摘要（rules_changes + prompt_changes）',
    benchmark_before_pass INT DEFAULT 0,
    benchmark_before_total INT DEFAULT 0,
    benchmark_after_pass INT DEFAULT 0,
    benchmark_after_total INT DEFAULT 0,
    failure_count   INT DEFAULT 0,
    analysis_raw    TEXT COMMENT 'DeepSeek 原始分析结果',
    version_before  INT COMMENT '进化前 rules_config 版本号',
    version_after   INT COMMENT '进化后 rules_config 版本号',
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_skill_round (skill_name, evolution_round)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 3.2 在 evolver.py 中注入反馈历史到分析 prompt

现有模版变量：
```
{{skill_name}} / {{current_rules_config}} / {{current_prompt}} / {{failure_logs}}
```

新增变量 `{{feedback_history}}`：

```yaml
analyze_template: |
  Skill：{{skill_name}}

  历史进化反馈（最近 5 轮）：
  {{feedback_history}}

  当前 rules_config：{{current_rules_config}}
  当前 prompt：{{current_prompt}}

  失败案例：
  {{failure_logs}}

  请分析失败模式，注意：
  - 如果历史中已尝试过类似改动且被丢弃，请避免重复
  - 参考成功案例的改动方向，提出新的优化建议
```

### 3.3 变更范围

| 文件 | 改动 | 工作量 |
|---|---|---|
| `config_loader.py` | 新增 `ensure_feedback_table()` + 建表 SQL | ~15 行 |
| `config_loader.py` | 新增 `save_feedback()` / `load_feedback_history()` | ~40 行 |
| `evolver.py` | `_analyze_failures()` 增加 `{{feedback_history}}` 变量替换 | ~15 行 |
| `evolver.py` | `evolve()` 结束后调用 `save_feedback()` | ~20 行 |
| `defaults/evolve_prompt.yaml` | 增加历史反馈段落 | ~10 行 |

**总计**：约 100 行代码

---

## 四、风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 反馈历史越长 → token 开销越大 | 低 | 默认只取最近 5 轮，可配置 |
| 历史偏见 — DeepSeek 被过往失败限制思路 | 中 | 在新一轮样本充足时可选跳过反馈注入 |
| 反馈记录原子性 | 低 | 在 `evolve()` 完成后立即写入，不跨事务 |

---

## 五、结论

**已实施。** 反馈历史是 EvoSkill 中我们最有价值尚未复用的功能。基于 MySQL `skill_evolution_feedback` 表实现了完整的反馈记录和注入链路。DeepSeek 分析时自动参考历史反馈，避免重复已失败策略。

---

## 六、实际实施详情

### 6.1 新增数据库表

```sql
skill_evolution_feedback (skill_name, evolution_round, outcome, proposal_summary,
    benchmark_before/after_pass/total, failure_count, analysis_raw,
    version_before, version_after, created_at)
```

### 6.2 config_loader.py 新增方法

- `ensure_feedback_table()` — 建表（幂等）
- `save_feedback()` — 记录一轮进化反馈（13 个字段）
- `load_feedback_history(skill_name, max_rounds=5)` — 加载最近 N 轮
- `get_next_evolution_round(skill_name)` — 获取轮次号

### 6.3 evolver.py 变更

| 变更点 | 说明 |
|---|---|
| 新增 `_feedback_max_rounds` 参数 | 控制注入到分析 prompt 的历史轮数（默认 5） |
| 新增 `_load_feedback_history()` | 将 MySQL 历史格式化为 `{{feedback_history}}` 文本 |
| 新增 `_build_proposal_summary()` | 从 proposal 提取摘要（rules_changes / prompt_changes 的顶层 key 列表） |
| `_analyze_failures()` | 注入 `{{feedback_history}}` 变量替换 |
| `evolve()` | 获取 evolution_round → 写入后调用 `save_feedback()` |

### 6.4 defaults/evolve_prompt.yaml 变更

- 新增 `{{feedback_history}}` 模板变量
- 新增规则：「若历史反馈中已有类似改动被 discarded 或 rolled_back，不要重复尝试相同方向」
