"""AI 代码生成质量门禁 — 可扩展的 AST 检查器 + 上下文提取

提供两层能力：
1. CodeGuard — 注册 Checker → 检查代码 → 返回 CodeIssue 列表
2. FunctionContext — 自动提取函数上下文（is_method / 可用变量 / 禁止变量）

使用方式：
    from skill_self_evolution.code_guard import CodeGuard, extract_context

    guard = CodeGuard()
    passed, issues = guard.gate("path/to/file.py")

    ctx = extract_context("path/to/file.py", "function_name")
    print(ctx.is_method)    # False
    print(ctx.local_vars)   # ['cx', 'cy', 'raws', ...]
"""

import ast
from pathlib import Path
from typing import Optional

from skill_self_evolution.models import CodeIssueModel, FunctionContextModel

# Backward compatibility aliases
CodeIssue = CodeIssueModel
FunctionContext = FunctionContextModel


class BaseChecker(ast.NodeVisitor):
    """AST 检查器基类。子类只需实现 visit_Xxx 方法"""

    def run(self, source: str, filepath: str = "") -> list[CodeIssue]:
        self._issues: list[CodeIssue] = []
        self._filepath = filepath
        try:
            tree = ast.parse(source)
            self.visit(tree)
        except SyntaxError as e:
            self._issues.append(CodeIssue(
                rule="syntax_error", level="error",
                message=f"Syntax error: {e}", file=filepath,
                line=e.lineno or 0, col=e.offset or 0))
        return self._issues

    def _add(self, rule: str, level: str, msg: str, node: ast.AST):
        self._issues.append(CodeIssue(
            rule=rule, level=level, message=msg,
            file=self._filepath,
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0)))


# ═══════════════════════════════════════════════════
# 6 条内置 Checker
# ═══════════════════════════════════════════════════

class NoBareExcept(BaseChecker):
    """禁止裸 except:（必须指定异常类型）"""

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is None:
            self._add("no_bare_except", "error",
                      "bare 'except:' without exception type", node)
        self.generic_visit(node)


class CyclomaticComplexity(BaseChecker):
    """圈复杂度 ≤ DEFAULT_MAX"""

    DEFAULT_MAX = 10
    BRANCH_NODES = (ast.If, ast.While, ast.For, ast.AsyncFor,
                    ast.ExceptHandler, ast.With, ast.AsyncWith,
                    ast.Try, ast.And, ast.Or, ast.IfExp)

    def __init__(self, max_complexity: int = DEFAULT_MAX):
        super().__init__()
        self.max = max_complexity

    def run(self, source: str, filepath: str = "") -> list[CodeIssue]:
        self._issues = []
        self._filepath = filepath
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            self._issues.append(CodeIssue(
                rule="syntax_error", level="error",
                message=f"Syntax error: {e}", file=filepath,
                line=e.lineno or 0, col=e.offset or 0))
            return self._issues
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                complexity = 1
                for child in ast.walk(node):
                    if isinstance(child, self.BRANCH_NODES):
                        complexity += 1
                if complexity > self.max:
                    self._add("cyclomatic_complexity", "error",
                              f"function '{node.name}' complexity {complexity} > {self.max}", node)
        return self._issues


class NoGlobalModification(BaseChecker):
    """禁止模块级函数使用 global 语句"""

    def visit_Global(self, node: ast.Global):
        self._add("no_global_modification", "error",
                  "use of 'global' statement (forbidden in module-level functions)", node)
        self.generic_visit(node)


class NoLoggingInTightLoop(BaseChecker):
    """禁止 for/while 循环体内调用 logging.info/debug/warning"""

    LOG_METHODS = {"info", "debug", "warning", "warn", "log"}

    def visit_For(self, node: ast.For):
        self._check_loop_body(node.body, "for")
        self.generic_visit(node)

    def visit_While(self, node: ast.While):
        self._check_loop_body(node.body, "while")
        self.generic_visit(node)

    def _check_loop_body(self, body: list, loop_type: str):
        for stmt in body:
            for child in ast.walk(stmt):
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                    if child.func.attr in self.LOG_METHODS:
                        self._add("no_logging_in_loop", "warning",
                                  f"logging.{child.func.attr}() inside {loop_type} loop", child)


class NoExceptionSwallowing(BaseChecker):
    """禁止 try/except 中无声吞没异常（空 handler / pass）"""

    def visit_Try(self, node: ast.Try):
        for handler in node.handlers:
            if not handler.body:
                self._add("no_exception_swallowing", "error",
                          "empty except handler (exception swallowed)", handler)
            elif len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                self._add("no_exception_swallowing", "error",
                          "exception swallowed with 'pass'", handler.body[0])
        self.generic_visit(node)


class NoNonDeterministicImports(BaseChecker):
    """禁止引入非确定性依赖：import random / from time import time / from datetime import datetime"""

    FORBIDDEN_MODULES = {"random"}
    FORBIDDEN_FROM = {
        "time": {"time"},
        "datetime": {"datetime", "now"},
    }

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            if alias.name.split(".")[0] in self.FORBIDDEN_MODULES:
                self._add("no_nondeterministic", "error",
                          f"import '{alias.name}' (non-deterministic)", node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module is None:
            return
        base = node.module.split(".")[0]
        if base in self.FORBIDDEN_FROM:
            for alias in node.names:
                if alias.name in self.FORBIDDEN_FROM[base]:
                    self._add("no_nondeterministic", "error",
                              f"from {node.module} import {alias.name} (non-deterministic)", node)


# ═══════════════════════════════════════════════════
# AST 上下文自动提取
# ═══════════════════════════════════════════════════

def extract_context(filepath: str | Path, func_name: str) -> Optional[FunctionContext]:
    """用 AST 提取目标函数的上下文信息。

    返回 FunctionContextModel，包含：
    - is_method: 是否是类方法（有 self/cls）
    - params: 参数名列表
    - local_vars: 函数体内赋值的变量名（在目标区域之前）

    用于 Evolver 自动注入 AI prompt，无需人工维护变量清单。
    """
    path = Path(filepath)
    source = path.read_text("utf-8")
    return _extract_context_from_source(source, str(path), func_name)


def _extract_context_from_source(
    source: str, filepath: str, func_name: str
) -> Optional[FunctionContext]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            is_method = bool(node.args.args) and node.args.args[0].arg in ("self", "cls")
            params = [a.arg for a in node.args.args]

            local_vars: list[str] = []
            for child in ast.walk(node):
                if (isinstance(child, ast.AnnAssign)
                        and isinstance(child.target, ast.Name)):
                    local_vars.append(child.target.id)
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name):
                            local_vars.append(target.id)
                elif isinstance(child, ast.NamedExpr):
                    if isinstance(child.target, ast.Name):
                        local_vars.append(child.target.id)

            return FunctionContextModel(
                name=func_name,
                file=filepath,
                is_method=is_method,
                params=params,
                local_vars=list(dict.fromkeys(local_vars)),
                lineno=node.lineno,
                end_lineno=node.end_lineno or 0,
            )
    return None


# ═══════════════════════════════════════════════════
# CodeGuard 注册中心
# ═══════════════════════════════════════════════════

class CodeGuard:
    """代码质量门禁 — 注册 + 按序执行所有 Checker"""

    _BUILTIN: dict[str, type[BaseChecker]] = {
        "no_bare_except": NoBareExcept,
        "cyclomatic_complexity": CyclomaticComplexity,
        "no_global_modification": NoGlobalModification,
        "no_logging_in_loop": NoLoggingInTightLoop,
        "no_exception_swallowing": NoExceptionSwallowing,
        "no_nondeterministic": NoNonDeterministicImports,
    }

    def __init__(self, rules: list[str] | None = None, max_complexity: int = 10):
        """
        Args:
            rules: 启用的规则名列表。None = 启用全部内置规则
            max_complexity: 圈复杂度上限
        """
        self.rules = rules or list(self._BUILTIN)
        self.max_complexity = max_complexity

    def check_file(self, filepath: str | Path) -> list[CodeIssue]:
        """对单个文件执行所有启用的检查"""
        path = Path(filepath)
        return self.check_source(path.read_text("utf-8"), str(path))

    def check_source(self, source: str, filepath: str = "<string>") -> list[CodeIssue]:
        """对源码字符串执行所有启用的检查"""
        all_issues: list[CodeIssue] = []
        for name in self.rules:
            cls = self._BUILTIN.get(name)
            if cls is None:
                continue
            kwargs = {}
            if issubclass(cls, CyclomaticComplexity):
                kwargs["max_complexity"] = self.max_complexity
            checker = cls(**kwargs)
            all_issues.extend(checker.run(source, filepath))
        return all_issues

    def check_files(self, filepaths: list[str]) -> dict[str, list[CodeIssue]]:
        """对多个文件执行检查"""
        results: dict[str, list[CodeIssue]] = {}
        for fp in filepaths:
            issues = self.check_file(fp)
            if issues:
                results[fp] = issues
        return results

    def gate(self, filepath: str | Path) -> tuple[bool, list[CodeIssue]]:
        """门禁：返回 (通过?, 问题列表)。有任意 error 级问题则不过"""
        issues = self.check_file(filepath)
        errors = [i for i in issues if i.level == "error"]
        return len(errors) == 0, issues

    def register(self, name: str, checker_cls: type[BaseChecker]):
        """注册自定义 Checker"""
        self._BUILTIN[name] = checker_cls
        if name not in self.rules:
            self.rules.append(name)

    @classmethod
    def list_rules(cls) -> dict[str, str]:
        """列出所有内置规则及其说明"""
        return {
            "no_bare_except": "禁止裸 except:（必须指定异常类型）",
            "cyclomatic_complexity": f"圈复杂度 ≤ {CyclomaticComplexity.DEFAULT_MAX}",
            "no_global_modification": "禁止模块级函数使用 global",
            "no_logging_in_loop": "禁止 for/while 循环内调用 logging",
            "no_exception_swallowing": "禁止 try/except 吞没异常（pass/空 handler）",
            "no_nondeterministic": "禁止引入非确定性依赖（random/time/datetime）",
        }
