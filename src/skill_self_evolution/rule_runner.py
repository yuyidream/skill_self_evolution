"""
薄执行层 — 遍历 rules_config.yaml 中的声明式规则，执行匹配/过滤/修正。

供各 Skill 的 run.py::execute() 调用，将规则内容与执行逻辑分离。
"""

import re
from typing import Any

from pydantic import ValidationError

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)

from skill_self_evolution.models import RejectionRuleItem


def run_rejection_rules(text: str, rules: list[dict[str, Any]]) -> str | None:
    """对单条文本顺序执行拒绝规则链。

    每条规则先过 Pydantic 校验，格式不对时记录警告并跳过该规则。

    规则字段：
        type:   "regex" | "prefix" | "length"
        action: "drop" | "remove_prefix"（默认 drop）

        type=regex  : pattern（必填）
        type=prefix : keywords（必填，list[str]）
        type=length : min / max（可选，默认 0/999）

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

        # ── Pydantic 校验 ──
        try:
            validated = RejectionRuleItem.model_validate(rule)
        except ValidationError as e:
            logger.warning("rule_runner 跳过非法规则: %s → %s", rule.get("description", rule), e)
            continue

        t = validated.type
        action = validated.action

        if t == "regex":
            pat = validated.pattern
            if not pat or not re.search(pat, text):
                continue
            if action == "drop":
                return None
            if action == "remove_prefix":
                text = re.sub(pat, "", text)

        elif t == "prefix":
            for kw in validated.keywords:
                if text.startswith(kw):
                    if action == "drop":
                        return None

        elif t == "length":
            mn = validated.min
            mx = validated.max
            if not (mn <= len(text) <= mx):
                if action == "drop":
                    return None

    return text
