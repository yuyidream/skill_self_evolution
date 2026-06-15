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


调用方在现有 SKILL 仅靠固定规则时，可集成 skill_self_evolution 开源框架实现 AI 辅助判断与离线自进化。

使用流程：
（1）调用方准备4个文档：
    将业务逻辑（规则化判断规则）封装为 `scripts/run.py`（规则化判断脚本，例如测试用例脚本，例如从文档提取阿姨年龄的脚本），该脚本可选通过 `rules_config.yaml`（规则阈值/黑名单等可调参数）调整规则行为。

    `skill.md` 为 AI 可读的知识文档，描述 Skill 的输入输出、流程和 ai扮演的角色，流程中使用的脚本 `scripts/run.py`和规则配置`rules_config.yaml`的相关说明
    `prompt.yaml` 是给skill_self_evolution开源框架里AI判断模块的提示词

（2）在业务关键节点（例如识别出微信发言人昵称后），调用方调用skill_self_evolution开源框架里的SkillExecutor模块。
（3）SkillExecutor模块使用 prompt.yaml 中的常识判断提示词，让 skill_self_evolution里的判断AI模块（目前使用DeepSeek） 进行 AI 验证：
    A. AI 判断结果合理 → 返回规则结果（ai_validated=true）。通知SkillExecutor模块写日志

    B. AI 判断不合理 → SkillExecutor模块反馈给调用方，调用方提供新的候选方案（例如昵称后续列表）给SkillExecutor模块，SkillExecutor模块提供给AI重新进行判断。返回步骤A。通知SkillExecutor模块写日志

   C. SkillExecutor模块将本次执行记录（含规则结果、AI 验证/重选、最终输出）写入
       /data/skill-logs/{skill_name}/{date}.jsonl 日志。

（4）skill_self_evolution里的自进化模块 Evolver 离线运行（通常次日定时调度）：
    读取昨日 JSONL 日志中 is_failure=true 的记录，当异常案例 ≥10 条时，
    将当前 rules_config / prompt 配置与失败案例一并提交大模型（当前使用 DeepSeek） 分析，
    提出 rules_config.yaml（仅阈值调整）和 prompt.yaml（措辞优化）的改进提案。
    按 evolve.toml 权限配置自动写入 MySQL（当前默认） ，或生成改进版本供人工审核（当前未实现）。
    写入后重跑 benchmark，若结果退化则自动回滚到上一版本。


调用方在需要进化已有SKILL（当前只支持固定规定和配置）时，PIP使用此skill_self_evolution开源框架

使用流程：
（1）调用方使用当前只支持rules.py（规则化判断的固定脚本），rules_config.yaml（规则化的可选用户配置）的skill.md，按规则进行业务判断
（2）在合适的节点（例如识别出微信发言人后），调用方通过prompt.yaml让skill_self_evolution开源框架
的判断AI模块（目前使用deepseek）进行常识化判断（例如发言人昵称不能是系统时间）：
    A.如果符合常识，告知调用方结果正常
    B. 如果有异常则根据skill.md里指明的业务资料（例如metadata.json）进行重新判断，挑选出合适的结果返回给调用方。
        同时将此异常案例发送给skill_self_evolution开源框架
的自进化模块EvoSkill，异常案例数量达到阈值后，自进化模块EvoSkill重新推理，提出skill.md，rules.py（规则化判断的固定脚本），rules_config.yaml（规则化的可选用户配置）的更新版本让用户确认。




---

## 3. 非功能需求

### 3.1 性能需求

每天1000人访问


### 3.2 安全需求

使用华为云安全相关功能


### 3.3 可用性需求

系统稳定，99.9%的时间可访问

---
