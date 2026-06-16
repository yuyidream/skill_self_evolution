# skill_self_evolution v0.3.0

Skill 自进化框架：**Pydantic 全链路校验** + 规则执行 + AI 常识判断 + 离线进化 + **AI 生成代码质量门禁**的可插拔 Skill 执行引擎。

## v0.3.0 更新

- **CodeGuard**：基于 Python AST 的 6 条内置代码检查规则（裸 except / 圈复杂度 / global / 日志在循环 / 吞异常 / 非确定性导入）
- **FunctionContext**：AST 自动提取函数上下文（is_method / 可用变量 / 禁止变量），替代人工硬编码变量清单
- **GatePipeline**：4 层代码门禁管道 — 静态检查 → 单元测试 → 集成测试 → 生产候选数据回放
- 每层失败 → 错误信息喂回 AI → AI 重写 → 重新过门禁（最多 3 轮）

## v0.2.0 更新

- **Pydantic 全链路覆盖**：12 个源文件，8 个完整 Pydantic 校验（4 个有理据豁免）
- 新增 11 个 Pydantic 模型，覆盖 AI 中间结果、DeepSeek 响应、JSONL 日志、降级配置、进化提案、Skill 子结构

## 架构

```
输入 (SkillInput)       规则执行              AI 校验           AI 重选            日志 & 进化
  input_data     →    execute()     →    _ai_validate()  →  _ai_reselect()  →  JSONL + Evolver
    │                     │                   │                  │                  │
    └─ Pydantic ✅        └─ SkillOutput ✅    └─ AiValidation   └─ AiReselection   └─ LogEntry/Proposal
                                                 Result ✅          Result ✅            ✅
```

### Evolver 生成新代码时的 4 层门禁

```
AI 生成代码 → Layer 1 静态检查 → Layer 2 单元测试 → Layer 3 集成测试 → Layer 4 生产回放
       ↑              ↓                ↓                 ↓                ↓
       └────────── 失败反馈 ───────────┴─────────────────┴────────────────┘
```

## CodeGuard 快速使用

```python
from skill_self_evolution import CodeGuard

guard = CodeGuard(max_complexity=10)
passed, issues = guard.gate("path/to/code.py")

for i in issues:
    print(f"[{i.level}] {i.rule}: {i.message} @ {i.file}:{i.line}")
```

### AST 上下文自动提取

```python
from skill_self_evolution import extract_context

ctx = extract_context("path/to/code.py", "my_function")
print(ctx.is_method)     # False
print(ctx.local_vars)    # ['cx', 'cy', 'result', ...]
print(ctx.context_for_prompt())  # AI 可注入 prompt
```

### 6 条内置规则

| 规则 | 说明 | 级别 |
|---|---|---|
| `no_bare_except` | 禁止裸 `except:` | error |
| `cyclomatic_complexity` | 圈复杂度 ≤ 10 | error |
| `no_global_modification` | 禁止模块级函数用 `global` | error |
| `no_logging_in_loop` | 禁止 for/while 内调用 logging | warning |
| `no_exception_swallowing` | 禁止 `except: pass` / 空 handler | error |
| `no_nondeterministic` | 禁止 `import random` / `time.time` / `datetime.now` | error |

### 自定义 Checker

```python
from skill_self_evolution.code_guard import BaseChecker, CodeGuard

class NoPrintInProd(BaseChecker):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            self._add("no_print", "warning", "print() in production", node)

guard = CodeGuard()
guard.register("no_print", NoPrintInProd)
```

## GatePipeline 快速使用

```python
from skill_self_evolution import GatePipeline

pipeline = GatePipeline(max_complexity=10)

result = await pipeline.run(
    filepaths=["backend/skill_service/run.py"],
    unit_test_path="tests/test_skill.py",
    e2e_test_path="tests/test_e2e.py",
    candidate_replay_fn=my_replay_function,
    backend_dir=".",
)
print(f"Passed: {result.passed}, Layers: {len(result.layers)}")
```

## 安装

```bash
pip install skill_self_evolution
```

## 开发

```bash
# 本地安装（开发模式）
pip install -e .

# 运行测试
pytest

# 只跑 CodeGuard 测试
pytest tests/test_code_guard.py -v

# 只跑 GatePipeline 测试
pytest tests/test_gate_pipeline.py -v
```

## 环境变量

| 变量 | local 默认 | test/prod 默认 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 官网 Key | — |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1` | — |
| `WX_MATCH_DEEPSEEK_API_KEY` | — | 华为云 MaaS Key |
| `WX_MATCH_DEEPSEEK_API_BASE` | — | `https://api.modelarts-maas.com/v2` |
| `APP_ENV` | `local` | `test` / `prod` |
| `DB_HOST` | `127.0.0.1` | 环境注入 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `root` / (空) / `housekeeping_ai_match_dev` | 同上 |
| `SKILL_BASE_DIR` | `backend/config/services/skill/` | 同上 |
| `SKILL_LOG_DIR` | `/data/skill-logs` | 同上 |

## License

MIT
