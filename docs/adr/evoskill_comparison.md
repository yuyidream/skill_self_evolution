# ADR: skill_self_evolution vs EvoSkill (sentient-agi) — 对比评估

> 状态：评估完成
> 日期：2026-06-16
> 结论：保持独立，不引入 pip EvoSkill 作为依赖

---

## 一、背景

`skill_self_evolution` 最初受 EvoSkill（https://github.com/sentient-agi/EvoSkill）的自进化理念启发，在此基础上针对家政匹配业务场景进行了完整的重写。本 ADR 记录两边的详细对比，明确哪些是概念继承、哪些是自主创新、哪些是 EvoSkill 有而我们尚未复用的。

---

## 二、总体架构对比

| 维度 | EvoSkill (sentient-agi) | skill_self_evolution (我们的) |
|---|---|---|
| **形态** | CLI 工具，`evoskill init/run` | Python 库，嵌入应用通过 APScheduler 调用 |
| **进化对象** | coding agent 的 system prompt + skills 文件 | 业务规则 YAML（rejection_rules / geometry_rules / confidence 阈值 / prompt） |
| **数据来源** | CSV（question/answer pairs）+ 分类均衡采样 | MySQL JSONL 失败日志（`is_failure=true`） |
| **评分机制** | Benchmark 打分（`multi_tolerance` / `exact` / `llm` / `harbor`） | 注入式 `benchmark_fn`（业务自行定义，如昵称准确率） |
| **版本管理** | Git 分支（`program/iter-skill-N`）+ `frontier/*` tags | VersionManager + `wx_version_activation` + 磁盘 `rules_config_vN.yaml` |
| **调用方式** | 开发者 CLI + Python API（`EvoSkill(...).run()`） | `Evolver(skill_name=...).evolve()` 库内调用 |
| **依赖规模** | 10+ 外部依赖（claude-agent-sdk, opencode-ai, harbor, daytona 等） | 5 个核心依赖（pydantic, httpx, pymysql, ruamel.yaml, structlog） |

---

## 三、进化核心机制逐项对比

### 继承项（概念层面，共 3 项）

| # | 机制 | EvoSkill | skill_self_evolution | 继承程度 |
|---|---|---|---|---|
| 1 | 五步循环骨架 | Base Agent → Proposer → Generator → Evaluator → Frontier | 读日志 → DeepSeek 分析 → 生成提案 → benchmark 安全网 → 写入/回滚 | ✅ 概念 |
| 2 | 失败样本 → LLM 分析 → 提案 | 多个 Agent 分散执行 | 一次 DeepSeek 调用合并完成 | ✅ 概念 |
| 3 | 进化角色控制 | `evolution_mode: skill_only/prompt_only` | `ai_role: correction/enhancement`（enhancement 不触发进化） | ✅ 简化 |

### 自主创新项（共 6 项）

| # | 创新项 | 说明 | EvoSkill 是否有 |
|---|---|---|---|
| 1 | VersionManager + 磁盘版本文件 | Git 分支 → `rules_config_vN.yaml` + `wx_version_activation` | ❌ EvoSkill 用 Git |
| 2 | **自动回滚安全网** | Post-benchmark 分数退步 → `rollback()` 恢复上一版本 | ❌ EvoSkill 只有 discard，无回滚 |
| 3 | `min_failure_samples` 门控 | 失败样本不足 10 条跳过本轮进化 | ❌ EvoSkill 无样本量判断 |
| 4 | YAML deep-merge 应用变更 | `ruamel.yaml` 递归合并 + 数值漂移告警 | ❌ EvoSkill 直接写文件 |
| 5 | YAML lint 校验 | `lint_and_fix_yaml()` 写入前自动修复 | ❌ EvoSkill 无校验 |
| 6 | Pydantic 入口校验 | `EvolveTomlModel` / `EvolvePromptYamlModel` 配置入口校验 | ❌ EvoSkill 无 |

### EvoSkill 有但我们尚未复用的（共 6 项）

| # | 功能 | 说明 | 是否值得复用 |
|---|---|---|---|
| 1 | **反馈历史学习** (`feedback_history.md`) | 记录每轮 proposal + outcome + score，Proposer 可学习历史 | ⚠️ 值得评估（见 §六） |
| 2 | 采样状态 Checkpoint 继续 | 中断后恢复精确状态 | 暂不需要 |
| 3 | 并发样本执行 | `asyncio.gather` 并发测试 | 单线程当前够用 |
| 4 | Frontier top-N 策略 | 保留多个高分程序，而非只保留一个 | 策略不同，不适用 |
| 5 | Progress 事件发射 (`on_event`) | 供 CLI 进度表实时显示 | 无人机交互需求 |
| 6 | 运行缓存 (`RunCache`) | 缓存 agent API 请求 | 不需要 |

---

## 四、功能利用率：引入 pip EvoSkill 后

| 指标 | 数值 |
|---|---|
| EvoSkill 总功能点 | 34 项 |
| 我们需要且能用的 | 0 项 |
| 实际利用率 | **0%** |
| 附带无用依赖 | ~120 MB（claude-agent-sdk, opencode-ai, harbor, daytona, pandas 等） |

### 不用的核心原因

1. **EvoSkill 为 coding agent benchmark 设计**（SWE-bench, SealQA），不是业务规则进化
2. **数据结构完全不同**：CSV/Harbor vs MySQL JSONL
3. **评分体系完全不同**：benchmark 打分 vs 业务准确率
4. **输出目标完全不同**：.claude/skills/*.md 文件 vs VersionManager 版本文件 + MySQL 执行日志
5. **调用模式完全不同**：CLI vs 库内调用

---

## 五、结论

**保持独立，不引入 `pip EvoSkill` 作为依赖。**

真正的代码复用为 0，概念复用约 3 项。强制嫁接会引入 120MB+ 无用依赖，且需要大量适配层把 EvoSkill 的 CSV/Harbor/Git 体系转化为我们的 MySQL/YAML/业务评测体系。成本远高于收益。

---

## 六、待评估项 → 已实施

| # | EvoSkill 功能 | 评估结果 | 状态 |
|---|---|---|---|
| 1 | 反馈历史学习 | 值得复用，已实施 | ✅ 已实施 |
| 2 | OpenCode harness 写代码自动进化 | 已跑通，参见 `opencode_harness_assessment.md` | ✅ 已实施 |
| 3 | prompt 自动进化增强 | 已有基础，已增强 | ✅ 已实施 |
