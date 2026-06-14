# skill_self_evolution v0.2.0

Skill 自进化框架：**Pydantic 全链路校验** + 规则执行 + AI 常识判断 + 离线进化的可插拔 Skill 执行引擎。

## v0.2.0 更新

- **Pydantic 全链路覆盖**：12 个源文件，8 个完整 Pydantic 校验（4 个有理据豁免）
- 新增 11 个 Pydantic 模型，覆盖 AI 中间结果、DeepSeek 响应、JSONL 日志、降级配置、进化提案、Skill 子结构
- `AiValidationResult` / `AiReselectionResult` 用 `Literal["合理","不合理"]` 替代裸 `dict.get("result")`
- `DeepSeekChatResponse` 替代 dataclass，字段缺失自动默认值
- `ConfigVersionManager` 兼容 `dict` 和 `DbConfig` 双路径

## 架构

```
输入 (SkillInput)       规则执行              AI 校验           AI 重选            日志 & 进化
  input_data     →    execute()     →    _ai_validate()  →  _ai_reselect()  →  JSONL + Evolver
    │                     │                   │                  │                  │
    └─ Pydantic ✅        └─ SkillOutput ✅    └─ AiValidation   └─ AiReselection   └─ LogEntry/Proposal
                                                 Result ✅          Result ✅            ✅
```

## Pydantic 模型清单

### 核心框架

| 模型 | 作用 | 校验内容 |
|---|---|---|
| `SkillInput[T]` | 入口 | `trace_id` + `input_data`（泛型） |
| `SkillOutput` | 出口 | `source` + `result` + `ai_validated` + `ai_reselected` |

### AI 中间结果（v0.2.0 新增）

| 模型 | 作用 | 校验约束 |
|---|---|---|
| `AiValidationResult` | AI 验证输出 | `Literal["合理","不合理"]` + reason ≤500字 |
| `AiReselectionResult` | AI 重选输出 | `result: str` + reason ≤500字 |

### 数据层（v0.2.0 新增）

| 模型 | 作用 |
|---|---|
| `DeepSeekChatResponse` | HTTP 响应结构校验 |
| `LogEntry` | JSONL 日志条目（11 字段全默认值容错） |
| `FallbackConfigModel` | 降级参数（gt/ge/le 约束） |
| `EvolveProposalModel` | 进化提案序列化 |
| `NicknameSkillResult` | nickname-selector 子结构示例 |
| `DeepSeekEnvConfig` | API 连接配置 |
| `DbConfig` | 数据库连接配置（port ge=1 le=65535） |

## 快速开始

```python
from skill_self_evolution import SkillExecutor

executor = SkillExecutor(
    deepseek_api_key="sk-xxx",  # 或设置 DEEPSEEK_API_KEY
    skill_base_dir="/path/to/skills",
)
result = await executor.run("nickname-selector", {
    "screenshot_id": "scr_004",
    "metadata_path": "/path/to/metadata.json",
    "debug_session_derived_path": "/path/to/debug_session_derived.json",
})
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
