"""代码自动生成测试：AI 生成消费新 YAML 参数的代码

场景：card_binding 新增 min_overlap_area_ratio 和 ambiguity_tie_ratio 参数
目标：AI 在 nickname_ocr_simple.py 的 _resume_thumb_bindings_and_orphans 函数中
      生成消费这两个参数的代码

验证：CodeGuard 静态检查 → pytest 单元测试
"""
import json
import asyncio
import os
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

os.environ["DEEPSEEK_API_KEY"] = "sk-6447e6c91a6f45a0b29373af216ea530"
os.environ["DEEPSEEK_API_BASE"] = "https://api.deepseek.com/v1"
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"

sys.path.insert(0, "E:/projects/skill_self_evolution/src")

from skill_self_evolution.deepseek import DeepSeekClient
from skill_self_evolution.code_guard import CodeGuard, extract_context
from skill_self_evolution.gate_pipeline import GatePipeline


PROJECT_ROOT = Path("E:/projects/housekeeping_ai_match")
TARGET_FILE = PROJECT_ROOT / "scripts/wx_match/processor/nickname_ocr_simple.py"
TARGET_FUNC = "_resume_thumb_bindings_and_orphans"
SKILL_MD = PROJECT_ROOT / "backend/config/services/skill/nickname-selector/SKILL.md"


async def main():
    print("=" * 60)
    print("代码自动生成测试 — card_binding 新参数消费")
    print("=" * 60)

    # 1. 提取函数上下文
    print("\n[Step 1] 提取函数上下文 (FunctionContext)...")
    try:
        ctx = extract_context(str(TARGET_FILE), TARGET_FUNC)
        print(f"  is_method: {ctx.is_method}")
        print(f"  params: {ctx.params}")
        print(f"  self_forbidden: {ctx.self_forbidden}")
        context_text = ctx.context_for_prompt()
    except Exception as e:
        print(f"  ERROR: {e}")
        return

    # 2. 读取 SKILL.md 作为领域知识
    print("\n[Step 2] 读取 SKILL.md 领域知识...")
    skill_md_text = ""
    if SKILL_MD.exists():
        skill_md_text = SKILL_MD.read_text(encoding="utf-8")[:3000]
        print(f"  SKILL.md: {len(skill_md_text)} chars")
    else:
        print("  SKILL.md 不存在，使用内置知识")

    # 3. 读取当前函数源码
    print(f"\n[Step 3] 读取目标函数: {TARGET_FUNC}...")
    target_code = TARGET_FILE.read_text(encoding="utf-8")
    lines = target_code.split("\n")

    # 找到函数定义行
    func_start = None
    for i, line in enumerate(lines):
        if f"def {TARGET_FUNC}(" in line:
            func_start = i
            break

    if func_start is None:
        print(f"  ERROR: 找不到函数 {TARGET_FUNC}")
        return

    # 找到函数结束（基于缩进）
    func_end = func_start + 1
    base_indent = len(lines[func_start]) - len(lines[func_start].lstrip())
    for i in range(func_start + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and line.strip():
            func_end = i
            break
    else:
        func_end = len(lines)

    func_code = "\n".join(lines[func_start:func_end])
    print(f"  函数行范围: {func_start+1}-{func_end} ({func_end - func_start} 行)")

    # 4. 读取当前 YAML 规则
    print("\n[Step 4] 读取当前 rules_config.yaml 中的 card_binding 参数...")
    import os as _os
    _os.environ['DB_PASSWORD'] = 'local_root_123'
    from skill_self_evolution.config_loader import ConfigVersionManager
    from ruamel.yaml import YAML
    yaml_safe = YAML(typ='safe')

    mgr = ConfigVersionManager()
    raw = mgr.load_raw("nickname-selector", "rules_config")
    config = yaml_safe.load(raw) if raw else {}
    vc = config.get("correctness_criteria", {}).get("verification_conditions", [])
    card_binding = [v for v in vc if v.get("id") == "card_binding"]
    mgr.close()

    if card_binding:
        cb = card_binding[0]
        print(f"  min_overlap_area_ratio: {cb.get('min_overlap_area_ratio', 'N/A')}")
        print(f"  ambiguity_tie_ratio: {cb.get('ambiguity_tie_ratio', 'N/A')}")
        new_params_yaml = f"""card_binding:
  min_overlap_area_ratio: {cb.get('min_overlap_area_ratio', 0.3)}
  ambiguity_tie_ratio: {cb.get('ambiguity_tie_ratio', 0.05)}
  description: "{cb.get('description', '')}" """
    else:
        print("  card_binding 不存在！使用默认参数")
        new_params_yaml = """card_binding:
  min_overlap_area_ratio: 0.3
  ambiguity_tie_ratio: 0.05"""

    # 5. 构造 prompt
    print("\n[Step 5] 调用 DeepSeek 生成代码...")

    system = """你是一个 Python 代码专家。根据 YAML 配置变更，在目标函数中生成消费新参数的代码。

要求：
1. 只修改指定函数内部，不改变函数签名
2. 最多 15 行新增代码
3. 使用已有的变量和参数，不要编造不存在的变量
4. 不要在模块级函数中使用 self
5. 不要使用 global 语句
6. 不要使用 random / time.time / datetime.now 等非确定性调用
7. 不要使用裸 except:
8. 不要在循环内使用 logging

输出格式（纯代码，不要 markdown 包裹）：
只输出需要插入到函数中的代码片段，包含必要的注释说明插入位置。"""

    user = f"""## 目标函数上下文
{context_text}

## SKILL.md 领域知识
{skill_md_text[:2000]}

## 当前函数代码 ({TARGET_FUNC})
```python
{func_code}
```

## YAML 新增参数
```yaml
{new_params_yaml}
```

## 任务
在 `{TARGET_FUNC}` 函数中生成消费 `min_overlap_area_ratio` 和 `ambiguity_tie_ratio` 的代码。

具体要求：
1. min_overlap_area_ratio (默认 0.3)：当重叠区域面积占卡片面积的比例低于此值时，不绑定该卡片
2. ambiguity_tie_ratio (默认 0.05)：当两张卡片在重叠区域中面积差小于此比例时，标记为不确定（renxin_system）

请输出需要插入到函数中的代码片段，标注插入位置（在哪个变量/循环之后）。
只输出代码，不要 markdown 包裹，不要解释。"""

    client = DeepSeekClient(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        api_base=os.environ["DEEPSEEK_API_BASE"],
        model=os.environ["DEEPSEEK_MODEL"],
    )

    try:
        response = await client.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        generated_code = response.content.strip()
        if generated_code.startswith("```"):
            # 去掉 markdown 包裹
            generated_code = generated_code.split("```")[1]
            if generated_code.startswith("python"):
                generated_code = generated_code[6:]
        generated_code = generated_code.strip()

        print(f"\n  生成的代码 ({len(generated_code)} 字符):")
        print("  " + "-" * 40)
        for line in generated_code.split("\n"):
            print(f"  | {line}")
        print("  " + "-" * 40)
    except Exception as e:
        print(f"  DeepSeek 调用失败: {e}")
        return

    # 6. CodeGuard 静态检查
    print("\n[Step 6] CodeGuard 静态检查...")
    guard = CodeGuard()

    # 将生成的代码与函数代码合并做检查
    test_code = func_code + "\n" + generated_code
    temp_file = Path("E:/tmp/_evolve_gen_test.py")
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_text(f"def dummy():\n    pass\n\n{test_code}", encoding="utf-8")

    try:
        issues = guard.check_files([str(temp_file)])
        if issues:
            errors = [i for i in issues if i.level == "error"]
            warnings = [i for i in issues if i.level == "warning"]
            print(f"  错误: {len(errors)}  警告: {len(warnings)}")
            for err in errors[:5]:
                print(f"    ❌ [{err.rule}] L{err.line}: {err.message}")
            for warn in warnings[:5]:
                print(f"    ⚠️ [{warn.rule}] L{warn.line}: {warn.message}")

            if errors:
                print("\n  ⚠️ 代码有静态错误，需要修复")
            else:
                print("\n  ✅ 静态检查通过（仅警告）")
        else:
            print("  ✅ 静态检查通过（零问题）")
    except Exception as e:
        print(f"  CodeGuard check 失败: {e}")

    # 7. 门禁管道测试
    print("\n[Step 7] GatePipeline 门禁检查...")
    try:
        gate = GatePipeline(max_retries=1)

        # Layer 1: 静态检查
        result_l1 = gate.check_static([str(temp_file)])
        print(f"  Layer 1 (静态检查): {'✅ PASS' if result_l1 else '❌ FAIL'}")

        # Layer 2: 简单语法检查 (用 compile 验证)
        try:
            compile(test_code, "<generated>", "exec")
            print("  Layer 2 (语法检查): ✅ PASS")
        except SyntaxError as se:
            print(f"  Layer 2 (语法检查): ❌ FAIL — {se}")

    except Exception as e:
        print(f"  GatePipeline 失败: {e}")

    # 清理
    if temp_file.exists():
        temp_file.unlink()

    # 8. 总结
    print("\n" + "=" * 60)
    print("代码自动生成测试总结")
    print("=" * 60)
    print(f"  生成代码行数: {len(generated_code.split(chr(10)))}")
    print(f"  生成代码字符数: {len(generated_code)}")
    print(f"  测试文件: {TARGET_FILE}")
    print(f"  目标函数: {TARGET_FUNC}")

if __name__ == "__main__":
    asyncio.run(main())
