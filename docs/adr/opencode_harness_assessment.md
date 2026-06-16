# ADR: OpenCode harness 写代码自动进化 — 可行性评估

> 状态：**可行**（2026-06-16 EvoSkill harness 实测通过）
> 日期：2026-06-16

---

## 一、方法

不调用 OpenCode CLI `run` 命令，直接复用 EvoSkill 的 Python harness：

1. **复制** `EvoSkill\src\harness\` → `skill_self_evolution\src\skill_self_evolution\harness\`
2. **最小依赖**：仅需 `schemas.py`（`AgentResponse` Pydantic model）
3. **调用方式**：`execute_query(options, prompt)` → 内部管理 `opencode serve` 生命周期 + HTTP API

```python
from skill_self_evolution.harness.opencode.executor import execute_query

options = {
    "provider_id": "deepseek",
    "model_id": "deepseek-chat",
    "mode": "build",
    "cwd": str(backend_path),
    "system": "You are a Python code fixer...",
}
result = await execute_query(options, prompt)
```

---

## 二、实测结果

**方向1+2（闭环修复）：第1轮成功**

```
--- Round 1/3 ---
  AI: 794 chars, code=yes
  E2E: PASSED
  Replay: OK|bindings=0|orphan=2

  BASELINE PASSED in 1 round(s)
```

对比 `closed_loop_v2.py`（手写 DeepSeek 客户端，639 行），harness 版本只需要 ~30 行 AI 调用代码。

---

## 三、注意事项

| 问题 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | 需要有效的 API key，直接配置环境变量即可，不走 OpenRouter 中转 |
| `opencode serve` 启动 | 每进程首次 5-10s，后续调用复用同一 serve 进程 |
| Windows `os.kill(pid, 0)` | 非功能性，仅 atexit 清理报错，可忽略 |
| AI 输出质量 | prompt 需明确要求格式（如 "Output ```python``` ONLY. No function def."） |
| 文件备份 | 用独立 `.bak` 文件，避免模块级变量被运行时修改污染 |
| 代码提取 | 仅接受 ` ```python ``` ` 围栏块，拒绝非代码文本和过短片段（<50 字符） |

---

## 四、两种方案定位

| 维度 | EvoSkill Harness | Cursor Agent |
|---|---|---|
| 调用方式 | `execute_query()` 异步函数 | 对话交互 |
| 代码编辑 | AI 输出文本，脚本写入 | 内置 Edit/Write |
| 多轮反馈 | 脚本编排 | Agent 自动重试 |
| 可编程性 | 完全可编程（脚本/CI） | 依赖对话上下文 |
| 适用场景 | 自动化闭环/批量修复 | 交互式修复/探索 |

---

## 五、方向3（Dev/Test 分离）实测结果

方向3 经过三轮迭代改进后达到第1轮成功：

| 版本 | 关键改动 | 结果 |
|---|---|---|
| v1 | 静态严格检查，2轮 | ❌ 全部卡在静态分析 |
| v2 | 宽松检查 + 降级，5轮 | ❌ 5轮全部失败 |
| **v3** | **coach 模式 + 反馈历史累积** | ✅ **第1轮通过** |

v3 的两个关键改进直接来自 EvoSkill：

1. **反馈历史累积**：Dev 每轮看到所有历史尝试 + 失败原因（`DO NOT repeat these mistakes`），从不重复犯同样错误
2. **Coach 模式**：Test 输出 `FIX: <具体指令>` 而非模糊的 `FAIL`，Dev 知道确切怎么改

```
DIRECTION 3: Dev/Test Separation (max 5 rounds, feedback history)
--- Round 1/5 ---
  Dev: 806 chars, code=yes
  Test static: PASS
  E2E: PASSED
  Replay: PASSED

  DIRECTION 3 SUCCESS in 1 round(s)
```

---

## 六、复用的 EvoSkill 模块

| 文件 | 来源 | 改动 |
|---|---|---|
| `feedback_descent.py` | 直接复制 | 无（零外部依赖），加 structlog 日志 |
| `loop_config.py` | `loop/config.py` | 去除 EvoSkill 特定字段（harness / benchmark），改为通用进化配置 |
| `feedback_history.py` | `loop/helpers.py` | 提取 `append_feedback` + `read_feedback_history`，去除 harness 依赖，加 structlog 日志 |
| `run_cache.py` | `cache/run_cache.py` | 去除 `AgentTrace` / `pydantic` 依赖，改为纯 JSON 键值缓存，加 structlog 日志 |
| `parallel_eval.py` | `evaluation/evaluate.py` | 去除 `Agent` / `tqdm` 依赖，提供通用 `run_parallel`，加 structlog 日志 |
| `harness/` | `src/harness/`（整个目录） | 直接复制，仅加 `schemas.py` |
| `logging.py` | 自建 | structlog 统一日志配置，支持 `STRUCTLOG_JSON=true` 切换 ConsoleRenderer / JSONRenderer |

**日志规范**：所有模块统一使用 `structlog`(`stdlib` 绑定)，通过 `from skill_self_evolution.logging import get_logger` 获取。开发环境默认 ConsoleRenderer（彩色）；设置 `STRUCTLOG_JSON=true` 切换 JSONRenderer 输出单行 JSON 日志。

### 6.1 structlog 日志样例

开发环境（ConsoleRenderer，默认）：
```
2026-06-16T13:37:02Z [info     ] feedback_descent.candidate  candidate_len=15 history_size=0 iteration=1
```

结构化输出（JSONRenderer,`STRUCTLOG_JSON=true`）：
```json
{"max_iterations": 5, "no_improvement_limit": 3, "event": "feedback_descent.start", "logger": "skill_self_evolution.feedback_descent", "level": "info", "timestamp": "2026-06-16T13:37:02.370Z"}
{"iteration": 1, "candidate_len": "792", "history_size": 0, "event": "feedback_descent.candidate", "logger": "skill_self_evolution.feedback_descent", "level": "info", "timestamp": "2026-06-16T13:37:02.600Z"}
{"iteration": 1, "preferred": false, "score_best": 1.0, "score_candidate": 1.0, "rationale": "e2e: PASSED; replay: PASSED", "event": "feedback_descent.eval", "logger": "skill_self_evolution.feedback_descent", "level": "info", "timestamp": "2026-06-16T13:37:04.200Z"}
```

### 6.2 3 轮+ 反馈驱动演示

`scripts/demo_feedback_descent.py` 使用 `FeedbackDescent` + DeepSeek AI 真实修复 nickname_ocr_simple.py hallucination 缺陷。

```
DIRECTION 3: Dev/Test Separation (max 5 rounds, feedback history)
--- Round 1/5 ---
  Dev: 806 chars, code=yes
  Test static: PASS
  E2E: PASSED
  Replay: PASSED
  DIRECTION 3 SUCCESS in 1 round(s)
```

当第 1 轮就正确时，FeedbackDescent 自动在第 3 轮（`no_improvement_limit=3`）提前终止。反馈历史（`data/demo_feedback_history.md`）记录每轮尝试，包含 Proposal + Justification + Outcome。日志通过 `STRUCTLOG_JSON` 控制输出格式。

---

## 七、结论

**EvoSkill harness 可以作为 closed_loop 的编程智能体后端**，比手写 DeepSeekClient（639 行 → 30 行）更简洁。两者互补：harness 用于自动化批量场景，Cursor Agent 用于交互式修复。

**日志**：所有模块通过 `structlog`（stdlib 绑定）统一输出，支持开发环境 ConsoleRenderer 和 `STRUCTLOG_JSON=true` 切换 JSONRenderer。
