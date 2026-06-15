# Skill 自进化框架：最终方案 v8

> 状态：方案确定，待实施
> 日期：2026-06-14

---

## 第一部分：方案

### 一、核心理念

```
规则执行 → AI 常识判断 → 合理就过 / 不合理 AI 从原始数据重选 → 日志记录 → 离线进化 → 优化配置
```

---

### 二、统一降级总原则

```
输入非法          → 框架层直接返回 400，不执行业务逻辑
AI 验证失败/超时   → 标记跳过，采信规则结果
AI 重选失败/超时   → 直接返回规则原始结果
AI 全局熔断       → 全链路跳过 AI，纯走规则
保守降级模式       → 可选开关：AI 不可用时标记「需人工复核」而非直接通过
warnings          → 仅用于日志和监控，不阻断流程；业务方可订阅做人工复核队列
```

---

### 三、三个 Skill

| Skill | 输入 | 规则做什么 | AI 做什么 | ai_role |
|-------|------|-----------|----------|---------|
| **A: nickname-selector** | 聊天截图 OCR 数据 | 从 speaker_bands 选昵称候选 | 常识判断→不合理则从 `nickname_candidate` 块中重选 | `correction` |
| **B: match-scorer** | 阿姨简历 + 客户需求 | 公式化匹配评分（58分） | 语义匹配评分（0-22分） | `enhancement` |
| **C: speaker-structurer** | 发言人 JSON | 正则/关键词拆分为字段 | 常识判断→不合理则从发言人 JSON 原文中重新提取 | `correction` |

---

### 四、Skill 目录结构

```
backend/config/services/skill/{skill_name}/
├── skill.md                    ← AI 可读知识文档（Git）
├── scripts/
│   └── run.py                  ← 强制入口，必须导出 execute + benchmark（Git）
├── evolve.toml                 ← 进化权限配置（Git，含 ai_role）
├── evolve_prompt.yaml          ← EvoSkill 分析 prompt（可选，覆盖框架默认）
│
MySQL: skill_config 表
├── rules_config.yaml           ← 阈值/黑名单/正则模式（热加载）
└── prompt.yaml                 ← DeepSeek 提示词模板（热加载）
```

### `run.py` 强制接口

```python
def execute(input_data: SkillInput, config: dict) -> SkillOutput:
    """运行时调用。config 来自 MySQL rules_config.yaml"""

def benchmark(executor) -> tuple[int, int, list]:
    """进化时调用。无数据时返回 (0, 0, [])"""

def summarize_input(input_data) -> dict:
    """可选。生成日志中的 input_summary。未实现则取前 5 个键值对"""
```

### `evolve_prompt.yaml` 加载优先级

```
1. skill/{skill_name}/evolve_prompt.yaml    ← Skill 自定义（优先）
2. skill_engine/defaults/evolve_prompt.yaml  ← 框架默认（降级）
```

---

### 五、Pydantic 输入输出模型

```python
# skill-engine 框架提供

from pydantic import BaseModel, Field
from typing import Generic, TypeVar

T = TypeVar("T")

class SkillOutput(BaseModel):
    """所有 Skill 输出必须继承"""
    source: str = Field(..., description="rule | ai")
    result: dict = Field(..., description="业务结果。各 Skill 差异大，暂不强校验内部结构")
    ai_validated: bool = False
    ai_reselected: bool = False
    warnings: list[str] = Field(default_factory=list, description="仅用于日志和监控，不阻断流程")

class SkillInput(BaseModel, Generic[T]):
    """所有 Skill 输入必须继承。T 为各 Skill 自定义的 InputData"""
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    input_data: T = Field(..., description="业务输入数据")
```

**各 Skill 自定义**：

```python
# Skill A
class NicknameInputData(BaseModel):
    screenshot_id: str
    metadata_path: str
    debug_session_derived_path: str

class NicknameInput(SkillInput[NicknameInputData]):
    pass

# Skill C
class StructurerInputData(BaseModel):
    speaker_json_path: str
    original_text: str

class StructurerInput(SkillInput[StructurerInputData]):
    pass
```

---

### 六、trace_id 自动注入（contextvars）

```python
# skill_engine/context.py

import contextvars

_current_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("trace_id", default=None)

def get_trace_id() -> str | None:
    return _current_trace_id.get()

def set_trace_id(trace_id: str) -> None:
    _current_trace_id.set(trace_id)
```

```python
# skill_engine/executor.py

class SkillExecutor:
    def run(self, skill_name: str, input_data: dict) -> SkillOutput:
        trace_id = str(uuid4())
        set_trace_id(trace_id)          # ← 注入上下文
        # ... 执行流程
```

**`run.py` 无需关心 trace_id**——框架自动注入，`logger.py` 自动读取。

---

### 七、JSONL 日志必写字段

```json
{
  "trace_id": "uuid",
  "skill_name": "nickname-selector",
  "timestamp": "2026-06-14T10:00:00+08:00",
  "is_failure": true,
  "input_summary": {"screenshot_id": "scr_003"},
  "rule_output": {"nickname": "阿姨派单群", "source": "rule"},
  "ai_validation": {"result": "不合理", "reason": "这是群名不是人名"},
  "ai_reselection": {"result": "张三", "source": "ai"},
  "final_output": {"nickname": "张三", "source": "ai"},
  "warnings": [],
  "elapsed_ms": 850
}
```

### `is_failure` 标记规则

**由 `evolve.toml` 中的 `ai_role` 声明式决定**，框架自动应用对应规则：

| ai_role | `is_failure` 规则 |
|---------|------------------|
| `correction` | AI 验证发现不合理 → `true`；规则返回空/兜底值 → `true`；AI 重选后仍不合理 → `true` |
| `enhancement` | **始终 `false`**（AI 是加分项，不可用不影响可用性） |

框架实现：

```python
# executor.py
def _compute_is_failure(self, ai_role: str, rule_output: dict, ai_validation: dict, ai_reselection: dict) -> bool:
    if ai_role == "enhancement":
        return False
    if ai_role == "correction":
        if ai_validation.get("result") == "不合理":
            return True
        if ai_reselection and ai_reselection.get("result") == "不合理":
            return True
    return False
```

### `input_summary` 生成规则

1. 框架调用 `run.py.summarize_input(input_data) → dict`
2. 若未实现，自动取 `input_data` 的前 5 个键值对

---

### 八、AI 降级策略

```yaml
# rules_config.yaml 中统一配置（每个 Skill 可覆盖）

ai_fallback:
  validate_timeout_seconds: 3
  reselect_timeout_seconds: 5
  max_retries: 1
  circuit_breaker_threshold: 3          # 连续失败 3 次触发熔断
  circuit_breaker_cooldown_seconds: 60  # 熔断 60 秒后恢复
  conservative_mode: false              # true=不可用时标记「需人工复核」，false=乐观通过
```

**降级行为**：

| 场景 | 乐观模式（默认） | 保守模式 |
|------|----------------|---------|
| AI 验证超时/报错 | 默认「合理」 | 标记 `warnings: ["需人工复核: AI验证不可用"]` |
| AI 重选超时/报错 | 返回规则原始结果 | 返回规则原始结果 + 标记 |
| 全局熔断 | 全链路跳过 AI | 同左 |

---

### 九、MySQL 表结构

```sql
-- 主配置表
CREATE TABLE skill_config (
    skill_name   VARCHAR(128) NOT NULL COMMENT 'Skill 名称',
    config_type  ENUM('rules_config','prompt') NOT NULL COMMENT '配置类型',
    content      MEDIUMTEXT NOT NULL COMMENT 'YAML 字符串',
    version      INT NOT NULL DEFAULT 1 COMMENT '版本号，每次更新递增',
    updated_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (skill_name, config_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 配置历史（每次更新前归档旧版本，支持回滚）
CREATE TABLE skill_config_history (
    id           BIGINT AUTO_INCREMENT PRIMARY KEY,
    skill_name   VARCHAR(128) NOT NULL,
    config_type  ENUM('rules_config','prompt') NOT NULL,
    content      MEDIUMTEXT NOT NULL,
    version      INT NOT NULL,
    archived_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_skill_version (skill_name, config_type, version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

### 十、框架内置版本管理

```python
# skill_engine/config_loader.py

class ConfigVersionManager:
    """
    框架内置简单版本管理：version 递增 + 历史归档。
    housekeeping 项目的 VersionManager 作为可选适配器实现同一接口。
    """
    def load(self, skill_name: str, config_type: str) -> dict | None:
        """从 MySQL 加载当前激活版本，返回解析后的 dict"""

    def save(self, skill_name: str, config_type: str, content: str):
        """写入新版本：先归档旧版本到 skill_config_history，再更新主表 version+1"""

    def rollback(self, skill_name: str, config_type: str, target_version: int):
        """回滚到指定版本"""
```

---

### 十一、Skill A：nickname-selector

**流程**：
```
输入: screenshot_id + metadata.json + debug_session_derived.json
│
├── 1. 规则执行（现有 nickname_ocr_simple.py 逻辑）
│   └── 从 speaker_bands 选昵称 → candidate
│
├── 2. AI 常识判断
│   └── 「candidate 是真实微信昵称吗？」
│       ├── 合理 → 返回 SkillOutput(source="rule", ai_validated=True)
│       ├── AI 不可用 → 降级处理 → 返回
│       └── 不合理 → is_failure=true（ai_role=correction）→ 进入步骤 3
│
├── 3. AI 重新挑选
│   └── 取同 band 内 nickname_candidate 类块（≤20）→ DeepSeek 选最合理的
│       └── AI 不可用 → 返回规则原始结果
│
└── 4. 日志 → SkillOutput(source="ai", ai_reselected=True)
```

**`prompt.yaml`**：
```yaml
system_prompt: |
  你是微信昵称合理性判断专家。根据常识判断以下结果是否像真实用户的微信展示名。
  合理的示例：张三、李四阿姨、月嫂王姐、Sunny、15010025966、AA家政-小刘
  不合理的示例：阿姨派单群（群名）、09:18（时间）、*条新消息（系统消息）、###（乱码）

user_template_validate: |
  规则选出的昵称：{{nickname}}
  所在聊天区域的其他文字：{{context_blocks}}
  这个结果是合理的微信昵称吗？只回答「合理」或「不合理」，并简述理由。

user_template_reselect: |
  以下是一组微信聊天区域的文字块，其中有一个是真实的用户展示名。
  请根据常识选出最合理的一个，只回答选中的文字（原文照抄，不要修改）。
  候选文字块：
  {{candidates}}
```

---

### 十二、Skill B：match-scorer

**流程**：
```
输入: match_info + candidates
│
├── 1. 规则评分（现有 rule_match_scoring.py）→ 0-78 分
├── 2. AI 语义评分（现有 match_scoring.py）→ 0-22 分
│   └── AI 不可用 → 语义分为 0（is_failure=false，ai_role=enhancement）
├── 3. 相加 → 0-100 分
└── 4. 日志
```

**`rules_config.yaml`**：
```yaml
formula:
  required_full: 6
  optional_full: 4
  penalty_binary: 4
required_dimensions: [work_type_code, job_code, resume_update_days, province_codes, job_years_require, age_range, salary_max]
optional_dimensions: [education_ids, need_driver_license, city_code, height_min]
```

---

### 十三、Skill C：speaker-structurer

**流程**：
```
输入: speaker JSON（含发言人原文）
│
├── 1. 规则拆分 → {nickname, age?, hometown?, job?, ...}
│
├── 2. AI 常识判断
│   └── 「这个年龄/籍贯/职业字段合理吗？」
│       ├── 全部合理 → 返回
│       ├── AI 不可用 → 降级处理 → 返回
│       └── 某个字段不合理 → is_failure=true（ai_role=correction）→ 进入步骤 3
│
├── 3. AI 重新挑选
│   └── DeepSeek 阅读发言人 JSON 原文全文 → 重新提取不合理字段的值
│       └── AI 不可用 → 返回规则原始结果
│
└── 4. 日志
```

**`rules_config.yaml`**：
```yaml
field_extractors:
  age:
    patterns:
      - "(\d{2,3})\s*岁"
      - "年龄[：:]\s*(\d{2,3})"
  hometown:
    patterns:
      - "(湖南|湖北|四川|广东|江西|河南|安徽|江苏|浙江|山东|河北|陕西|广西|福建|云南|贵州|重庆|上海|北京|天津)人"
  job:
    patterns:
      - "(月嫂|育儿嫂|保姆|护工|钟点工|保洁|住家阿姨|白班阿姨)"
  salary:
    patterns:
      - "工资[：:]\s*(\d{3,6})"
      - "月薪[：:]\s*(\d{3,6})"

ai_validated_fields: [job, hometown]
```

**`prompt.yaml`**：
```yaml
system_prompt: |
  你是家政行业信息合理性判断专家。根据常识判断规则拆分出的字段是否合理。
  年龄合理：52、48、35。不合理：999、0、200
  籍贯合理：湖南、四川、广东。不合理：月亮、火星、ABC
  职业合理：月嫂、育儿嫂、保洁、护工、钟点工。不合理：老板、CEO、程序员、阿姨派单群群主

user_template_validate: |
  原文：{{original_text}}
  规则拆分结果：{{extracted_fields}}
  请逐字段判断是否合理。回答 JSON：{"字段名": "合理"|"不合理"}

user_template_reselect: |
  以下是发言人原文：{{original_text}}
  规则拆分结果中，以下字段被判断为不合理：{{invalid_fields}}
  请重新阅读原文，从中提取合理的值替换不合理字段。其他字段保持不变。输出完整的 JSON 结果。
```

---

### 十四、三个 Skill 对比

| | Skill A | Skill B | Skill C |
|---|---------|---------|---------|
| **规则产出** | 昵称候选 | 条件匹配分 | 拆分字段 |
| **ai_role** | `correction` | `enhancement` | `correction` |
| **AI 判断** | 像真实昵称吗？ | 语义匹配度 | 字段合理吗？ |
| **AI 重选来源** | `nickname_candidate` 类块 | — | 发言人 JSON 原文 |
| **AI 降级** | 默认合理 / 返回规则 | 语义分=0 | 默认合理 / 返回规则 |
| **is_failure** | AI 不合理 → true | 始终 false | AI 不合理 → true |
| **EvoSkill 分析** | 分析纠正失败的昵称 | 不触发 | 分析纠正失败的字段 |

---

### 十五、整体架构

```
skill-engine (pip, 纯框架)
│
├── SkillExecutor.run(skill_name, input)
│   ├── Pydantic 输入校验（SkillInput[InputDataType]）
│   ├── trace_id 生成 + contextvars 注入
│   ├── 加载 evolve.toml（获取 ai_role）
│   ├── 加载 skill.md + run.py（磁盘）
│   ├── 加载 rules_config + prompt（MySQL，ConfigVersionManager）
│   ├── execute() → AI 常识判断 → 合理则过 / 不合理则 AI 从原始数据重选
│   │   └── AI 降级（统一原则）
│   └── 写 JSONL 日志（根据 ai_role 自动计算 is_failure + summarize_input）
│
├── Logger → /data/skill-logs/{skill_name}/{date}.jsonl
│
└── Evolver.evolve(skill_name)
    ├── 读昨日 JSONL → 筛选 is_failure=true
    ├── 若 is_failure 样本 < 10 → 跳过本次进化
    ├── 跑 benchmark()
    ├── DeepSeek 分析失败模式（优先 Skill 自定义 evolve_prompt.yaml，否则用框架默认）
    ├── 生成 YAML 优化提案
    └── 按 evolve.toml 权限 → 自动写 MySQL 或发 PR
        └── 写入前归档旧版本到 skill_config_history
```

---

### 十六、进化权限与声明

```toml
# evolve.toml（随 Git，权限管控与代码强相关）

# Skill 级别声明
[skill]
ai_role = "correction"        # "correction"（纠错项）或 "enhancement"（加分项）

[evolve.auto_modify]
skill_md     = false    # 知识文档，发 PR
scripts      = false    # 确定性逻辑，发 PR
rules_config = true     # 阈值/黑名单/正则，自动写 MySQL
prompt       = true     # 模板措辞，自动写 MySQL

[evolve.auto_modify.rules_config]
mode = "threshold_only"
max_change_percent = 20

[evolve.guard]
require_benchmark_pass = true
min_improvement = 0.05
dry_run_before_apply = true
min_failure_samples = 10
```

### `ai_role` 声明机制

`evolve.toml` 中声明 `skill.ai_role`，框架据此自动决定：
- `is_failure` 计算规则
- EvoSkill 是否分析此 Skill 的日志（`enhancement` 角色不触发进化）

```python
# executor.py 读取
cfg = load_evolve_toml(skill_name)
ai_role = cfg.get("skill", {}).get("ai_role", "correction")
is_failure = _compute_is_failure(ai_role, rule_output, ai_validation, ai_reselection)
```

### `evolve_prompt.yaml`（框架默认，可被 Skill 覆盖）

```yaml
system: |
  你是配置优化专家。分析以下 Skill 执行日志中的失败案例，提出 rules_config / prompt 改进建议。

analyze_template: |
  Skill：{{skill_name}}
  当前 rules_config：{{current_rules_config}}
  当前 prompt：{{current_prompt}}

  失败案例（is_failure=true 的记录）：
  {{failure_logs}}

  请分析失败模式，提出改进建议：
  1. rules_config.yaml 需要调整什么？（阈值、黑名单词、正则模式）
  2. prompt.yaml 需要调整什么？（措辞、示例、temperature）
  注意：只改 rules_config 的数值和 prompt 的措辞，不改逻辑。

  输出 JSON：{"rules_changes": {...}, "prompt_changes": {...}}
```

---

### 十七、PIP 包目录

```
skill-engine/
├── pyproject.toml
├── defaults/
│   └── evolve_prompt.yaml       ← 框架默认进化 prompt
└── src/skill_engine/
    ├── __init__.py
    ├── executor.py              # SkillExecutor 主类（trace_id + is_failure 自动计算）
    ├── models.py                # SkillInput[T] + SkillOutput（Pydantic）
    ├── context.py               # trace_id contextvars
    ├── loader.py                # 加载 run.py / YAML / summarize_input
    ├── config_loader.py         # ConfigVersionManager（内置版本管理 + 历史归档）
    ├── deepseek.py              # DeepSeek 客户端封装（超时/重试/熔断）
    ├── logger.py                # JSONL 日志写入
    ├── evolver.py               # EvoSkill 离线进化（min_failure_samples=10）
    └── fallback.py              # AI 降级策略（乐观/保守模式）
```

---

### 十八、与现有资产兼容

| 现有资产 | 处理后 |
|---------|--------|
| `nickname_ocr_simple.py` | 被 skill A `run.py` import，主逻辑不变 |
| `rule_match_scoring.py` | 被 skill B `run.py` import，逻辑不变 |
| `match_scoring.py` | 同上 |
| `ocr_session_rule_bridge.py` | skill A 的 AI 兜底分支新增，主逻辑不变 |
| `match_weights_ayi_v1.yaml` | 迁入 MySQL `match-scorer/rules_config` |
| `matching_prompt_ayi_v1.yaml` | 迁入 MySQL `match-scorer/prompt` |
| `DeepSeekClient` | 合并到 skill-engine 统一实现 |
| `conftest.py` JSONL | 复用到 `logger.py` |
| `SKILL.md`（622行） | 拆为三个 skill 各自 `skill.md` |

### 十九、四类配置/代码的完整生命周期（实现对照）

以下描述基于 `skill-engine` 实际实现，明确四类关键资产在运行时链路和离线进化链路中的角色。

#### 19.1 四类资产总览

| 资产 | 存储 | 加载者 | 消费者（运行时） | 消费者（进化时） |
|------|------|--------|-----------------|-----------------|
| **`scripts/run.py`** | Git 磁盘 | `SkillLoader`（importlib 动态导入） | `SkillExecutor.run()` 调用 `execute()` | `Evolver.evolve()` 调用 `benchmark()` |
| **`rules_config.yaml`** | Git 磁盘（可迁 MySQL） | 调用方在 `SkillExecutor.run()` 传入 | `SkillExecutor`（降级配置 + 注入 `execute()`）+ `execute()` 内部 | `Evolver._analyze_failures()` 注入进化 prompt |
| **`prompt.yaml`** | Git 磁盘（可迁 MySQL） | 调用方在 `SkillExecutor.run()` 传入 | `SkillExecutor._ai_validate()` / `_ai_reselect()` / `_ai_enhance()` | `Evolver._analyze_failures()` 注入进化 prompt |
| **`skill.md`** | Git 磁盘 | `SkillLoader._load_skill_md()` | 无（不参与运行时推理） | `Evolver` 作分析上下文（当前未注入 prompt，预留） |

#### 19.2 运行时链路（SkillExecutor.run）

```
调用方
  │
  ├─ 加载 rules_config.yaml → dict  ────────────┐
  ├─ 加载 prompt.yaml → dict  ──────────────────┤
  │                                              │
  ├─ SkillExecutor.run(skill_name, input_data,   │
  │       rules_config=..., prompt_config=...)    │
  │   │                                          │
  │   ├─ SkillLoader.load(skill_name)            │
  │   │   ├─ importlib 动态导入 scripts/run.py   │  ← run.py 介入
  │   │   │   → execute / benchmark / summarize_input
  │   │   ├─ 解析 evolve.toml → ai_role          │
  │   │   ├─ 解析 evolve_prompt.yaml → evolve 提示词
  │   │   └─ 读取 skill.md → skill_md 文本       │  ← skill.md 介入（预留）
  │   │                                          │
  │   ├─ _build_fallback_config(rules_config)    │  ← rules_config 介入
  │   │   └─ ai_fallback 段 → FallbackConfig     │
  │   │                                          │
  │   ├─ execute(skill_input, merged_config)     │  ← rules_config + prompt_config
  │   │   └─ merged_config = {                   │     合并传入 execute()
  │   │        "rules_config": {...},             │
  │   │        "prompt_config": {...}             │
  │   │      }                                   │
  │   │                                          │
  │   ├─ [correction]                            │
  │   │   ├─ _ai_validate()                      │  ← prompt_config：
  │   │   │   ├─ system_prompt                   │     system_prompt
  │   │   │   └─ user_template_validate          │     + user_template_validate
  │   │   │                                      │
  │   │   └─ _ai_reselect() (若不合理)           │  ← prompt_config：
  │   │       ├─ system_prompt                   │     system_prompt
  │   │       └─ user_template_reselect          │     + user_template_reselect
  │   │                                          │
  │   └─ [enhancement]                           │
  │       └─ _ai_enhance()                       │  ← prompt_config：
  │           ├─ system_prompt                   │     system_prompt
  │           └─ user_template                   │     + user_template
  │                                              │
  └─ _log() → /data/skill-logs/{skill}/{date}.jsonl
```

**关键点**：

- `rules_config` 的两重用途：
  1. **框架层**：`ai_fallback` 段 → `FallbackConfig`（超时/重试/熔断/保守模式），由 `SkillExecutor` 自身消费
  2. **Skill 层**：全量内容通过 `merged_config["rules_config"]` 注入 `execute()`，Skill 的 `run.py` 可自由读取（如 Skill C 的 `field_extractors` 正则模式）

- `prompt.yaml` 的字段消费映射：

| 字段 | ai_role=correction | ai_role=enhancement |
|------|-------------------|---------------------|
| `system_prompt` | `_ai_validate()` + `_ai_reselect()` | `_ai_enhance()` |
| `user_template_validate` | `_ai_validate()` 渲染为 user message | 不使用 |
| `user_template_reselect` | `_ai_reselect()` 渲染为 user message | 不使用 |
| `user_template` | 不使用 | `_ai_enhance()` 渲染为 user message |

- `run.py` 的 `execute()` 只承担**规则阶段**。AI 阶段由 `SkillExecutor` 统一接管，调用 `_ai_validate` / `_ai_reselect` / `_ai_enhance`。

#### 19.3 离线进化链路（Evolver.evolve）

```
Evolver.evolve(skill_name)
  │
  ├─ SkillLoader.load(skill_name)
  │   ├─ ai_role → 若为 "enhancement" → 不触发进化 ✋
  │   └─ evolve_prompt.yaml (Skill 自定义优先，框架默认降级)  ← 进化 prompt 介入
  │
  ├─ _load_failure_logs() → 读 JSONL, 筛选 is_failure=true
  ├─ _run_benchmark() → 进化前基线
  │
  ├─ ConfigVersionManager.load_raw(rules_config)  → {{current_rules_config}}  ← rules_config 介入
  ├─ ConfigVersionManager.load_raw(prompt)        → {{current_prompt}}        ← prompt 介入
  │
  ├─ _analyze_failures()
  │   └─ DeepSeek.chat_json()
  │       ├─ system: evolve_prompt.yaml → system
  │       └─ user:   evolve_prompt.yaml → analyze_template
  │           ├─ {{skill_name}}          ← 固定注入
  │           ├─ {{current_rules_config}} ← rules_config 当前值
  │           ├─ {{current_prompt}}       ← prompt 当前值
  │           └─ {{failure_logs}}         ← JSONL 中 is_failure=true 的记录（≤20 条）
  │       → 输出 JSON: {"rules_changes": {...}, "prompt_changes": {...}}
  │
  ├─ 按 evolve.toml 权限：
  │   ├─ rules_config → ConfigVersionManager.save() 写入 MySQL（写入前归档到 skill_config_history）
  │   └─ prompt       → ConfigVersionManager.save() 写入 MySQL
  │
  └─ benchmark 安全网：重跑 benchmark → 退化则 ConfigVersionManager.rollback() 自动回滚
```

**关键点**：

- `skill.md` 虽然被 `SkillLoader` 加载到 `SkillModule.skill_md`，但当前 `Evolver._analyze_failures()` **未将其注入进化 prompt**。这是一个预留字段——未来可在 `evolve_prompt.yaml` 的 `analyze_template` 中增加 `{{skill_md}}` 占位符实现注入。
- `rules_config` 和 `prompt` 在进化链路中是**只读引用**（注入 prompt 供 DeepSeek 分析），写入由 `ConfigVersionManager.save()` 执行。
- `run.py` 在进化链路中通过 `benchmark()` 验证变更效果。

#### 19.4 存储策略（当前实现 vs 目标）

| 资产 | 当前存储 | 当前加载方式 | 目标存储（MySQL 热加载） |
|------|---------|-------------|------------------------|
| `scripts/run.py` | Git 磁盘 | importlib 动态导入 | 保持不变（逻辑代码） |
| `skill.md` | Git 磁盘 | 直接读文件 | 保持不变（知识文档） |
| `rules_config.yaml` | Git 磁盘（`skill/{name}/rules_config.yaml`） | 调用方读取后传入 executor | MySQL `skill_config` 表（`config_type='rules_config'`） |
| `prompt.yaml` | Git 磁盘（`skill/{name}/prompt.yaml`） | 调用方读取后传入 executor | MySQL `skill_config` 表（`config_type='prompt'`） |
| `evolve.toml` | Git 磁盘 | SkillLoader 内建 TOML 解析 | 保持不变（权限与代码强相关） |
| `evolve_prompt.yaml` | Git 磁盘（优先 Skill 自定义，降级框架默认） | SkillLoader 加载到 SkillModule | 保持不变或可迁 MySQL |

> **注意**：当前 `rules_config.yaml` 和 `prompt.yaml` 均以磁盘文件形式加载，`SkillExecutor.run()` 未内置 MySQL 读取逻辑——由调用方负责加载后传入。`Evolver` 则通过 `ConfigVersionManager` 直连 MySQL 读写。

---

## 第二部分：实施计划

### 阶段 0：PIP 框架骨架

| 步骤 | 任务 | 产出 |
|------|------|------|
| 0.1 | 创建 `skill-engine` 目录 + `pyproject.toml` | 空 pip 包 |
| 0.2 | `models.py`：`SkillInput[T]` + `SkillOutput` | Pydantic 模型 |
| 0.3 | `context.py`：`trace_id` contextvars | 上下文注入 |
| 0.4 | `deepseek.py`：OpenAI 兼容调用 + 超时/重试/熔断 | DeepSeek 客户端 |
| 0.5 | `config_loader.py`：`ConfigVersionManager` + 历史归档 | 配置热加载 + 版本管理 |
| 0.6 | `loader.py`：动态加载 `scripts/run.py` + `summarize_input` + `evolve.toml`（含 `ai_role`） | Skill 动态导入 |
| 0.7 | `fallback.py`：AI 降级策略（乐观/保守模式 + 熔断） | 降级逻辑 |
| 0.8 | `logger.py`：JSONL 追加写入（含 `is_failure`，由 `ai_role` 决定） | 日志器 |
| 0.9 | `executor.py`：`SkillExecutor.run()` 主流程 | 执行引擎 |
| 0.10 | 创建 `defaults/evolve_prompt.yaml` | 框架默认进化 prompt |
| 0.11 | pip 包可安装验证 | `pip install -e .` 通过 |

### 阶段 1：迁移 match-scorer（Skill B）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 1.1 | 创建 `skill/match-scorer/` 目录 + `skill.md` + `evolve.toml`（`ai_role = "enhancement"`） | 知识文档 + 权限配置 |
| 1.2 | 编写 `scripts/run.py`：import 现有规则 + AI 评分 | Skill B 实现 |
| 1.3 | 迁移 `match_weights_ayi_v1.yaml` → MySQL `rules_config` | 配置迁移 |
| 1.4 | 迁移 `matching_prompt_ayi_v1.yaml` → MySQL `prompt` | 配置迁移 |
| 1.5 | 创建 `evolve_prompt.yaml`（可选，不创建则用框架默认；ai_role=enhancement 时不触发进化） | 进化 prompt |
| 1.6 | 集成测试：5 个已知匹配案例验证 | 验证通过 |

### 阶段 2：新增 nickname-selector（Skill A）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 2.1 | 创建 `skill/nickname-selector/` 目录 + `skill.md` + `evolve.toml`（`ai_role = "correction"`） | 知识文档 + 权限配置 |
| 2.2 | 编写 `scripts/run.py`：规则 + AI 常识判断 + candidate 重选 | Skill A 实现 |
| 2.3 | 编写 `rules_config.yaml` → 写入 MySQL | 规则配置 |
| 2.4 | 编写 `prompt.yaml`（validate + reselect）→ 写入 MySQL | Prompt 配置 |
| 2.5 | 创建 `evolve_prompt.yaml`（可选） | 权限配置 |
| 2.6 | 集成测试：5 个已知 session 验证昵称结果 | 验证通过 |

### 阶段 3：新增 speaker-structurer（Skill C）

| 步骤 | 任务 | 产出 |
|------|------|------|
| 3.1 | 创建 `skill/speaker-structurer/` 目录 + `skill.md` + `evolve.toml`（`ai_role = "correction"`） | 知识文档 + 权限配置 |
| 3.2 | 编写 `scripts/run.py`：正则拆分 + AI 常识判断 + 原文重提取 | Skill C 实现 |
| 3.3 | 编写 `rules_config.yaml` → 写入 MySQL | 规则配置 |
| 3.4 | 编写 `prompt.yaml`（validate + reselect）→ 写入 MySQL | Prompt 配置 |
| 3.5 | 创建 `evolve_prompt.yaml`（可选） | 权限配置 |
| 3.6 | 集成测试：5 个发言人 JSON 验证拆分结果 | 验证通过 |

### 阶段 4：EvoSkill 离线进化

| 步骤 | 任务 | 产出 |
|------|------|------|
| 4.1 | `evolver.py`：读 JSONL（`is_failure=true`，min 10 条）→ DeepSeek 分析 → 生成 YAML 提案 | Evolver 类 |
| 4.2 | 按 `evolve.toml` 自动写 MySQL（写入前归档到 `skill_config_history`）或生成 PR | 自动生效 / 人工审核 |
| 4.3 | 进化 dry-run 验证：跑 benchmark 确认不退化 | 安全网 |

### 阶段 5：验收

| 步骤 | 任务 | 产出 |
|------|------|------|
| 5.1 | 三个 skill 各 10+ 真实 session 全量跑通 | 回归通过 |
| 5.2 | AI 兜底命中率统计（验证 + 重选） | 数据报告 |
| 5.3 | 降级测试：断 DeepSeek API → 链路不崩 | 降级通过 |
| 5.4 | trace_id 可追踪：任意日志反查完整链路 | 链路通过 |
| 5.5 | 配置回滚：从 `skill_config_history` 回滚到历史版本 | 回滚通过 |
| 5.6 | EvoSkill 闭环：输入 10 条 `is_failure=true` 日志 → 产出 ≥1 条有效 YAML 提案 | 闭环通过 |
| 5.7 | benchmark 安全网：错误 YAML 提案注入 → benchmark 不通过 → 自动回滚 | 安全网通过 |
| **5.8** | **提取 `AiAssistedExecutor` 基类**（三个 `run.py` 写完后，抽取通用「验证+重选」流程） | 框架层抽象 |

---

### 各阶段依赖

```
阶段 0 ──→ 阶段 1 (Skill B: 迁移，最快)
  │
  ├──→ 阶段 2 (Skill A: 新增)
  │
  └──→ 阶段 3 (Skill C: 新增)
  │
  └──→ 阶段 4 (EvoSkill: 依赖日志积累)
           └──→ 阶段 5 (验收 + 基类提取)
```

阶段 1/2/3 可并行开发（三个 `run.py` 独立）。

---

### 验收标准

| 标准 | 要求 |
|------|------|
| 三个 skill 集成测试 | 各自 10+ session 全部正确 |
| AI 降级 | 断 DeepSeek API → 链路不崩，乐观/保守模式均正确 |
| trace_id 可追踪 | 任意一条日志通过 trace_id 反查完整链路 |
| `is_failure` 分 ai_role 正确 | `correction` 角色 AI 不合理标记 true；`enhancement` 角色始终 false |
| 最小样本量 | is_failure < 10 时正确跳过进化 |
| evolve_prompt 优先级 | Skill 自定义优先，框架默认降级 |
| 配置历史 | `skill_config_history` 表含每次变更归档 |
| 配置回滚 | 从 history 表回滚到任意历史版本 |
| EvoSkill 闭环 | 输入 10 条 `is_failure=true` 日志 → 产出 ≥1 条有效 YAML 提案 |
| benchmark 安全网 | 错误 YAML 提案注入 → benchmark 不通过 → 自动回滚 |
| `AiAssistedExecutor` 提取 | 三个 `run.py` 的共通模式抽象为框架基类 |
