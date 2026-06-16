"""
薄执行层 — 遍历 rules_config.yaml 中的声明式规则，执行匹配/过滤/修正。

供各 Skill 的 run.py::execute() 调用，将规则内容与执行逻辑分离。

支持三种规则层：
  - 文本层：run_rejection_rules(text, rules) → str | None
  - 几何层：run_block_rules(block, geometry_rules, params) → OcrBlock | None
"""

import re
from typing import Any

from pydantic import ValidationError

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)

from skill_self_evolution.models import GeometryRuleParams, OcrBlock, RejectionRuleItem


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


def run_block_rules(
    block: OcrBlock,
    geometry_rules: list[dict[str, Any]],
    params: GeometryRuleParams | None = None,
) -> OcrBlock | None:
    """对单个 OCR block 执行几何规则链。

    每条规则先过 Pydantic 校验，格式不对时记录警告并跳过该规则。

    几何规则字段（type=geometry）：
        constraint: "horizontal_position" | "avatar_column" | "bbox_width" | "char_height_ratio"
        action:     "drop"（当前仅支持 drop）
        operator:   "lt" | "lte" | "gt" | "gte"
        value:      float（阈值）

    约束说明：
        horizontal_position: 比较 block 中心 x 与某参考值（如 midline_x），
                             当前实现用 params.midline_y 作为横向中线
        avatar_column:       判断 block 水平位置是否在头像列内
        bbox_width:          判断 block 宽度
        char_height_ratio:   判断 block 高度与字符高度中位数的比值

    Returns:
        通过所有规则返回 OcrBlock，被 drop 返回 None。

    Example:
        >>> block = OcrBlock(text="昵称A", bbox_xyxy=[50, 100, 200, 130])
        >>> params = GeometryRuleParams(screen_width=1080, midline_y=540)
        >>> run_block_rules(block, [
        ...     {"type": "geometry", "constraint": "avatar_column",
        ...      "action": "drop", "operator": "lt", "value": 120}
        ... ], params)
    """
    if params is None:
        params = GeometryRuleParams()

    for rule in geometry_rules:
        if not isinstance(rule, dict):
            continue

        # ── Pydantic 校验 ──
        try:
            validated = RejectionRuleItem.model_validate(rule)
        except ValidationError as e:
            logger.warning("run_block_rules 跳过非法规则: %s → %s", rule.get("description", rule), e)
            continue

        if validated.type != "geometry":
            continue

        constraint = rule.get("constraint", "")
        operator = rule.get("operator", "lt")
        value = float(rule.get("value", 0))
        action = validated.action

        matched = False

        if constraint == "horizontal_position":
            # 判断 block 中心 x 是否在屏幕左半侧
            # 当前用 midline_y 的近似实现：比较 center_x 与 0.5*screen_width
            midline_x = params.screen_width * 0.5
            if operator == "lt":
                matched = block.center_x < midline_x
            elif operator == "lte":
                matched = block.center_x <= midline_x
            elif operator == "gt":
                matched = block.center_x > midline_x
            elif operator == "gte":
                matched = block.center_x >= midline_x
        elif constraint == "avatar_column":
            # 判断 block 是否在头像列内（左边界到右边界之间，反向判断）
            col_left = params.avatar_column_left
            col_right = params.avatar_column_right
            if col_left <= 0 and col_right <= 0:
                # 无有效头像列信息，跳过
                continue
            if operator == "lt":
                matched = block.right < value
            elif operator == "lte":
                matched = block.right <= value
            elif operator == "gt":
                matched = block.left > value
            elif operator == "gte":
                matched = block.left >= value
            elif operator == "between":
                matched = col_left <= block.center_x <= col_right
                if not matched:
                    # block 不在头像列内
                    pass
        elif constraint == "bbox_width":
            bw = block.width
            if operator == "lt":
                matched = bw < value
            elif operator == "lte":
                matched = bw <= value
            elif operator == "gt":
                matched = bw > value
            elif operator == "gte":
                matched = bw >= value
        elif constraint == "char_height_ratio":
            if params.char_height_median <= 0:
                continue
            ratio = block.height / params.char_height_median
            if operator == "lt":
                matched = ratio < value
            elif operator == "lte":
                matched = ratio <= value
            elif operator == "gt":
                matched = ratio > value
            elif operator == "gte":
                matched = ratio >= value

        if matched and action == "drop":
            return None

    return block
