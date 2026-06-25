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
| V 0.2  | 2026-06-16 | 阶段1+2实施：框架 geometry 规则支持、executor session_dir、EvolveGuardModel 补齐、管线 rules_config 补全、run.py session_dir、扫描旁路 JSONL hook、**nickname_ocr_simple 声明式桥接（主路径替换）**、进化 APScheduler 凌晨2点 | AI | AI | 测试通过 |
| V 0.3  | 2026-06-16 | `_classify()` 声明式替换：`_classify_with_declarative_rules()` 作为主分类路径，config (NicknameOcrConfig) 阈值优先于 YAML，`_starts_with_system_prefix` 返回 bubble_text（非 drop），geometry_rules 修复 `type: geometry` 字段，YAML path `parents[3]` 修正 | AI | AI | 34/34 nickname OCR + 149/149 skill_self_evolution 全绿 |
| V 0.4  | 2026-06-18 | `SkillExecutor` 新增 `enrich_failure` 回调机制：扫描旁路通过回调将 `debug_session_derived.json`、`speaker JSON`、`customer_metadata.json` 三个文件全文注入 JSONL 的 `input_summary`，供 Evolver LLM 分析几何原因；`evolve_prompt.yaml` 同步更新领域知识摘要与数据注入说明 | AI | AI | 测试通过 |

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
│  昵称选择                      │  │  匹配评分                          │
│  发言人结构化                    │  │                                    │
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

**上游1：数据处理规则结果判断**（昵称选择 / 发言人结构化）。

（一）昵称选择模型（规则）的自我进化方案：

rules_config.yaml存在mysql数据库，同时项目目录有备份（从数据库读取）

三组件解耦关系
skill_self_evolution（开源）          screenshot_vision_algorithm（开源）
  │                                        │
  ├── rules_config.yaml ───真理源────      ├── NicknameOcrConfig ← 纯 dataclass
  │   nickname_thresholds                  │   skip_block_patterns: tuple
  │   card_binding                         │   cross_band_distance_threshold_px
  │   skip_patterns                        │   min_confidence...
  │                                        │
  └── Evolver 优化↑                        └── _should_skip_block() ← 读 config
                          ↑
                    读 yaml，构造 dataclass
                          │
                  housekeeping（项目）
                    run_processor_minimal.py
                    _default_nickname_ocr_config()
sva 对 skill_self_evolution 零依赖
skill_self_evolution 对 sva 零依赖
housekeeping 是唯一知道两者并存的项目，负责胶水
其他项目可以直接 NicknameOcrConfig(skip_block_patterns=(...)) 无需 yaml
Evolver 优化 rules_config.yaml 后，下轮扫描自动生效（无需改 sva 代码）




同一套版本文件，一个版本号来源
                      wx_version_activation 表
                      active_version = N
                            │
        ┌───────────────────┼───────────────────┐
        ▼                                       ▼
  Admin 创建新版本                     Evolver 自动进化
  rules_config_v{N+1}.yaml           rules_config_v{N+1}.yaml
  set_active_version(N+1)            _sync_evolved_rules_to_version_manager()
        │                                       │
        └──────────────┬────────────────────────┘
                       ▼
              VersionManager.load_config("nickname_rules_config")
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
        run.py    scan_job.py    benchmark()
       (扫码生产)  (扫描旁路)    (进化验证)

Admin 面板"创建新版本"和 Evolver "自动进化"都通过同一个 wx_version_activation 表 + rules_config_vN.yaml 文件体系，生产流程实时读取当前激活版本。Evolver 内部的 rules_config.yaml 作为工作文件保留不动（_sync_rules_to_disk 仍写入它），但 3 个生产入口都从 VersionManager 读取。



### 管线内的规则执行（始终运行，无需开关）

声明式规则引擎由两部分组成：**`rules_config.yaml`**（规则定义）+ **`rule_runner.py`**（薄执行层）。用于替代 `nickname_ocr_simple.py` 中 `_classify()` 的旧硬编码实现：对每个 OCR text block 逐块分类（`nickname_candidate` / `bubble_text` / `drop`），结构编排层再从候选池中选出最终昵称。

`nickname_ocr_simple.py`（已有旧管线文件，路径 `scripts/wx_match/processor/nickname_ocr_simple.py`）的内部逻辑分两层：

| 层 | 内容 | 执行策略 |
|----|------|---------|
| **逐块过滤层** `_classify()` | 文本规则 + 几何规则 + 头像守卫 | 声明式规则引擎（`rules_config.yaml` + `rule_runner.py`）作为**主分类路径**。`_classify()` 通过 `_get_declarative_rules()` 加载 YAML 规则后传入 `_classify_with_declarative_rules()`，由后者统一执行 drop / 分类。config (NicknameOcrConfig) 阈值优先于 YAML（测试可覆盖），`_starts_with_system_prefix` 仅阻止昵称分类（返回 bubble_text，非 drop），水平位置与头像列守卫保持硬编码。`rules_config.yaml` 不可用时自动降级到纯硬编码。降级逻辑直接写在代码中，无外部参数控制。降级触发条件：
- `rules_config.yaml` 解析失败 → 降级到 `_classify()` 旧逻辑`_get_declarative_rules()` 支持 MySQL 优先、磁盘 YAML 回退、模块级缓存热加载 |
| **结构编排层** | 气泡碎片合并、发言认领、简历卡绑定三步逻辑、orphan 归因，从候选池中选出最终昵称 | 算法流程保持硬编码，**参数**纳入 YAML 配置（见下） |

`rules_config.yaml` 覆盖范围（Evolver 在 `mode=full` 下可自主改进）：

| 节 | 内容 | 类型 | 原代码位置 | 实现状态 | 归属层 |
|----|------|------|-----------|---------|-------|
| `rejection_rules` | 文本匹配规则（regex / prefix / length）。注意：`@` 等系统前缀由 `config.system_prefix_drops` 阻止昵称分类（→ bubble_text），不在 YAML 中直接 drop | YAML 原生 | 原 `_classify()` 内的 `_is_pure_time` 等调用链 | ✅ 已实现 | **filter 层** |
| `nickname_thresholds` | 数值阈值（min_confidence、nickname_max_chars、screen_midline_ratio、nickname_max_x1_ratio） | YAML 扩展 | 原 `NicknameOcrConfig` 类 | ✅ 已实现 | **filter 层** |
| `correctness_criteria` | AI 判定用的 bad_categories、verification_conditions | YAML 已有 | 不变 | ✅ 已实现 | — |
| `ai_fallback` | AI 熔断/降级参数（timeout、重试次数、断路器阈值） | YAML 已有 | SkillExecutor 内置 | ✅ 已实现 | — |
| `geometry_rules` | 附加几何约束（bbox_width / char_height_ratio），使用 `type: geometry` 字段配合 `RejectionRuleItem` 校验 | YAML 新增 | 原 `_classify()` 内无直接对应（补充性约束），`_is_on_left_half` / `_is_avatar_column_nickname_row` 保持硬编码 | ✅ 已实现 | **filter 层** |
| `bubble_merge` | 气泡碎片归并参数（vertical_gap_max_px、fragment_same_line_y_tol_px、fragment_horizontal_gap_max_px） | YAML 新增 | 原 `NicknameOcrConfig` 类 | ✅ 已实现 | **structural 层** |
| `placeholder_lines` | 发言正文占位行剔除列表（如 `[语音]`、`[图片]` 等） | YAML 新增 | 原 Python `_PLACEHOLDER_EXACT_LINES` frozenset | ✅ 已实现 | **structural 层** |
| `card_binding` | 卡片绑定参数（inside_y_tolerance_px、orphan_distance_threshold_px、thumb_block_mask_midline_ratio） | YAML 新增 | 原函数体内硬编码参数 | ✅ 已实现 | **structural 层** |

> **归属层说明**：
> - **filter 层**：逐块过滤 `_classify()` 阶段的参数，benchmark 只需对单个 block 跑 `rule_runner`（轻量）。
> - **structural 层**：气泡合并 / 认领 / 卡片绑定 / orphan 归因等编排阶段的参数，benchmark 需跑完整 `nickname_ocr_simple` 全链路（重）。

> **`rule_runner` 能力边界**：`run_rejection_rules()` 支持 `regex` / `prefix` / `length` 三种纯文本规则（输入 `str`）。`run_block_rules()` 已新增，支持 `type: "geometry"` 及 `OcrBlock` 输入，覆盖 `horizontal_position` / `avatar_column` / `bbox_width` / `char_height_ratio` 四种几何约束。`OcrBlock` / `GeometryRuleParams` / `BlockCandidate` / `SessionInput` 等新的 Pydantic 模型已在 `models.py` 中定义。

上述参数均不改变算法逻辑，仅调整数值或增删列表项。算法流程本身（如三步绑定的先后顺序、orphan 继承的遍历方向）保持硬编码，需 `scripts=true` + 编程智能体才能改动。


- 规则过滤后候选池为空 → 降级到 `_classify()` 旧逻辑



### 数据源——session 目录

所有数据以 session 目录为单位，格式：

```
build/wx_match_sessions/wechat/{device_id}/{YYYYMMDD}/session_{session_id}/
```

示例：`build/wx_match_sessions/wechat/edb1a89f/20260613/session_20260613113935_edb1a89f/`

目录内关键文件：

| 文件 | 用途 | 写入者 |
|------|------|--------|
| `debug_session_derived.json` | OCR 分类结果，`blocks[]` 含 `class: "nickname_candidate"` 的候选池（每条带 text / bbox_xyxy / confidence / band） | Scanner 管线 |
| `{昵称}_{时间戳}.json`（speaker JSON） | 发言人绑定，`md5_spokesperson.speaker_binding_raw` 为管线最终选中的昵称 | MQ Consumer |
| `customer_metadata.json` | 含 `resume_thumb_bboxes`、`click_context`、`screenshots[].type` 等几何上下文（仅 Evolver 进化AI 使用） | Scanner 管线 |
| `metadata.json` | 采集元数据（本方案不直接使用） | Collector |

- local 环境：数据在本地 `build/wx_match_sessions/` 下，宿主机和 Docker 容器通过 bind mount 共享。
- test/prod 环境：数据在华为云 OBS（bucket `wx-screenshot` / `test-sync-obs`），路径前缀 `wechat/`。下载到本地后目录结构与 local 一致。Evolver 运行时通过 `wx_session_processed.obs_prefix` 定位 OBS key，再从 OBS 拉取到本地。

##### enrich_failure 回调：session 文件注入

Evolver 分析失败案例时需要查阅 `debug_session_derived.json`（OCR 分类结果，含 block 坐标/分类/confidence/band）、`speaker JSON`（管线最终选中的昵称及正文）、以及 `customer_metadata.json`（简历卡片 bbox、点击坐标等几何上下文）。若只给 Evolver 一个 `session_dir` 路径，则 LLM 无法直接访问这些文件。

**方案**：在 `SkillExecutor` 构造函数中引入 `enrich_failure` 可选回调（`Callable[[str], dict[str, str]]`），由调用方实现。扫描旁路传入 `_enrich_nickname_failure(session_dir)`，该函数读三个文件的全文内容，返回 `dict[str, str]`。`SkillExecutor._log()` 将回调返回的键值对合并到 JSONL 的 `input_summary` 中，与 `candidates_path` 一并写入。

**数据流**：

```
scan sidecar
  ↓ 调用 SkillExecutor(enrich_failure=_enrich_nickname_failure)
    ↓ SkillExecutor.run(session_dir=...)
      ↓ 触发 self._enrich_failure(session_dir)
        → 读 debug_session_derived.json 全文
        → 读 speaker JSON 全文
        → 读 customer_metadata.json 全文（可选）
      ↓ 存入 self._enrichment
    ↓ SkillExecutor._log() 将 self._enrichment 合并到 input_summary
      → JSONL 条目中包含完整的 session 文件内容
```

**JSONL 注入字段**（`input_summary` 内新增的键）：

| 键 | 来源文件 | 内容 | condition |
|----|----------|------|-----------|
| `candidates_path` | — | session_dir 路径（始终存在） | always |
| `debug_session_derived_json` | `debug_session_derived.json` | 全文 JSON 字符串，含 `blocks[].text/class/band/bbox_xyxy/confidence/speaker_bands[]` | 文件存在 |
| `speaker_json` | `{昵称}_{时间戳}.json` | 全文 JSON 字符串，含 `speaker_binding_raw`、`body_raw_merged`、`source_files[]` | 文件存在 |
| `customer_metadata_json` | `customer_metadata.json` | 全文 JSON 字符串，含 `resume_thumb_bboxes`、`click_context` | 文件存在 |

**异常处理**：回调异常时仅记录 warning 日志，不阻塞扫描管线。单个文件读取失败不影响其他文件的注入。

### 自我进化旁路（通过local/test/prod env参数来实现开关）

上述管线内的规则执行与降级始终运行于管线中，与自我进化开关无关。

env文件里的 `enable_nickname_evolution` 参数作为开关，只控制管线跑完后是否触发自我进化旁路，开启后 `create_scanner_process_fn()` 会执行后续动作。
以下几种方式可以实现开关的动作（`false` 为关闭，`true` 为开启。local环境默认开启，test/prod环境默认关闭）：
- CLI 参数 `--enable-nickname-evolution` 和 `--disable-nickname-evolution`（`run_scanner_minimal.py` 使用），本次调用立即开启/关闭
- `test-collector-customized-for-renxin` SKILL 收到"开启/关闭昵称选择规则的自我进化"指令时，直接修改 `.env` 中 `enable_nickname_evolution` 为 `true` 或 `false`。

#### 扫描旁路（每次 `process_session()` 完成后触发）

开关为 `true` 时，每次扫描结束后执行：

1. 定位 session 目录下的 speaker JSON 文件（格式 `{昵称}_{时间戳}.json`）→ 读取 `md5_spokesperson.speaker_binding_raw`（管线的最终选择）。AI 始终以管线实际输出作为判断对象——Golden label 不替代 AI 输入，仅用于 Evolver benchmark 时的正确性对照。
2. 读取 `debug_session_derived.json` → 提取所有 `class: "nickname_candidate"` 的 block 的 `text` 字段 → 候选池文本列表。
3. 调用 `SkillExecutor.run(session_dir, prompt_config)`，
   将候选池文本 + 管线选中的昵称交给“规则选择结果判断AI”（当前接入DeepSeek，按 `prompt.yaml` 常识判断）：
   管线选出的昵称是否正确、合理。
   “规则结果判断AI”仅凭人类常识判断，不看当前规则配置，也不看 bbox / band / customer_metadata 等几何数据。

若昵称选择结果判断AI判定 result 不合理：
- 优先从候选池中重选最佳替代；
- 若候选池中不存在合理选项（规则误将正确答案过滤掉），标记 `no_valid_alternative=true`。
以上两种均写 JSONL 日志标记 `is_failure=true`（日志带 `session_dir` 字段，指向 session 目录）。
若合理，标记 `is_failure=false`。

4. `SkillExecutor` 调用方通过 `enrich_failure` 回调注入 session 文件内容：
   回调在 `SkillExecutor.run(session_dir=...)` 执行时被调用，读取 `debug_session_derived.json`、
   `speaker JSON`、`customer_metadata.json` 的全文，注入到 JSONL 的 `input_summary` 中。
   这些数据供后续 Evolver LLM 分析几何原因（如 band 归属错误、卡片边界偏差等），
   而非让"规则选择结果判断AI"使用。


#### Evolver训练集和验证集
由 Evolver 在每天进化定时任务里构建

**数据源与 Evolver 共用同一 `log_dir`（`/data/skill-logs/{skill_name}/`）。为防止循环自证，错误集拆分为训练集和验证集：**

- **Golden set `golden_set_nickname_evolution`**：少量人工标注正确答案。每个案例是一个完整的 session 目录（包含 `debug_session_derived.json` + speaker JSON），随OBS 存储。正向案例（管线已选对的）无需额外标注；纠错案例（管线选错的）通过 MySQL 表 `nickname_golden_label` 记录正确答案（`session_id` + `speaker_json_file` → `golden_nickname`，`label_type='correction'`）。详见附录「Golden set 标注表」。
- **训练集 `training_set_nickname_evolution`**（给 Evolver 分析规则缺陷）：历史 `is_failure=true` 中排除当天的新增错误。每个案例通过 JSONL 中的 `session_dir` 定位 session 目录。
- **验证集 `validation_nickname_evolution`**（给 `benchmark_fn` 验收）：**仅 Golden set**。未经验证的 `is_failure=false` 案例不进入验证集——AI 可能误判（false negative），将 AI 错误判断作为正确基准会污染进化方向。


整个流程**不生成中间文件**——规则结果判断AI、Evolver 进化AI、benchmark 均直接读取 session 目录下的原始文件。

两个 AI 角色的数据需求对比：

| | 昵称选择结果判断AI | Evolver 规则进化AI |
|---|---|---|
| 候选池文本 | ✅ `nickname_candidate` 的 text 列表 | ✅ |
| 管线选中昵称 | ✅ `speaker_binding_raw` | ✅ |
| bbox / band / confidence | ❌ 不需要，凭常识判断 | ✅ 需要，分析空间关系与规则缺陷 |
| `resume_thumb_bboxes` | ❌ 不需要 | ✅ 需要，分析卡片绑定规则 |
| `click_context` | ❌ 不需要 | ✅ 需要，验证点击精度 |
| 截图图片 | ❌ DeepSeek 纯文本模型 | ❌ 同上，当前无法利用 |
| **数据获取方式** | SkillExecutor 直接读取候选池文本列表 + speaker JSON | 通过 `enrich_failure` 回调全文注入到 JSONL `input_summary` 中，LLM 无需文件系统访问 |


#### 进化定时任务 `nickname_evolution`


`nickname_evolution` 是独立的 APScheduler 定时任务（后台常驻，每天11点和23点执行一次），
启动时读取 `enable_nickname_evolution` 参数，为 `true` 时才执行进化流程：

Evolver 先构建训练集和验证集，
然后读取 JSONL 失败案例，失败案例数量达到阈值后（默认≥10，可配置），让 “Evolver 规则进化AI”（当前接入DeepSeek），根据 `evolve_prompt.yaml` 的提示词，分析当前 `rules_config.yaml` 哪里导致误判，然后优化已有规则或提出新规则。
`evolve_prompt.yaml` 的输入包括：
- 当前 `rules_config.yaml`
- 失败案例的 JSONL 条目（含 `rule_output` / `ai_validation` / `ai_reselection` 等字段）
- `input_summary` 中由 `enrich_failure` 回调注入的 session 文件全文：
  - `debug_session_derived_json`：OCR 分类结果（blocks、speaker_bands 等）
  - `speaker_json`：管线选中昵称、正文、来源截图
  - `customer_metadata_json`（可选）：简历卡片 bbox、点击坐标等几何上下文

**数据定位**：Evolver 无需再从 `session_dir` 做文件系统或 OBS 读取 ——
所有 session 文件内容已在扫描旁路阶段由 `enrich_failure` 回调一次性注入到 JSONL 中，
LLM 直接解析 `input_summary` 内的 JSON 字符串即可获得完整的几何与文本上下文。

Evolver 提出的规则分两类，由 `evolve.toml` 的 `[evolve.auto_modify]` 节控制（Evolver 通过 benchmark 确定性对比决定自动接受或回滚）：

- **纯配置规则**：仅改动 `rules_config.yaml`（如新增拒绝规则、调整阈值、补充 correctness_criteria）。始终允许（`rules_config.mode = "full"`）。
- **代码级规则**：需要修改下游代码才能生效（如新增参数 `min_overlap_area_ratio`，`nickname_ocr_simple.py` 需新增消费逻辑）。由 `scripts = true/false` 开关控制（local环境默认开启，test/prod环境默认关闭）。

（1）当 Evolver 提出纯配置规则时，调用 `benchmark_fn`（调用方注入）获取确定性对比数据。

`benchmark_fn` 读验证集（仅 Golden set）→ 对每个 case 通过 JSONL 中的 `session_dir` 定位 session 目录 → 用新规则重跑过滤 → 对比 Golden set 已知正确答案 → 返回 `(通过数, 总数, 失败列表)`。Evolver 比较改动前后通过数，决定接受或回滚。

benchmark 执行路径分两级（取决于 Evolver 改动触及哪些节）：

| 改动涉及的节 | benchmark 执行路径 | 是否需要完整管线 |
|---|---|---|
| `rejection_rules`、`correctness_criteria.bad_categories`、`nickname_thresholds`（filter 层） | 仅对候选池文本调 `rule_runner.run_rejection_rules()` | 否（轻量，无需重跑 OCR） |
| `geometry_rules`（filter 层，⬜ 计划新增） | 需 `rule_runner` 升级支持 `OcrBlock` 输入后方可 benchmark（当前 `rule_runner` 仅处理纯文本 `str`，不支持 bbox 位置判断） | 否（单个 block） |
| `bubble_merge`、`placeholder_lines`、`card_binding`（structural 层） | 需跑完整 `nickname_ocr_simple` 全链路（气泡合并→认领→卡片绑定→orphan 归因） | 是（重） |

> **当前可用范围**：`rule_runner` 仅支持 `regex` / `prefix` / `length` 三种纯文本规则。Evolver 现阶段仅能优化已实现的 filter 层文本规则。`geometry_rules` 需先升级 `rule_runner`（列入开发计划）。


（2）当 Evolver 提出代码级规则时，如果符合条件（local 环境默认开启使用 ，test/prod 暂不提供；每个环境的`scripts = true` 且 `enable_nickname_evolution = true`时才允许使用），
Evolver 通过以下闭环流程生成和改进代码：

a) **代码生成（OpenCode）**：通过 EvoSkill 的 OpenCode harness 调用 `opencode serve` HTTP API，使用 DeepSeek (`deepseek-chat`) 模型生成代码。调用方式为 `execute_query(options, prompt)`（详见 `E:\projects\skill_self_evolution\docs\adr\opencode_harness_assessment.md`），每次传入当前代码上下文 + 反馈历史（历史失败尝试及原因），AI 返回 ` ```python ``` ` 代码块。
`FeedbackDescent` 算法,驱动多轮迭代。loop_config.py进化循环统一配置/parallel_eval.py并行评测，提供有力辅助（复用EvoSkill的代码自主进化功能的分析参见E:\projects\skill_self_evolution\docs\adr\prompt_evolution_enhancement.md）。

b) **测试验证（`E:\projects\collector_phone_android\.cursor\skills\test-collector-customized-for-renxin` SKILL）**：生成的代码由cursor调用该 SKILL 执行自动化测试，每次失败时将错误信息 / 失败原因喂回 AI 作为下一轮反馈。日志通过 `structlog` 输出

按如下 4 层约束验证生成的代码：

    1. 静态检查。Python 标准库 ast 模块做静态代码检查（包括但不限于超长条件链 / 裸 except / 修改 global / 日志在 for 循环内 / 异常不吞没等 AST 检查），失败就重写（错误信息喂回）。
    2. 单元测试。opencode写，cursor测，失败就重写（错误信息喂回）。
    3. 集成测试。要求新代码必须和该模块有接口的其它系统/业务模块（这个提前就知道，写入`test-collector-customized-for-renxin` SKILL 知识库），产生直接或者间接的关联。实际是强制参加集成测试 + 测试覆盖率门禁。任何一个失败就重写（错误信息喂回）。
    4. 生产环境测试。跑所有验证集数据。失败则重写（错误信息喂回）。

4层全部通过后，将 `(通过数, 总数, 失败列表)` 返给 Evolver。
Evolver 比较改动前后通过数，决定接受或回滚。回滚时企微报警。

#### 附录：Golden set 标注表

```sql
CREATE TABLE IF NOT EXISTS nickname_golden_label (
    id                BIGINT AUTO_INCREMENT PRIMARY KEY,
    session_id        VARCHAR(64)  NOT NULL COMMENT '对应 wx_session_processed.session_id',
    speaker_json_file VARCHAR(256) NOT NULL COMMENT 'Speaker JSON 文件名（如 梦仙居慕兮老师_2026061311421076.json）',
    golden_nickname   VARCHAR(128) NOT NULL COMMENT '人工标注的正确昵称',
    label_type        ENUM('correction','verification') NOT NULL COMMENT 'correction=管线选错了, verification=管线选对了',
    annotated_by      VARCHAR(64)  DEFAULT NULL,
    annotated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note              VARCHAR(512) DEFAULT NULL,
    UNIQUE KEY uk_session_file (session_id, speaker_json_file)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- `label_type='verification'`：正向案例，`golden_nickname` 与管线 `speaker_binding_raw` 一致，仅做人工确认留痕。
- `label_type='correction'`：纠错案例，`golden_nickname` 为正确答案，用于驱动 Evolver 修复规则。

benchmark 读取逻辑：查询 `nickname_golden_label WHERE session_id=? AND speaker_json_file=?`，有记录则取 `golden_nickname`，无记录则 fallback 到 speaker JSON 的 `speaker_binding_raw`。



#### 附录：skill_self_evolution和opencode分工和密钥使用：

┌─────────────────────────────────────────┐  ┌─────────────────────────────────────┐
│          opencode 体系                    │  │      skill_self_evolution 体系       │
│                                          │  │                                     │
│  opencode.jsonc                          │  │  .env / SKILL_DEEPSEEK_API_KEY       │
│  ├─ provider: deepseek                   │  │  └─→ DEEPSEEK_API_KEY                 │
│  │  ├─ apiKey: sk-03ed...                │  │      └─→ DeepSeekClient (直连API)     │
│  │  └─ baseURL: api.deepseek.com/v1      │  │          └─→ 34个非harness脚本        │
│  └─ model: deepseek/deepseek-v4-pro      │  │          └─→ Consumer容器进化AI        │
│                          ▲               │  │                                     │
│  4 个 harness 脚本 ──────┘                │  │ 密钥: sk-af55...                     │
│  (只负责启动服务+发查询)                    │  │ 模型: deepseek-V4-PRO               │
│                                          │  │                                     │
│  密钥: sk-03ed...                         │  │                                     │
│  模型: deepseek-V4-PRO                     │  │                                     │
└─────────────────────────────────────────┘  └─────────────────────────────────────┘
harness executor.py 删掉了全部密钥注入逻辑，opencode 完全自治。两个体系密钥隔离、模型独立、边界清晰。

#### 附录：skill_self_evolution的AI调用日志

每次 `DeepSeekClient._do_chat()` 实际发出 HTTP 请求前，会记录一条 INFO 日志，格式：

```
DeepSeek API 调用 → model=deepseek-v4-pro tokens(max)=4096 caller=evolve_v4.py:evolve:L42
```

**字段说明**：

| 字段 | 说明 |
|---|---|
| `model` | 当前使用的模型名（来自 `DEEPSEEK_MODEL` 环境变量） |
| `tokens(max)` | 请求的 `max_tokens` 上限 |
| `caller` | `脚本名:函数名:L行号`，从调用栈回溯到第一个跳出 `deepseek.py` 的帧 |

**覆盖范围**：

- `skill_self_evolution` 的 34 个非 harness 脚本 + `SkillExecutor` / `Evolver`（全部走 `DeepSeekClient`）
- `housekeeping_ai_match` 的 Match Scoring / AI Structuring / Ping（复用同一 `DeepSeekClient`）

**审计价值**：当日志中出现同一 caller 高频调用时（如昨天的 8000 次），可直接定位源头脚本和函数，无需全网 grep。日志行由 structlog 输出到 skill execution log（JSONL），可通过 `caller` 字段聚合统计。

注意：opencode harness 脚本走的是 opencode server 自有的 API 调用路径，不经过 `DeepSeekClient`，因此不产生此类日志（使用 opencode 自身的用量统计）。



（二）发言人结构化规则的自我进化方案

### 现状：有两套「结构化」，职责不同----speaker-structurer Skill还是空壳，没补充内容没切换。前期直接用AI读session并给出第一版规则？？？

复用EvoSkill的prompt自主进化功能的分析参见E:\projects\skill_self_evolution\docs\adr\prompt_evolution_enhancement.md

| | structurer 1: 生产管线 | structurer 2: speaker-structurer Skill |
|---|---|---|
| **代码位置** | `RuleStructuringService`（~1350 行） | `backend/config/services/skill/speaker-structurer/` |
| **规则来源** | `structuring_classification_v1` / `shared_v1` / `order_v1` / `resume_v1`（四资产合并，由 VersionManager 热加载） | `rules_config.yaml`（~30 行，6 个字段各 1-3 条 regex） |
| **规则规模** | 数百条 pattern + canonical 别名表 + 地铁站正则 + negation_words + 学历映射… | 6 个字段：nickname / age / hometown / job / salary / experience |
| **后处理** | 重：`_build_order_item` / `_build_resume_item` 内做整数解析、手机号清洗、alias 映射、dict 编码、range check 等 | 无（正则捕获后直接返回） |
| **落地目标** | MySQL `wx_resume` / `wx_order` 生产表 | 未接线（`speaker-structurer` 从未被扫描器或 MQ 消费者调用） |
| **覆盖字段** | 几十个业务字段（工种、岗位、手机、学历、身高、驾照、省市区、地铁站、薪资上下限…） | 6 个（且字段名与生产表不对齐：`job` vs `job_code`、`hometown` vs `province`） |

### 设计意图

原来的计划：像 nickname-selector 替代 `_classify()` 一样，speaker-structurer 作为**声明式规则引擎**替代 `structuring_*_v1` 的生产角色，现有四资产 `RuleStructuringService` 作为硬代码降级。Evolver 在旁路验证并自动优化 `rules_config.yaml` 中的 pattern。

### 差距分析：当前不可行

nickname-selector 替代 `_classify()` 能成立的前提是被替代物足够简单（一个纯函数，输出 3 种分类标签）。但 `structuring_*_v1` 完全不满足这个前提：

| 对比维度 | nickname-selector | speaker-structurer（若要替代 structuring_*_v1） |
|---|---|---|
| **被替代物** | `_classify()` 纯函数 | `RuleStructuringService.classify_and_extract()` + `_build_*` 后处理链 |
| **后处理** | 无 | 整数解析、phone 清洗、alias 映射、dict 编码、range check、地铁站后缀处理… |
| **降级复杂度** | 调用一个函数 | 切换整个执行框架（SkillExecutor vs RuleStructuringService） |
| **出错影响** | 昵称显示错误（H5 可修复） | 年龄/薪资写错 → 匹配全盘错（不可逆） |
| **数据来源** | OCR block（有 bbox/confidence/band 等丰富信号） | 纯文本（无几何信号辅助判断） |

在补全到与 `structuring_*_v1` 同等成熟度之前（意味着重写 `RuleStructuringService` 的后处理链），让 Evolver 自动修改 pattern 是危险的。

### 务实路径：分三阶段

**阶段 1（近期，可在路径 1 闭环内做）：AI 验证旁车**

speaker-structurer 不替代生产管线，而是作为**旁路质检**：

- 输入：`structuring_*_v1` 从 speaker JSON 原文中提取的结构化字段
- 规则：`rules_config.yaml` 中的少量 regex（age / hometown / job / salary 等）
- AI：常识判断字段合理性（年龄 52 合理、999 不合理；籍贯「湖南」合理、「月亮」不合理）
- 输出：`is_failure` 标志 → JSONL → Evolver 可优化 `rules_config.yaml` 中的 pattern

这一阶段的 `rules_config.yaml` 范围很小（仅几个字段的验证规则），优化风险可控。

**阶段 2（中期）：字段提取规则进化**

在阶段 1 的 benchmark 积累足够（≥50 条标注案例）后，Evolver 可小范围优化 extraction pattern：

- 可控范围：`field_extractors` 中每个字段的 pattern 列表（增删改 regex）
- 不可控：不碰 canonical、alias、dict 映射等业务语义规则（这些只能人工维护）
- 误伤保护：benchmark 必须全部通过才允许生效

**阶段 3（远期，暂不排期）：声明式引擎替换生产管线**

当 speaker-structurer 积累足够的匹配度（benchmark 通过率 ≥ 现有 `RuleStructuringService`）且后处理逻辑全部迁移后，才考虑切换为声明式主链路，`RuleStructuringService` 降级为回退路径。

### 不建议：将 `structuring_*_v1` 纳入自我进化

这四份资产由 Version Management（Admin UI）人工维护，**不纳入 Evolver 自动优化**，原因：

1. **耦合太深**：每条 YAML pattern 命中后要走 `_build_order_item` / `_build_resume_item` 的复杂后处理，Evolver 对 YAML 的修改可能在代码侧静默出错
2. **影响面大**：直接写入生产表，错误不可逆
3. **领域知识壁垒**：canonical 别名（如「钟点工→小时工」）需要家政行业知识，DeepSeek 难以准确判断
4. **反馈信号弱**：只能靠用户手动点「匹配不正确」，数量极少，Evolver 长期缺数据

---




**上游2：prompt结果判断**（匹配评分）。
（三）匹配评分prompt的自我进化方案

等着AI模型进化或者客户反馈多了之后再做，先不做！！

AI 按 prompt 对简历-订单匹配进行语义评分（0-22 分），结果在 H5 页面展示。用户点击「匹配不正确」（可选补充不正确的原因）后写入 wx_match_feedback 表。Evolver 读取用户负面反馈，经 DeepSeek 分析后优化 prompt.yaml（需人工确认，因 prompt 结果具有概率性），同时可优化 rules_config 中各维度的分值与权重。

| | 上游1: 数据处理规则结果判断 | 上游2: prompt结果判断 |
|---|---|---|
| 适用范围 | 昵称选择（全部）+ 发言人结构化（仅 AI 验证旁车，阶段 1） | 匹配评分 |
| 失败信号 | AI 纠正了规则输出 → JSONL | 用户点击「匹配不正确」 → wx_match_feedback |
| 信号来源 | 机器（AI 自我检测） | 人类（H5 用户反馈） |
| Evolver 优化 | rules_config.yaml（昵称选择全范围；发言人结构化仅 field_extractors 的 pattern） | prompt.yaml + rules_config 维度分值 |
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

### 3.4 结构化日志（structlog）

整个进化链路使用 `structlog`（stdlib 集成）输出结构化日志。默认使用 `ConsoleRenderer`（开发环境彩色输出），设置 `STRUCTLOG_JSON=true` 环境变量可切换为 `JSONRenderer`（生产环境 / Docker）。

日志配置入口：`src/skill_self_evolution/logging.py`（`get_logger(__name__)` 返回已配置的 `structlog.BoundLogger`）。

#### 3.4.1 日志事件表

##### SkillExecutor（`executor.py`）

| 事件 | 级别 | 触发时机 | 关键字段 |
|------|------|---------|---------|
| `executor.start` | INFO | `run()` 入口 | `skill_name`, `ai_role`, `source`（`session_dir` / `candidates_path`), `trace_id` |
| `executor.config_validation_failed` | ERROR | Pydantic 校验 rules_config/prompt_config 失败 | `skill_name`, `error` |
| `executor.enrich_failure_ok` | INFO | `enrich_failure` 回调成功返回 | `session_dir`, `injected_keys`, `injected_count` |
| `executor.rule_stage_ok` | INFO | 规则阶段正常完成 | `candidates_count`, `filtered_count`, `result` |
| `executor.ai_validation_ok` | INFO | AI 验证返回 | `result`（`"合理"` / `"不合理"`）, `reason` |
| `executor.ai_reselection_ok` | INFO | AI 重选返回 | `result`（重选出的昵称） |
| `executor.jsonl_written` | INFO | JSONL 日志写入完成 | `trace_id`, `is_failure`, `no_valid_alternative`, `elapsed_ms`, `enrich_keys` |
| — | WARNING | `enrich_failure` 回调抛异常、AI 验证/重选异常、规则阶段异常、JSONL 写入失败 | 含 `exc_info` |

##### Evolver（`evolver.py`）

| 事件 | 级别 | 触发时机 | 关键字段 |
|------|------|---------|---------|
| `Evolver [skill] 开始进化分析` | INFO | `evolve()` 入口 | `skill_name`, `mode`, `min_failure_samples`, `dry_run` |
| `Evolver [skill] 日志文件不存在` | INFO | 当日 JSONL 不存在 | `skill_name`, `log_path` |
| `Evolver [skill] 读取 N 条 is_failure 记录` | INFO | JSONL 读取完成 | `skill_name`, 失败数 |
| `Evolver [skill] 失败样本不足` | INFO | 失败数 < `min_failure_samples` | `skill_name`, `got`, `need` |
| `Evolver [skill] 运行进化前/后 benchmark` | INFO | benchmark 执行 | `skill_name` |
| `Evolver [skill] 进化前/后 benchmark: N/M 通过` | INFO | benchmark 结果 | `skill_name`, 通过数, 总数 |
| `DeepSeek 分析请求失败` | WARNING | API 调用失败 | `skill_name`, `error` |
| `Evolver [skill] DeepSeek 未提出任何优化建议` | INFO | 分析返回空 | `skill_name` |
| `Evolver [skill] rules_config 已写入 MySQL + 同步到磁盘` | INFO | 写入成功 | `skill_name` |
| `Evolver [skill] prompt 已写入 MySQL` | INFO | 写入成功 | `skill_name` |
| `Evolver [skill] benchmark 退化 … 自动回滚` | WARNING | 通过数下降，触发回滚 | `skill_name`, `pass_before/total_before` → `pass_after/total_after` |
| `Evolver [skill] 反馈已记录 round=N outcome=X` | INFO | 进化反馈写入 MySQL | `skill_name`, `round`, `outcome` |
| — | WARNING | 日志读取失败、benchmark 异常、磁盘同步失败、反馈记录失败 | — |

##### enrich_failure 回调（`wx_session_scan_job.py`）

| 事件 | 级别 | 触发时机 | 关键字段 |
|------|------|---------|---------|
| `enrich_nickname_failure.start` | INFO | 开始读取 session 文件 | `session_dir`, `exists` |
| `enrich_nickname_failure.file_loaded` | INFO | 单个文件读取成功 | `file`（文件名）, `size_bytes` |
| `enrich_nickname_failure.file_not_found` | DEBUG | 文件不存在（如缺少 `customer_metadata.json`） | `file` |
| `enrich_nickname_failure.file_read_error` | WARNING | 文件读取异常 | `file`, `exc_info` |
| `enrich_nickname_failure.speaker_json_not_found` | DEBUG | 未找到 speaker JSON | `session_dir`, `total_json_files` |
| `enrich_nickname_failure.done` | INFO | 回调完成 | `session_dir`, `injected_keys`, `total_size_bytes` |

##### 扫描旁路（`wx_session_scan_job.py`）

| 事件 | 级别 | 触发时机 | 关键字段 |
|------|------|---------|---------|
| `evolution_sidecar.start` | INFO | 旁路开始 | `session_dir` |
| `evolution_sidecar.session_dir_not_found` | DEBUG | session 目录不存在 | `session_dir` |
| `evolution_sidecar.no_speaker_json` | DEBUG | speaker JSON 未生成 | `session_dir` |
| `evolution_sidecar.no_debug_session_derived` | DEBUG | debug_session_derived.json 不存在 | `session_dir` |
| `evolution_sidecar.no_rules_config` | WARNING | 无法加载 rules_config | `session_dir` |
| `evolution_sidecar.done` | INFO | 旁路完成 | `session_dir`, `source`, `result_text`, `has_warnings` |
| `evolution_sidecar.failed` | ERROR | 旁路异常 | `session_dir`, `exc_info` |

##### 其他模块

| 模块 | 关键事件 |
|------|---------|
| `config_loader.py` | `skill_config 表确认存在`, `skill_evolution_feedback 表确认存在`, `反馈记录写入`, `配置写入: name type vN`, `配置回滚成功: name type → vN` |
| `feedback_history.py` | `feedback.append`, `feedback.read`, `feedback.read_empty` |
| `feedback_descent.py` | `feedback_descent.start`, `.initial`, `.candidate`, `.eval`, `.improved`, `.no_improvement`, `.early_stop`, `.done` |
| `deepseek.py` | 熔断器冷却/触发/关闭, `DeepSeek 请求失败 (attempt)`, `DeepSeek 响应非 JSON` |
| `logger.py` | `Skill 日志写入失败` (WARNING) |
| `rule_runner.py` | `rule_runner 跳过非法规则`, `run_block_rules 跳过非法规则` |
| `run_cache.py` | `cache.init`, `.tree_hash`, `.miss`, `.hit`, `.corrupt`, `.set`, `.clear` |
| `parallel_eval.py` | `parallel.start`, `.task_ok`, `.task_timeout`, `.task_error`, `.parallel.done` |

#### 3.4.2 日志级别约定

| 级别 | 用途 |
|------|------|
| DEBUG | 无需关注的细节（文件未找到、缓存命中、cache 操作） |
| INFO | 正常路径关键节点（管线开始/阶段完成/写入成功/进化结论） |
| WARNING | 可恢复的异常（回调异常、API 失败、退化回滚、数值漂移超限） |
| ERROR | 不可恢复但已捕获（配置校验失败、规则阶段异常） |

#### 3.4.3 调用方约定

`housekeeping_ai_match` 项目侧（`wx_session_scan_job.py`）通过 `from app.logging import get_logger` 获取同一个 structlog logger，日志格式与框架侧完全一致。生产环境（Docker）通过 `app.logging.configure(use_colors=False)` 关闭颜色渲染。

---
### 3.3 分阶段实施安排

实施计划

**一期：路径 1（数据处理规则结果判断 → JSONL → Evolver）**

路径 1 基本通车，需补两个洞即可形成完整闭环。

已实现部分：

- JSONL 写入 — 昵称选择 / 发言人结构化（correction 角色）会写 `is_failure=true`

```
def _compute_is_failure(ai_role, rule_output, ai_validation, ai_reselection) -> bool:
    if ai_role == "enhancement":
        return False  # ← 匹配评分永远不写 is_failure
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
| `_apply_rules_changes` 升级 deep-merge | 当前只处理 int/float，需支持列表字段和嵌套 dict 的合并（复用已有 `_deep_update`，列表为全量替换） |
| 昵称选择 benchmark() 填充真实案例 | 64 条真实案例（已有 `real_failure_cases.json`），跑完整规则引擎验证 |
| 发言人结构化 benchmark() 填充真实案例 | M 条已标注原文（从 speaker JSON 中手工标注），验证少量字段（age/hometown/job/salary）的正则提取 + AI 常识验证正确率 |
| 昵称选择处理器读 rules_config 声明式规则 | 薄执行层消费 rejection_rules 做过滤 |
| 匹配评分处理器每维度分值为 YAML 可配置 | full_score / penalty 从 rules_config 读取 |
| `evolve.toml` mode `threshold_only` → `full` | 允许 Evolver 增删非数值规则 |
| `evolve.toml` `scripts` 开关 | `scripts = true` 允许 Evolver 提出需要写代码的新规则（如新增参数），触发下方 4 层约束；`false`则仅限纯配置规则 。local环境默认开启，test/prod环境默认关闭|

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
| 昵称选择处理器读 rules_config | ❌ 当前不读 | 需对接声明式规则 |
| 昵称选择 rules_config.yaml | ❌ 当前无声明式规则 | 需补充 rejection_rules |
| 昵称选择 / 发言人结构化 benchmark() | ❌ 当前空桩 | 需填充真实案例。发言人结构化仅覆盖少量字段的验证规则，不替代生产管线 |
| `evolve.toml` mode | ❌ 当前 threshold_only | 需放开为 full |

#### 3.4.3 执行步骤

| 序号 | 步骤 | 文件 | 改动说明 | 预估工作量 | 依赖 |
|---|---|---|---|---|---|
| 1 | `_apply_rules_changes` 升级 | `evolver.py` | 用 `_deep_update` 替换正则数值替换，支持列表全量替换、嵌套 dict 修改 | ~10 行 | — |
| 2 | 新增 `rule_runner.py` | `skill_self_evolution/rule_runner.py` | 通用函数：遍历规则链，执行 regex/prefix/length 匹配 + drop/remove_prefix 动作 | ~30 行 | — |
| 3 | 昵称选择处理器对接规则 | `skill/nickname-selector/scripts/run.py` | `_rule_extract()` 增加：读 `config["rules_config"]["rejection_rules"]`，对每条 candidate 调 `rule_runner` 过滤 | ~20 行 | 2 |
| 4 | 昵称选择 rules_config 补充 | `backend/config/services/skill/nickname-selector/rules_config.yaml` | 新增 `rejection_rules` 列表（正则/前缀/长度），覆盖现有 `system_prefix_drops` | 纯配置 | — |
| 5 | 昵称选择 benchmark 填充 | `backend/config/services/skill/nickname-selector/scripts/run.py` | 读 `real_failure_cases.json`（64 条），调 `execute()` 跑完整链路，统计通过数 | ~30 行 | 3 |
| 6 | 发言人结构化 benchmark 填充 | `backend/config/services/skill/speaker-structurer/scripts/run.py` | 预置 M=20 条已标注原文 + 期望字段（age / hometown / job / salary），验证正则提取 + AI 常识验证正确率。**不替代生产管线，仅旁路质检** | ~30 行 | — |
| 7 | evolve.toml mode → full | 昵称选择 的 `evolve.toml` | `mode = "threshold_only"` → `full`；新增配置说明 `scripts = true/false` 控制是否允许代码级新规则。**发言人结构化的 evolve.toml 暂不升级**（仅阶段 1 AI 验证旁车） | 1 行 | 1 |
| 8 | 端到端集成测试 | 测试脚本 | 造 JSONL → 跑 Evolver → 验 YAML 变更 → 验 benchmark 通过/回滚 | ~40 行 | 1-7 |
| 9 | 切回 pip 安装 | `pip install .` | 全量验证通过后，从 editable `-e` 切回 `pip install .`，确保生产环境使用固化的包副本 | 1 条命令 | 8 |

#### 3.4.4 依赖关系图

```
步骤1 (deep-merge)
  │
步骤2 (rule_runner.py)
  │
  ├──→ 步骤3 (昵称选择skill对接) ──→ 步骤5 (昵称选择 benchmark)
  │
  ├──→ 步骤4 (昵称选择 YAML)
  │
  └──→ 步骤6 (发言人结构化 benchmark)  ← 与 3/4/5 可并行（仅旁路质检，不涉及生产管线切换）
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
| V1 | deep-merge 列表全量替换 | 给定旧 YAML 含 `rejection_rules: [a, b]`，`changes = {"rejection_rules": [a, b, c]}`，合并后 YAML 含 `[a, b, c]` | 1 |
| V2 | deep-merge 嵌套值修改 | 给定 `nickname_thresholds.min_confidence: 0.7`，`changes = {"nickname_thresholds": {"min_confidence": 0.85}}`，合并后值为 0.85，其他字段不变 | 1 |
| V3 | deep-merge 保留注释 | 合并后 YAML 中方原有注释不丢失 | 1 |
| V4 | rule_runner 正则过滤 | `run_rejection_rules("警惕不实营销信息", [{type: regex, pattern: "^警惕", action: drop}])` → `None` | 2 |
| V5 | rule_runner 前缀去除 | `run_rejection_rules("姓名：张三", [{type: regex, pattern: "^姓名[：:]", action: remove_prefix}])` → `"张三"` | 2 |
| V6 | rule_runner 链式执行 | 输入 `"姓名：@test"`，依次过 remove_prefix → prefix drop，最终 → `None` | 2 |
| V7 | 昵称选择规则引擎生效 | 64 条真实案例，拒绝规则生效后"安全横幅""简历碎片"类 nickname 不再作为 result | 3+4 |
| V8 | 昵称选择手动新规则提升通过数 | 对 64 条案例手动写入一条新拒绝规则（如过滤时间戳格式 `\d{4}年\d{1,2}月`），benchmark 通过数应上升 | 3+4+5 |
| V9 | 昵称选择 benchmark 返回值正确 | `benchmark(evolver)` 返回 `(pass_count, 64, [...failures])`，`pass_count > 0` 且 `total_count = 64` | 5 |
| V10 | 发言人结构化 benchmark 返回值正确 | `benchmark(evolver)` 返回 `(pass_count, total, [...])`，`total_count ≥ 20`。仅覆盖 age/hometown/job/salary 四个字段的提取 + AI 常识验证 | 6 |
| V11 | Evolver rules_changes deep-merge | Evolver 对 JSONL 分析后生成的 `rules_changes` 能正确 deep-merge 到 YAML（列表字段为全量替换） | 1+8 |
| V12 | Evolver 自动写入 | dry_run=False 时，rules_changes 成功写入 MySQL（rules_config.yaml 内容变更） | 1+8 |
| V13 | Evolver 退化回滚 | 故意写入一条会导致 pass_after < pass_before 的坏规则 → 自动 rollback → proposal.rolled_back = True | 8 |
| V14 | Evolver 正常接受 | 写入一条提升通过数的规则 → proposal.applied = True | 8 |
| V15 | pip 安装固化 | `pip install .` 成功后 `pip show skill_self_evolution` 指向 site-packages（非 E:\projects\skill_self_evolution） | 9 |

#### 3.4.6 风险点

| 风险 | 影响 | 缓解 |
|---|---|---|
| ruamel.yaml round-trip 在 `_deep_update` 合并后可能丢注释 | V3 失败 | 步骤 1 完成后单独验证 V3，若不通过则换用 ruamel 的 `CommentToken` API |
| 昵称选择的 `real_failure_cases.json` 依赖本地 session 目录存在 | V7/V8 因文件缺失无法跑 | 处理器增加文件不存在的容错（返回错误标记），benchmark 统计中计入 |
| 发言人结构化没有现成标注数据 | V10 需从零造数据 | 从已有 speaker JSON 中手工标注 M=20 条优先。覆盖面窄（仅 age/hometown/job/salary），不追求全字段覆盖 |

#### 3.4.7 rules_config 运行时架构 — MySQL 为主源

**问题**：Evolver 将优化后的 `rules_config` 写入 MySQL（通过 `ConfigVersionManager.save()`），但 `execute()` 只读磁盘 YAML。Evolver 改动无法实时生效。

**方案**：MySQL 作主源（SSOT），磁盘 YAML 作初始种子和 git 可追踪副本。

```
┌─ 首次启动（种子阶段） ───────────────────────────────────────┐
│ _seed_mysql_from_disk()                                      │
│   disk YAML → ConfigVersionManager.save() → MySQL           │
│   仅在 MySQL 中无该 Skill 配置时执行一次                        │
└──────────────────────────────────────────────────────────────┘

┌─ 运行时（每次 execute()） ────────────────────────────────────┐
│ _load_rules_from_mysql()                                     │
│   ConfigVersionManager.load() ← MySQL（实时取最新版本）        │
│   优先级：MySQL → 种子写入 → 调用方传入（回退）                  │
└──────────────────────────────────────────────────────────────┘

┌─ Evolver 产出优化 ───────────────────────────────────────────┐
│ 1. _version_mgr.save() → MySQL（版本号递增 + 历史归档）       │
│ 2. _sync_rules_to_disk() → disk YAML（同步副本，git 可追踪）   │
│ 3. benchmark 验证                                             │
│    ├─ 通过 → 维持 MySQL + 磁盘                                │
│    └─ 退化 → rollback MySQL → 读回旧配置 → _sync_rules_to_disk│
└──────────────────────────────────────────────────────────────┘
```

**关键函数**：

| 函数 | 位置 | 职责 |
|---|---|---|
| `_load_rules_from_mysql()` | 昵称选择处理器 | 每次执行从 MySQL 拉取最新 rules_config |
| `_seed_mysql_from_disk()` | 昵称选择处理器 | 首次运行时将 disk YAML 写入 MySQL |
| `_sync_rules_to_disk(yaml)` | `evolver.py::Evolver` | MySQL → 磁盘同步（写入后 + 回滚后） |

**数据流方向**：

- **读**：MySQL → `run.py::execute()`（每次调用都取最新版）
- **写**：Evolver → MySQL（版本归档） → disk YAML（同步副本）
- **回滚**：Evolver → MySQL rollback → 读回旧版 → disk YAML 同步

**版本追踪**：MySQL `skill_config_history` 表自动归档每次变更，`skill_config.version` 递增。git 追踪 disk YAML 变更。

#### 3.4.7.1 管线消费方的热加载

上述 MySQL → `execute()` 链路解决了 **Skill 旁路** 的实时生效。但 **管线内 `nickname_ocr_simple.py`** 也需消费 `rules_config.yaml`（替代 `_classify()` 旧硬编码），该侧需同步考虑：

**建议方案**（列入开发计划）：

| 组件 | 当前状态 | 需要 |
|---|---|---|
| `nickname_ocr_simple.py` | 硬编码 `_classify()`，不读任何 YAML | 植入 `_load_rules_from_mysql()` 或读磁盘 YAML，支持热刷新 |
| 扫描器 `SessionBatchScanner` | 每个 session 调一次 `_classify()` | 若 rules 变更频繁（Evolver 每天改），需进程内缓存 + TTL 失效，避免每次读 MySQL |

可复用 `VersionManager` 的 `get_rule_structuring_runtime()` 缓存模式（snapshot key = 版本号，变更时自动刷新），与 `structuring_*_v1` 的热加载机制一致。

#### 3.4.8 扩展执行步骤（correctness_criteria + evolve_prompt + MySQL 同步）

| 序号 | 步骤 | 文件 | 改动说明 | 依赖 |
|---|---|---|---|---|
| 10 | rules_config 新增 correctness_criteria | `rules_config.yaml` | 结构化可执行判据：`bad_categories[]`（6 类 + patterns[]）+ `verification_conditions[]`（A→B→C 三条件） | 4 |
| 11 | run.py 消费 correctness_criteria | `run.py` | `_judge_correctness()` 遍历 bad_categories 做正则匹配；benchmark 改用 criteria 判断 | 10 |
| 12 | Skill 级 evolve_prompt.yaml | `evolve_prompt.yaml` | 领域知识注入：参考资料链接 + 正确性判据 + 已知坏类别 + 规则类型说明 | — |
| 13 | 框架 evolve_prompt 解除限制 | `defaults/evolve_prompt.yaml` | 允许新增/修改/删除 correctness_criteria + rejection_rules（不限于数值） | — |
| 14 | execute() MySQL 为主源 | `run.py` | `_load_rules_from_mysql()` + `_seed_mysql_from_disk()`，Evolver 改动实时生效 | 1 |
| 15 | Evolver 写 MySQL 同步磁盘 | `evolver.py` | `_sync_rules_to_disk()` — 写入/回滚后同步 disk YAML | 1 |

#### 3.4.9 扩展验收标准

| 编号 | 验收项 | 通过标准 | 关联步骤 |
|---|---|---|---|
| V16 | correctness_criteria 可执行 | `_judge_correctness()` 对 10 条正/反例全部判断正确 | 10+11 |
| V17 | Evolver 能产出改进建议 | 64 条 real_failure_cases 输入 → Evolver 产出≥1 条新 rejection_rule 或 bad_category | 12+13 |
| V18 | MySQL 为主源实时生效 | Evolver dry_run=False 写入 MySQL → 下一次 execute() 读到新配置 | 14+15 |
| V19 | 写 MySQL 同步磁盘 | Evolver 写入后 disk YAML 内容与 MySQL 一致 | 15 |
| V20 | 磁盘种子可回读 | 清空 MySQL 该 Skill 配置 → execute() 首次调用从 disk YAML 自动恢复 | 14 |

#### 3.4.10 enrich_failure 回调测试用例

`enrich_failure` 是 `SkillExecutor` 新增的可选回调参数，用于在写 JSONL 时将 session 文件内容注入 `input_summary`。
测试文件：`tests/test_executor.py`。

| 编号 | 测试用例 | 输入 | 预期结果 |
|---|---|---|---|
| ENR1 | 回调被调用且结果注入 JSONL | `session_dir` 含完整 session 文件，传入有效 `enrich_failure` 回调 | JSONL 条目 `input_summary` 包含 `debug_session_derived_json`、`speaker_json`、`customer_metadata_json` 三个键 |
| ENR2 | 回调未传入时不影响正常流程 | `session_dir` 含文件，`enrich_failure=None` | JSONL 正常写入，`input_summary` 仅含 `candidates_path`，无额外注入字段 |
| ENR3 | 回调异常不阻塞管线 | `enrich_failure` 回调解内部抛异常 | `SkillExecutor.run()` 正常完成返回，仅输出 warning 日志，JSONL 仍写入（无注入字段） |
| ENR4 | 仅 session_dir 模式触发回调 | 传入 `session_dir`（非 `candidates_path`） | `enrich_failure(session_dir)` 被调用，注入数据写入 JSONL |
| ENR5 | candidates_path 模式不触发回调 | 传入 `candidates_path`（非 `session_dir`） | `enrich_failure` 不被调用，`self._enrichment` 保持空 dict |
| ENR6 | 部分文件缺失时优雅降级 | `session_dir` 缺少 `customer_metadata.json` | JSONL 仅含 `debug_session_derived_json` + `speaker_json`，不报错 |
| ENR7 | 文件内容为完整 JSON 字符串 | `debug_session_derived.json` 含 `blocks[]` 等字段 | `input_summary.debug_session_derived_json` 是完整 JSON 字符串（非截断/过滤），含 `blocks[].text/class/band/bbox_xyxy/confidence/speaker_bands[]` |

**测试环境要求**：测试无需真实 DeepSeek API 调用 — 使用 `monkeypatch` 或 `unittest.mock` mock `DeepSeekClient.chat`/`.chat_json` 返回预置响应，仅验证回调注入的数据流。

**验收标准**（V21-V22，关联 enrich_failure 回调机制）：

| 编号 | 验收项 | 通过标准 |
|---|---|---|
| V21 | enrich_failure 数据注入完整性 | ENR1-ENR7 全部通过 |
| V22 | 项目侧 `_enrich_nickname_failure` 端到端 | `housekeeping_ai_match` 的 `wx_session_scan_job._enrich_nickname_failure()` 在真实 session 目录下返回正确的三个键值对，JSONL 可被 Evolver 解析 |
