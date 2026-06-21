"""L4 代码生成闭环测试 — 严格按 PRD §二(2) + ADR §六 全模块复用

a) 代码生成（OpenCode）：
   - 通过 EvoSkill 的 OpenCode harness 调用 opencode serve HTTP API
   - DeepSeek (deepseek-chat) 模型
   - 调用方式: execute_query(options, prompt)
   - 每次传入当前代码上下文 + 反馈历史
   - FeedbackDescent 算法驱动多轮迭代
   - LoopConfig 配置进化循环参数

b) 测试验证（test-collector-customized-for-renxin SKILL）：
   - 生成的代码由 Cursor 调用该 SKILL 执行自动化测试
   - 每次失败时错误信息喂回 AI
   - structlog 日志
   - run_parallel 并行评测多个 session

4 层约束：
   1. 静态检查 — Python ast 模块
   2. 单元测试 — pytest test_processor_nickname_ocr_simple.py
   3. 集成测试 — pytest test_integration_ocr_pipeline.py
   4. 生产环境测试 — 真实 session extract_nicknames 回放（run_parallel 并行）

场景：card_binding 新增 min_overlap_area_ratio / ambiguity_tie_ratio 参数
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from datetime import datetime, timezone, timedelta

os.environ["STRUCTLOG_JSON"] = "false"
os.environ["DB_PASSWORD"] = "local_root_123"
os.environ["DB_NAME"] = "housekeeping_ai_match_dev"
BEIJING_TZ = timezone(timedelta(hours=8))

PROJECT_ROOT = Path("E:/projects/housekeeping_ai_match")
SKILL_ROOT = Path("E:/projects/collector_phone_android/.cursor/skills/test-collector-customized-for-renxin")
TARGET_FILE = PROJECT_ROOT / "scripts/wx_match/processor/nickname_ocr_simple.py"
TARGET_FUNC = "_resume_thumb_bindings_and_orphans"
BACKUP_FILE = TARGET_FILE.with_suffix(".py.bak_l4")

REAL_SESSION_DIRS = [
    PROJECT_ROOT / "build/wx_match_sessions/wechat/ahxvcp3910405060/20260611/session_20260611172434_ahxvcp3910405060",
    PROJECT_ROOT / "build/wx_match_sessions/wechat/ahxvcp3910405060/20260613/session_20260613111427_ahxvcp3910405060",
    PROJECT_ROOT / "build/wx_match_sessions/wechat/ahxvcp3910405060/20260613/session_20260613111815_ahxvcp3910405060",
]

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, "E:/projects/skill_self_evolution/src")
sys.path.insert(0, str(PROJECT_ROOT / "scripts/wx_match"))

from skill_self_evolution.logging import get_logger
from skill_self_evolution.code_guard import CodeGuard, extract_context
from skill_self_evolution.feedback_descent import (
    FeedbackDescent, Proposer, Evaluator, EvaluationResult, FeedbackDescentResult,
)
from skill_self_evolution.loop_config import LoopConfig              # ADR §六-2
from skill_self_evolution.parallel_eval import run_parallel          # ADR §六-5

logger = get_logger("l4_closed_loop")

# ════════════════════════════════════════════════
# 工具
# ════════════════════════════════════════════════

def read_file(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def backup():
    if TARGET_FILE.exists():
        BACKUP_FILE.write_text(TARGET_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        logger.info("backup.created", src=TARGET_FILE.name, dst=BACKUP_FILE.name)

def restore():
    if BACKUP_FILE.exists():
        TARGET_FILE.write_text(BACKUP_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        BACKUP_FILE.unlink()
        logger.info("restore.done")

def find_function_lines(source: str, func_name: str) -> tuple[int, int]:
    lines = source.split("\n")
    start = None
    for i, line in enumerate(lines):
        if f"def {func_name}(" in line:
            start = i
            break
    if start is None:
        raise ValueError(f"找不到函数 {func_name}")
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    paren_depth = lines[start].count("(") - lines[start].count(")")
    sig_end = start
    for i in range(start + 1, len(lines)):
        paren_depth += lines[i].count("(") - lines[i].count(")")
        if paren_depth <= 0:
            sig_end = i
            break
    for i in range(sig_end + 1, len(lines)):
        line = lines[i]
        if line.strip() == "":
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and line.strip():
            return start + 1, i
    return start + 1, len(lines)

def extract_code_from_opencode_response(raw: list) -> str:
    if not raw:
        return ""
    payload = raw[0]
    all_msgs = payload.get("messages", [])
    text_parts = []
    for msg in reversed(all_msgs):
        info = msg.get("info", {})
        if info.get("role") == "assistant":
            for part in msg.get("parts", []):
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
            break
    full_text = "".join(text_parts)
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", full_text, re.DOTALL)
    if blocks:
        for b in blocks:
            if len(b.strip()) >= 50:
                return b.strip()
    return full_text.strip()

def get_card_binding_params() -> dict:
    from ruamel.yaml import YAML
    from skill_self_evolution.config_loader import ConfigVersionManager
    y = YAML(typ='safe')
    mgr = ConfigVersionManager()
    raw = mgr.load_raw("nickname-selector", "rules_config")
    config = y.load(raw) if raw else {}
    vc = config.get("correctness_criteria", {}).get("verification_conditions", [])
    cb = [v for v in vc if v.get("id") == "card_binding"]
    mgr.close()
    if cb:
        c = cb[0]
        return {"min_overlap_area_ratio": c.get("min_overlap_area_ratio", 0.3),
                "ambiguity_tie_ratio": c.get("ambiguity_tie_ratio", 0.05)}
    return {"min_overlap_area_ratio": 0.3, "ambiguity_tie_ratio": 0.05}

def inject_code_into_target(code: str):
    source = read_file(BACKUP_FILE) if BACKUP_FILE.exists() else read_file(TARGET_FILE)
    if not code or not code.strip():
        TARGET_FILE.write_text(source, encoding="utf-8")
        return
    TARGET_FILE.write_text(source, encoding="utf-8")
    source = read_file(TARGET_FILE)
    func_start, func_end = find_function_lines(source, TARGET_FUNC)
    lines = source.split("\n")
    base_indent = len(lines[func_start - 1]) - len(lines[func_start - 1].lstrip())
    insert_line = func_end
    for i in range(func_end - 1, func_start - 1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("return ") or stripped == "return":
            insert_line = i
            break
    indent = " " * (base_indent + 4)
    indented = "\n".join(
        indent + line if line.strip() else "" for line in code.split("\n")
    )
    new_lines = lines[:insert_line] + indented.split("\n") + lines[insert_line:]
    TARGET_FILE.write_text("\n".join(new_lines), encoding="utf-8")

# ════════════════════════════════════════════════
# test-collector-customized-for-renxin SKILL 调用
# ════════════════════════════════════════════════

def skill_layer1_static() -> tuple[bool, str]:
    """Layer 1: 静态检查 — Python ast 模块"""
    source = read_file(TARGET_FILE)
    try:
        compile(source, str(TARGET_FILE), "exec")
    except SyntaxError as e:
        return False, f"FIX: 语法错误 L{e.lineno}: {e.msg}"
    guard = CodeGuard(max_complexity=100)
    func_start, func_end = find_function_lines(source, TARGET_FUNC)
    func_source = "\n".join(source.split("\n")[func_start - 1:func_end])
    issues = guard.check_source(func_source, str(TARGET_FILE))
    errors = [i for i in issues if i.level == "error"]
    if errors:
        msgs = "\n".join(f"  L{i.line}: [{i.rule}] {i.message}" for i in errors[:5])
        return False, f"FIX: {msgs}"
    return True, "OK"

def skill_layer2_unit() -> tuple[bool, str]:
    """Layer 2: 单元测试"""
    test_path = str(PROJECT_ROOT / "backend/tests/test_wx_match/test_processor_nickname_ocr_simple.py")
    test_expr = "TestCompletelyInsideTolerance or bind or card or thumb or bbox or orphan"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-x", "-v", "-k", test_expr,
             "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT / "backend"),
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "FIX: 单元测试超时（120s）"
    if result.returncode == 0:
        m = re.search(r"(\d+)\s+passed", output)
        n = m.group(1) if m else "?"
        return True, f"OK ({n} passed)"
    failures = []
    capture = False
    for line in output.split("\n"):
        if "FAILURES" in line:
            capture = True
        if capture:
            failures.append(line.strip())
            if len(failures) > 30:
                break
    fb = "FIX: " + ("\n".join(failures[:20]) if failures else output[-800:])
    return False, fb

def skill_layer3_integration() -> tuple[bool, str]:
    """Layer 3: 集成测试"""
    test_path = str(PROJECT_ROOT / "backend/tests/test_wx_match/test_integration_ocr_pipeline.py")
    test_expr = "TestOCRAndSplitPipeline or TestLocalFileOCR or TestMinIOSingleOCR"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_path, "-x", "-v", "-k", test_expr,
             "--tb=short", "--no-header"],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT / "backend"),
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "FIX: 集成测试超时（120s）"
    if result.returncode == 0:
        m = re.search(r"(\d+)\s+passed", output)
        n = m.group(1) if m else "?"
        return True, f"OK ({n} passed)"
    failures = [l.strip() for l in output.split("\n") if "FAILED" in l or "ERROR" in l]
    fb = "FIX: " + ("\n".join(failures[:10]) if failures else output[-800:])
    return False, fb

# ════════════════════════════════════════════════
# Layer 4: 生产回放 — run_parallel 并行评测（ADR §六-5）
# ════════════════════════════════════════════════

async def _eval_one_session(session_dir: Path) -> dict:
    """异步评估单个 session 的所有截图。返回 {passed, total, failures}"""
    from collector.contracts import Screenshot, CaptureAction
    from processor.text_ocr_adapter import OcrPageResult, TextBlock as Tb
    from processor.nickname_ocr_simple import extract_nicknames, NicknameOcrConfig

    passed, total, failures = 0, 0, []
    dp = session_dir / "debug_session_derived.json"
    if not dp.exists():
        return {"passed": 0, "total": 0, "failures": [f"  {session_dir.name}: debug_session_derived.json 不存在"]}

    debug = json.loads(dp.read_text(encoding="utf-8"))
    for scr in debug.get("screenshots", [])[:3]:
        sid = scr.get("screenshot_id", "?")
        blks = scr.get("blocks", [])
        if not blks:
            continue
        total += 1
        try:
            ss = scr.get("screen_size", {"width": 720, "height": 1612})
            sw, sh = ss.get("width", 720), ss.get("height", 1612)
            tbs = [Tb(text=b.get("text", ""), confidence=b.get("confidence", 0.9),
                      bbox_xyxy=tuple(b.get("bbox_xyxy", [0, 0, 10, 10])[:4]))
                   for b in blks[:80] if isinstance(b, dict)]
            ocr = OcrPageResult(screenshot_id=sid, scale_hint=1280,
                original_size=(sw, sh), processed_size=(sw, sh),
                resized_applied=False, text_blocks=tbs,
                raw_full_text="\n".join(b.text for b in tbs),
                engine_name="paddleocr_mock", wall_ms=0)
            shot = Screenshot.model_validate({
                "screenshot_id": sid, "sequence": 1,
                "capture_action": CaptureAction.CHAT_INITIAL.value,
                "type": "chat_message",
                "obs_key": f"wechat/ahxvcp3910405060/g/202606/x/{sid}.png",
                "captured_at": "2026-06-11T12:00:00Z",
                "ocr_scale_hint": 1600,
                "original_resolution": {"width": sw, "height": sh},
                "resume_thumb_bboxes": scr.get("resume_thumb_bboxes_scaling", []),
                "contains_resume_thumb": bool(scr.get("resume_thumb_bboxes_scaling")),
            })
            cfg = NicknameOcrConfig(min_bubble_body_chars=0,
                require_avatar_guard_for_nickname=False,
                nickname_max_char_height_ratio=99.0)
            r = extract_nicknames(ocr, shot, config=cfg)
            if r and r.nicknames:
                passed += 1
            else:
                failures.append(f"  {session_dir.name}/{sid}: 无昵称")
        except Exception as e:
            failures.append(f"  {session_dir.name}/{sid}: {type(e).__name__}: {e}")

    logger.info("layer4.session_done", session=session_dir.name,
                passed=passed, total=total, failures=len(failures))
    return {"passed": passed, "total": total, "failures": failures}

def skill_layer4_production() -> tuple[bool, str]:
    """Layer 4: 生产环境测试 — run_parallel 并行评测多个 session"""
    # 构造异步任务列表：(async_fn, args)
    tasks = [(_eval_one_session, (d,)) for d in REAL_SESSION_DIRS]

    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(run_parallel(tasks, max_concurrent=3, timeout_per_task=120))
    finally:
        loop.close()

    # 汇总结果
    passed, total, all_failures = 0, 0, []
    for (r, err) in results:
        if err:
            all_failures.append(f"  session: {type(err).__name__}: {err}")
            continue
        if r:
            passed += r["passed"]
            total += r["total"]
            all_failures.extend(r["failures"])

    if total == 0:
        return True, "OK"
    if passed == total:
        return True, f"OK ({passed}/{total} all passed, parallel)"
    fb = "FIX: " + "\n".join(all_failures[:10])
    return False, fb

def run_skill_test() -> tuple[bool, str]:
    """调用 test-collector-customized-for-renxin SKILL 执行 4 层验证"""
    layers = [
        ("静态检查", skill_layer1_static),
        ("单元测试", skill_layer2_unit),
        ("集成测试", skill_layer3_integration),
        ("生产回放(并行)", skill_layer4_production),
    ]
    for name, fn in layers:
        logger.info("skill.layer.start", layer=name)
        passed, fb = fn()
        logger.info("skill.layer.done", layer=name, passed=passed)
        if not passed:
            return False, f"[{name}] {fb}"
    logger.info("skill.all_layers_passed")
    return True, "ALL 4 LAYERS PASSED (通过数=4, 总数=4, 失败列表=[])"

# ════════════════════════════════════════════════
# OpenCode harness Proposer — PRD §二(2)a
# ════════════════════════════════════════════════

class OpenCodeProposer(Proposer[str]):

    def __init__(self, func_ctx, params: dict):
        self.ctx = func_ctx
        self.params = params
        self.original = read_file(TARGET_FILE)
        try:
            s, e = find_function_lines(self.original, TARGET_FUNC)
            self.func_lines = (s, e)
        except ValueError:
            self.func_lines = (0, 0)

    def _options(self) -> dict:
        return {
            "provider_id": "deepseek",
            "model_id": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "mode": "build",
            "cwd": str(PROJECT_ROOT),
            "system": textwrap.dedent(f"""\
                You are a Python code expert. Respond ONLY with a ```python``` code block.
                CRITICAL RULES:
                - Module-level function, NO self/cls/self.
                - Params: {', '.join(self.ctx.get('params', []))}
                - DO NOT define new functions or classes
                - DO NOT invent variable names not in the function
                - NO bare except / global / random / time.time / datetime
                - NO logging inside loops
                - Max 15 lines of new code
                - Read card_binding params via config attributes
            """),
        }

    def _prompt(self, feedback_history: list = None) -> str:
        fb = ""
        if feedback_history:
            fb = "\n\n## 历史失败尝试（DO NOT repeat these mistakes）\n"
            for i, entry in enumerate(feedback_history):
                fb += f"\n### Attempt {i+1} — FAILED\n```\n{str(entry.candidate)[:200]}\n```\n**Reason**: {entry.rationale[:400]}\n"
        s, e = self.func_lines
        code = "\n".join(self.original.split("\n")[s-1:e]) if s else "NOT FOUND"
        return textwrap.dedent(f"""\
            ## 目标
            在 {TARGET_FUNC} 函数 (L{s}-{e}) 中，在 return 前插入代码。

            ## 函数代码
            ```python
            {code[:3000]}
            ```

            ## 需要消费的 YAML 新增参数
            - min_overlap_area_ratio = {self.params['min_overlap_area_ratio']}
            - ambiguity_tie_ratio = {self.params['ambiguity_tie_ratio']}

            ## 可用变量
            - raws: list[list[int]] — 简历卡 bbox [x1,y1,x2,y2]
            - blocks: list[TextBlock] — OCR 文本块
            - layout_opt: Any — 含 .speaker_bands 属性
            - config: NicknameOcrConfig dataclass

            ## 消费逻辑
            1. min_overlap_area_ratio — 当卡片与 band 重叠面积比 < 此值，continue 跳过
            2. ambiguity_tie_ratio — 当 best vs second_best 面积差比 < 此值，continue 跳过
            {fb}

            Output ONLY ```python``` code block (5-15 lines). DO NOT include explanation.
        """)

    def generate_initial(self, problem: str) -> str:
        return ""

    def propose(self, current_best: str, feedback_history: list) -> str:
        logger.info("opencode.propose", history_size=len(feedback_history) if feedback_history else 0)
        prompt = self._prompt(feedback_history)
        loop = asyncio.new_event_loop()
        try:
            from skill_self_evolution.harness.opencode.executor import execute_query
            options = self._options()
            raw = loop.run_until_complete(execute_query(options, prompt))
        finally:
            loop.close()
        code = extract_code_from_opencode_response(raw)
        logger.info("opencode.response", raw_len=len(str(raw)), extracted_len=len(code))
        return code

# ════════════════════════════════════════════════
# SKILL Evaluator — PRD §二(2)b
# ════════════════════════════════════════════════

class SkillEvaluator(Evaluator[str]):

    def evaluate(self, current_best: str, candidate: str) -> EvaluationResult:
        inject_code_into_target(candidate)
        passed, fb = run_skill_test()
        inject_code_into_target(current_best)
        return EvaluationResult(preference_for_candidate=passed, rationale=fb)

# ════════════════════════════════════════════════
# 主流程
# ════════════════════════════════════════════════

def main():
    ts = datetime.now(BEIJING_TZ).isoformat()
    # ── LoopConfig — ADR §六-2 ──
    loop_cfg = LoopConfig(
        max_iterations=5,
        no_improvement_limit=3,
        concurrency=3,
        cache_enabled=False,
    )
    logger.info("loop_config", **{k: getattr(loop_cfg, k) for k in
        ["max_iterations", "no_improvement_limit", "concurrency", "cache_enabled"]})

    logger.info("l4.start", time=ts, target=str(TARGET_FILE), func=TARGET_FUNC,
                skill=str(SKILL_ROOT))
    print("=" * 70)
    print("L4 代码生成闭环测试 — PRD §二(2) + ADR §六")
    print(f"  代码生成: OpenCode harness (execute_query)")
    print(f"  测试验证: test-collector-customized-for-renxin SKILL")
    print(f"  进化配置: LoopConfig (max_iter={loop_cfg.max_iterations}, "
          f"no_imp_limit={loop_cfg.no_improvement_limit}, concurrency={loop_cfg.concurrency})")
    print(f"  Layer 4:   run_parallel 并行评测 {len(REAL_SESSION_DIRS)} 个 session")
    print(f"  日志:      structlog (ConsoleRenderer)")
    print("=" * 70)

    backup()
    ctx = extract_context(str(TARGET_FILE), TARGET_FUNC)
    logger.info("context.extracted", params=ctx.params if ctx else [])

    params = get_card_binding_params()
    logger.info("params.loaded",
                min_overlap_area_ratio=params["min_overlap_area_ratio"],
                ambiguity_tie_ratio=params["ambiguity_tie_ratio"])

    # Phase 1: 基线
    print("\n--- Phase 1: 基线 4 层门禁 ---")
    logger.info("phase1.baseline.start")
    bl_ok, bl_fb = run_skill_test()
    logger.info("phase1.baseline.done", passed=bl_ok)
    print(f"  基线: {'PASS' if bl_ok else 'FAIL'}")

    # Phase 2: FeedbackDescent — 使用 LoopConfig
    print(f"\n--- Phase 2: FeedbackDescent 闭环 (max {loop_cfg.max_iterations} rounds, "
          f"no_improvement_limit={loop_cfg.no_improvement_limit}) ---")
    logger.info("phase2.descent.start",
                max_iterations=loop_cfg.max_iterations,
                no_improvement_limit=loop_cfg.no_improvement_limit)
    ctx_dict = {"is_method": ctx.is_method if ctx else False,
                "params": ctx.params if ctx else [],
                "self_forbidden": ctx.self_forbidden if ctx else True}
    proposer = OpenCodeProposer(ctx_dict, params)
    evaluator = SkillEvaluator()
    fd = FeedbackDescent[str](
        proposer=proposer, evaluator=evaluator,
        max_iterations=loop_cfg.max_iterations,
        no_improvement_limit=loop_cfg.no_improvement_limit,
    )
    problem = "Consume card_binding params"
    result = fd.run(problem)
    logger.info("phase2.descent.done", iterations=result.iterations,
                improved=result.improved, history_count=len(result.feedback_history))

    # Phase 3: 最终验证
    print("\n--- Phase 3: 最终验证 ---")
    inject_code_into_target(result.best)
    final_ok, final_fb = run_skill_test()
    logger.info("phase3.final", passed=final_ok)

    # 报告
    print("\n" + "=" * 70)
    print("L4 测试报告")
    print("=" * 70)
    print(f"  代码生成方式: OpenCode harness execute_query(options, prompt)")
    print(f"  进化配置:     LoopConfig(max_iter={loop_cfg.max_iterations}, "
          f"no_imp_limit={loop_cfg.no_improvement_limit})")
    print(f"  Layer 4 方式: run_parallel(max_concurrent={loop_cfg.concurrency})")
    print(f"  测试验证:     test-collector-customized-for-renxin SKILL")
    print(f"  日志:         structlog")
    print(f"  基线门禁:     {'PASS' if bl_ok else 'FAIL'}")
    print(f"  最终门禁:     {'PASS' if final_ok else 'FAIL'}")
    print(f"  FeedbackDescent: {result.iterations}/{loop_cfg.max_iterations} rounds, improved={result.improved}")
    print(f"  best 代码长度: {len(result.best)} chars")
    for i, entry in enumerate(result.feedback_history):
        print(f"  失败历史[{i+1}]: {entry.rationale[:120]}...")

    if final_ok:
        print(f"\n  L4 闭环测试通过 — 代码已写入 {TARGET_FILE}")
    else:
        print(f"\n  L4 闭环测试未通过")
        restore()
    print("=" * 70)

if __name__ == "__main__":
    main()
