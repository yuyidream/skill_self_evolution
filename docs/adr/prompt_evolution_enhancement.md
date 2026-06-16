# ADR: prompt 自动进化功能复用与增强评估

> 状态：**已实施** ✅
> 日期：2026-06-16
> 实施日期：2026-06-16
> 源：EvoSkill `evolution_mode: "prompt_only"` + `prompt_proposer` + `prompt_generator`

---

## 一、EvoSkill 的 prompt 进化机制

EvoSkill 通过 `evolution_mode = "prompt_only"` 支持专门针对系统 prompt 的进化：

```
1. Proposer 分析失败 → 提出 prompt 层面的改进建议
2. Prompt Generator 根据建议重写系统 prompt
3. 写入 prompt.txt → Agent 下次执行时自动加载
4. Evaluator 评估新 prompt 效果
5. Frontier 接受或丢弃
```

关键代码流：

```python
# config.py
evolution_mode: EvolutionMode = "skill_only"  # 或 "prompt_only"

# helpers.py
def build_prompt_query(proposer_trace, original_prompt) -> str:
    return f"""## Original Prompt\n{original_prompt}\n
    ## Proposed Change\n{proposer_trace.output.proposed_skill_or_prompt}\n
    ## Justification\n{proposer_trace.output.justification}"""

def build_prompt_query_from_prompt_proposer(proposer_trace, original_prompt) -> str:
    return f"""## Original Prompt\n{original_prompt}\n
    ## Proposed Change\n{proposer_trace.output.proposed_prompt_change}\n
    ## Justification\n{proposer_trace.output.justification}"""

def update_prompt_file(file_path, new_prompt) -> None:
    file_path.write_text(new_prompt.strip())
```

---

## 二、我们已有的 prompt 进化基础

### 2.1 DeepSeek 已输出 prompt_changes

```20:48:E:\projects\skill_self_evolution\src\skill_self_evolution\evolver.py
import json
from skill_self_evolution.logging import get_logger
# ...
from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.logger import _get_log_dir
from skill_self_evolution.models import EvolveProposalModel, EvolvePromptYamlModel, EvolveTomlModel
```

```299:315:E:\projects\skill_self_evolution\src\skill_self_evolution\evolver.py
        proposal.rules_changes = analysis.get("rules_changes", {})
        proposal.prompt_changes = analysis.get("prompt_changes", {})

        if not proposal.rules_changes and not proposal.prompt_changes:
            logger.info("Evolver [%s] DeepSeek 未提出任何优化建议", self.skill_name)
            return proposal

        # 6. 生成 YAML 文本
        auto_cfg = self.evolve_toml.get("evolve", {}).get("auto_modify", {})

        if proposal.rules_changes and auto_cfg.get("rules_config", False):
            rules_threshold = auto_cfg.get("rules_config", {})
            max_pct = rules_threshold.get("max_change_percent", 20) if isinstance(rules_threshold, dict) else 20
            proposal.rules_text = self._apply_rules_changes(current_rules, proposal.rules_changes, max_pct)

        if proposal.prompt_changes and auto_cfg.get("prompt", False):
            proposal.prompt_text = self._apply_prompt_changes(current_prompt, proposal.prompt_changes)
```

### 2.2 prompt 写回 MySQL + 磁盘

```330:335:E:\projects\skill_self_evolution\src\skill_self_evolution\evolver.py
            if proposal.prompt_text and auto_cfg.get("prompt", False):
                proposal.prompt_text, lint_errors = lint_and_fix_yaml(proposal.prompt_text)
                if lint_errors:
                    logger.warning("Evolver [%s] prompt lint issues: %s", self.skill_name, lint_errors)
                self._version_mgr.save(self.skill_name, "prompt", proposal.prompt_text)
                logger.info("Evolver [%s] prompt 已写入 MySQL", self.skill_name)
```

### 2.3 evolve.toml 控制开关

```toml
[evolve.auto_modify]
rules_config = { mode = "full" }
prompt = true
```

---

## 三、当前不足

### 3.1 DeepSeek 分析模板偏重 rules_config

默认 `evolve_prompt.yaml` 中 prompt 相关指引只有一行：

```yaml
2. prompt.yaml 需要调整什么？（措辞、示例、temperature）
```

与 rules_config 的详细指引（bad_categories 结构、rejection_rules 格式、deep-merge 语义等）相比，prompt 部分几乎没有结构化的指导。

### 3.2 不支持 prompt-only 模式

当前 `ai_role` 只有两个值：
- `correction`：正常进化（rules_config + prompt）
- `enhancement`：不进化

没有"只进化 prompt"的模式。

### 3.3 prompt 变更无专项 benchmark

`benchmark_fn` 同时测 rules_config 和 prompt 的联合效果，无法区分到底是哪个改动起了作用。

### 3.4 无 prompt 变体对比

EvoSkill 的 `prompt_only` 模式下，每轮可以生成多个 prompt 变体，取最优。我们是单一的 prompt_changes 直接 deep-merge。

---

## 四、增强方案

### 4.1 增加 prompt-only 模式

在 `ai_role` 枚举中新增 `"prompt_only"` 或新增独立的 `evolution_mode` 参数：

```python
class Evolver:
    def __init__(self, *, evolution_mode: str = "both", ...):
        """
        evolution_mode: "both" | "rules_only" | "prompt_only"
        """
```

当 `evolution_mode="prompt_only"` 时：
- 跳过 rules_config 的加载和变更
- DeepSeek 分析 prompt 只输出 `prompt_changes`
- 加载专用的 `evolve_prompt_only.yaml`（见 4.2）

### 4.2 增强默认 prompt 分析模板

```yaml
# defaults/evolve_prompt_only.yaml
system: |
  你是 prompt 工程专家。分析 Skill 执行日志中的失败案例，优化 AI prompt 的措辞和逻辑。

analyze_template: |
  Skill：{{skill_name}}
  当前 prompt：{{current_prompt}}

  历史进化反馈：{{feedback_history}}

  失败案例：{{failure_logs}}

  请分析 prompt 层面的改进方向：

  1. system_prompt 是否需要更清晰的角色定义？
  2. user_template_validate 判断逻辑是否需要修正？
     - 当前判断标准是否过于宽松/严格？
     - 是否需要增加新的判断维度（如卡片布局、昵称位置上下文）？
  3. user_template_reselect 重选逻辑是否需要改进？
     - 候选列表的排序或筛选是否合理？
     - 是否需要增加「不确定则不选」的约束？
  4. 是否需要新增 examples 字段来引导 AI 行为？
  5. 措辞和格式是否清晰无误导？

  输出 JSON：
  {
    "prompt_changes": {
      "system_prompt": "新的系统提示词（或省略不改）",
      "user_template_validate": "新的验证提示词样本（或省略不改）",
      "user_template_reselect": "新的重选提示词样本（或省略不改）",
      "examples": ["示例1", "示例2"]
    }
  }

  注意：
  - 仅修改真正需要改变的部分，其他字段省略
  - 保持 YAML 模板变量 {{result}} / {{candidates}} 等不变
```

### 4.3 变更范围

| 文件 | 改动 | 工作量 |
|---|---|---|
| `evolver.py` | 新增 `evolution_mode` 参数 + 模式分支逻辑 | ~30 行 |
| `evolver.py` | `prompt_only` 模式下跳过 rules 相关代码 | ~15 行 |
| `defaults/evolve_prompt_only.yaml` | 新增专用 prompt 分析模板 | ~50 行（新建文件） |
| `models.py` | `EvolveTomlModel` 增加 evolution_mode 字段 | ~10 行 |

**总计**：约 100 行代码

---

## 五、结论

**已实施。** prompt 的自动进化基础已具备。增强方案包括：`evolution_mode` 参数支持 `prompt_only` 模式、专用分析模板 `evolve_prompt_only.yaml`、evolution_mode 控制下的规则加载和写入分支。

---

## 六、实际实施详情

### 6.1 evolver.py 变更

| 变更点 | 说明 |
|---|---|
| 新增 `evolution_mode` 参数 | `Literal["both", "rules_only", "prompt_only"]`，默认 `"both"` |
| `evolve()` mode 分支 | `prompt_only` 模式下跳过 rules_config 加载/写入；`rules_only` 模式下跳过 prompt 加载/写入 |
| `_analyze_failures()` 模板选择 | `prompt_only` 时自动加载 `defaults/evolve_prompt_only.yaml`，其他模式用 `defaults/evolve_prompt.yaml` |

### 6.2 新增 defaults/evolve_prompt_only.yaml

专用 prompt 进化模板，包含：
- system_prompt 清晰度检查
- user_template_validate 逻辑指导（宽松/严格、判断维度、示例）
- user_template_reselect 重选逻辑指导（排序、保守策略、多维度评估）
- examples 字段引导
- 措辞和格式审查
- 明确禁止输出 rules_changes 字段
- 历史反馈参考规则
