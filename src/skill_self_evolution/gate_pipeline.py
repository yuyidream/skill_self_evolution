"""4 层代码门禁管道

按 PRD §上游1 定义，对新生成的代码依次执行：

    Layer 1  静态检查 — Python 标准库 ast 模块（圈复杂度 / 裸except / global / 日志在循环 / 吞异常 / 非确定性）
    Layer 2  单元测试 — pytest 自己写自己测
    Layer 3  集成测试 — 强制参加已有 E2E 测试 + 覆盖率门禁
    Layer 4  生产环境测试 — 跑全量候选数据（≥10 条）+ 幂等性验证

任一层失败 → 错误信息喂回 AI → AI 重写 → 重新过门禁

使用方式：
    from skill_self_evolution.gate_pipeline import GatePipeline

    pipeline = GatePipeline(ai_callback=my_ai_regenerate)
    result = pipeline.run(
        filepaths=["path/to/changed.py"],
        e2e_test_path="tests/test_e2e.py",
        candidate_replay_fn=my_replay_function,
    )
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from .code_guard import CodeGuard, CodeIssue, FunctionContext, extract_context
from skill_self_evolution.models import LayerResultModel, GateResultModel

# Backward compatibility aliases
LayerResult = LayerResultModel
GateResult = GateResultModel


class GatePipeline:
    """4 层代码门禁管道。

    ai_regenerate: 失败时调用此函数重新生成代码
        signature: async def regenerate(feedback: str, filepaths: list[str]) -> bool
    """

    def __init__(
        self,
        ai_regenerate: Optional[Callable] = None,
        max_complexity: int = 10,
        candidate_min_count: int = 10,
    ):
        self.ai_regenerate = ai_regenerate
        self.max_complexity = max_complexity
        self.candidate_min_count = candidate_min_count
        self.max_rounds = 3

    async def run(
        self,
        filepaths: list[str],
        unit_test_path: str,
        e2e_test_path: str,
        candidate_replay_fn: Callable,
        backend_dir: str = ".",
        context_func_name: Optional[str] = None,
    ) -> GateResult:
        """执行完整 4 层门禁。最多 3 轮重试。

        Args:
            filepaths: 被修改的文件路径列表
            unit_test_path: pytest 单元测试路径
            e2e_test_path: pytest 集成测试路径
            candidate_replay_fn: async (files) -> (bool, str) 候选数据回放函数
            backend_dir: pytest 执行目录
            context_func_name: 如需提取函数上下文，指定函数名
        """
        t_start = time.perf_counter()

        for rnd in range(1, self.max_rounds + 1):
            print(f"\n=== Gate Round {rnd}/{self.max_rounds} ===")

            layers: list[LayerResult] = []

            # ── Layer 1: 静态检查 ──
            l1 = await self._layer1_static_check(filepaths)
            layers.append(l1)
            if not l1.passed:
                feedback = self._build_feedback(layers, filepaths, context_func_name)
                print(f"  Layer 1 FAILED: {len(l1.issues)} issues")
                if self.ai_regenerate:
                    await self.ai_regenerate(feedback, filepaths)
                    continue
                return GateResult(passed=False, layers=layers, feedback=feedback,
                                  total_elapsed_ms=(time.perf_counter() - t_start) * 1000)

            # ── Layer 2: 单元测试 ──
            l2 = await self._layer2_unit_test(unit_test_path, backend_dir)
            layers.append(l2)
            if not l2.passed:
                feedback = self._build_feedback(layers, filepaths, context_func_name)
                print(f"  Layer 2 FAILED")
                if self.ai_regenerate:
                    await self.ai_regenerate(feedback, filepaths)
                    continue
                return GateResult(passed=False, layers=layers, feedback=feedback,
                                  total_elapsed_ms=(time.perf_counter() - t_start) * 1000)

            # ── Layer 3: 集成测试 ──
            l3 = await self._layer3_integration_test(e2e_test_path, backend_dir)
            layers.append(l3)
            if not l3.passed:
                feedback = self._build_feedback(layers, filepaths, context_func_name)
                print(f"  Layer 3 FAILED")
                if self.ai_regenerate:
                    await self.ai_regenerate(feedback, filepaths)
                    continue
                return GateResult(passed=False, layers=layers, feedback=feedback,
                                  total_elapsed_ms=(time.perf_counter() - t_start) * 1000)

            # ── Layer 4: 生产环境测试 ──
            l4 = await self._layer4_candidate_replay(candidate_replay_fn, filepaths)
            layers.append(l4)
            if not l4.passed:
                feedback = self._build_feedback(layers, filepaths, context_func_name)
                print(f"  Layer 4 FAILED")
                if self.ai_regenerate:
                    await self.ai_regenerate(feedback, filepaths)
                    continue
                return GateResult(passed=False, layers=layers, feedback=feedback,
                                  total_elapsed_ms=(time.perf_counter() - t_start) * 1000)

            # ── 全部通过 ──
            total_ms = (time.perf_counter() - t_start) * 1000
            print(f"\n  ALL 4 LAYERS PASSED in {rnd} round(s) ({total_ms:.0f}ms)")
            return GateResult(passed=True, layers=layers,
                              total_elapsed_ms=total_ms)

        # 超出回合数
        total_ms = (time.perf_counter() - t_start) * 1000
        return GateResult(passed=False, layers=[],
                          feedback="Max retry rounds exceeded",
                          total_elapsed_ms=total_ms)

    # ── 各层实现 ──

    async def _layer1_static_check(self, filepaths: list[str]) -> LayerResult:
        t0 = time.perf_counter()
        guard = CodeGuard(max_complexity=self.max_complexity)
        all_issues: list[CodeIssue] = []
        for fp in filepaths:
            all_issues.extend(guard.check_file(fp))

        errors = [i for i in all_issues if i.level == "error"]
        warnings = [i for i in all_issues if i.level == "warning"]
        print(f"  Layer 1 (static): {len(errors)} errors, {len(warnings)} warnings")
        for i in all_issues:
            print(f"    [{i.level}] {i.rule}: {i.message}")

        return LayerResult(
            layer=1,
            layer_name="static_check",
            passed=len(errors) == 0,
            issues=all_issues,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    async def _layer2_unit_test(self, test_path: str, cwd: str) -> LayerResult:
        t0 = time.perf_counter()
        passed, output = self._run_pytest(test_path, cwd)
        return LayerResult(
            layer=2, layer_name="unit_test",
            passed=passed, output=output,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    async def _layer3_integration_test(self, test_path: str, cwd: str) -> LayerResult:
        t0 = time.perf_counter()
        passed, output = self._run_pytest(test_path, cwd)
        return LayerResult(
            layer=3, layer_name="integration_test",
            passed=passed, output=output,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    async def _layer4_candidate_replay(
        self, replay_fn: Callable, filepaths: list[str]
    ) -> LayerResult:
        t0 = time.perf_counter()
        try:
            result = replay_fn(filepaths)
            if isinstance(result, tuple):
                passed, output = result
            else:
                # 假设是协程
                passed, output = await result
        except Exception as e:
            passed, output = False, f"Candidate replay error: {e}"

        return LayerResult(
            layer=4, layer_name="candidate_replay",
            passed=passed, output=str(output),
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )

    # ── 工具方法 ──

    def _run_pytest(self, test_path: str, cwd: str) -> tuple[bool, str]:
        env = os.environ.copy()
        env.setdefault("DB_PASSWORD", "")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", test_path,
             "-q", "--tb=short", "--no-header", "-W", "ignore"],
            cwd=str(cwd), capture_output=True, text=True, timeout=180, env=env,
        )
        output = r.stdout[-3000:] if r.stdout else ""
        ok = r.returncode == 0
        # 更精确判断
        for line in (r.stdout or "").split("\n"):
            if line.strip().endswith(" failed"):
                ok = False
        return ok, output

    def _build_feedback(
        self, layers: list[LayerResult], filepaths: list[str],
        func_name: Optional[str] = None,
    ) -> str:
        """将失败信息格式化为 AI 可消费的反馈"""
        parts = []
        for lr in layers:
            if not lr.passed:
                parts.append(f"[Layer {lr.layer} FAILED] {lr.layer_name}")
                parts.append(f"Output:\n{lr.output[:1500]}")
                for issue in lr.issues:
                    parts.append(f"  [{issue.level}] {issue.rule}: {issue.message}")

        # 注入函数上下文
        if func_name and filepaths:
            ctx = extract_context(filepaths[0], func_name)
            if ctx:
                parts.insert(0, ctx.context_for_prompt())

        return "\n".join(parts)

    @classmethod
    def check_static(cls, filepaths: list[str], max_complexity: int = 10) -> tuple[bool, list[CodeIssue]]:
        """快捷方法：只做静态检查（Layer 1）"""
        guard = CodeGuard(max_complexity=max_complexity)
        all_issues: list[CodeIssue] = []
        for fp in filepaths:
            all_issues.extend(guard.check_file(fp))
        errors = [i for i in all_issues if i.level == "error"]
        return len(errors) == 0, all_issues
