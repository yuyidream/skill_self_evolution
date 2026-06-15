"""
薄执行层 — 遍历 rules_config.yaml 中的声明式规则，执行匹配/过滤/修正。

供各 Skill 的 run.py::execute() 调用，将规则内容与执行逻辑分离。
"""

import re
from typing import Any


def run_rejection_rules(text: str, rules: list[dict[str, Any]]) -> str | None:
    """对单条文本顺序执行拒绝规则链。

    每条规则是一个 dict，至少包含 type 和 action 两个字段：

    type 支持：
      - "regex"    : 正则匹配，需 pattern 字段
      - "prefix"   : 前缀匹配，需 keywords 列表
      - "length"   : 长度范围，需 min / max 字段

    action 支持：
      - "drop"          : 命中后直接丢弃，返回 None
      - "remove_prefix" : 命中后去除匹配部分（仅 regex 类型）

    返回修正后文本，若被 drop 则返回 None。

    Example:
        >>> run_rejection_rules("姓名：张三", [
        ...     {"type": "regex", "pattern": "^姓名[：:]", "action": "remove_prefix"},
        ... ])
        '张三'

        >>> run_rejection_rules("@系统消息", [
        ...     {"type": "prefix", "keywords": ["@", "撤回"], "action": "drop"},
        ... ])
        None
    """
    for rule in rules:
        if not isinstance(rule, dict):
            continue

        t = rule.get("type", "")
        action = rule.get("action", "drop")

        if t == "regex":
            pat = rule.get("pattern", "")
            if not pat or not re.search(pat, text):
                continue
            if action == "drop":
                return None
            if action == "remove_prefix":
                text = re.sub(pat, "", text)

        elif t == "prefix":
            for kw in rule.get("keywords", []):
                if text.startswith(kw):
                    if action == "drop":
                        return None

        elif t == "length":
            mn = rule.get("min", 0)
            mx = rule.get("max", 999)
            if not (mn <= len(text) <= mx):
                if action == "drop":
                    return None

    return text
