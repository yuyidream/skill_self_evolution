# skill_self_evolution

Skill 自进化框架：统一规则执行 + AI 常识判断 + 离线进化的可插拔 Skill 执行引擎。

## 安装

```bash
pip install skill_self_evolution
```

## 环境变量

| 变量 | local 默认 | test/prod 默认 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 官网 Key | — |
| `DEEPSEEK_API_BASE` | `https://api.deepseek.com/v1` | — |
| `WX_MATCH_DEEPSEEK_API_KEY` | — | 华为云 MaaS Key |
| `WX_MATCH_DEEPSEEK_API_BASE` | — | `https://api.modelarts-maas.com/v2` |
| `DB_HOST` | `127.0.0.1` | 环境注入 |
| `SKILL_BASE_DIR` | `backend/config/services/skill/` | 同上 |

## 快速开始

```python
from skill_self_evolution import SkillExecutor

executor = SkillExecutor(
    deepseek_api_key="sk-xxx",  # 或设置 DEEPSEEK_API_KEY
    skill_base_dir="/path/to/skills",
)
result = await executor.run("nickname-selector", {"data": "..."})
```
