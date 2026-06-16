"""反馈历史 — 从 EvoSkill helpers.py 提取。

原始：https://github.com/sentient-agi/EvoSkill
"""

from pathlib import Path

from skill_self_evolution.logging import get_logger

logger = get_logger(__name__)


def append_feedback(
    path: Path,
    iteration: str,
    proposal: str,
    justification: str,
    outcome: str | None = None,
    score: float | None = None,
    parent_score: float | None = None,
    active_skills: list[str] | None = None,
    failure_category: str | None = None,
    root_cause: str | None = None,
) -> None:
    """追加反馈条目到历史文件。

    Args:
        path: 反馈历史文件路径
        iteration: 迭代标识（如 "iter-1"）
        proposal: 提出的改进建议
        justification: 为什么提出这个建议
        outcome: "improved" | "no_improvement" | "discarded"
        score: 应用后评分
        parent_score: 父代评分
        active_skills: 活跃的技能列表
        failure_category: 失败类别（如 "methodology"）
        root_cause: 根因简要描述
    """
    outcome_section = ""
    if outcome is not None:
        delta = (score - parent_score) if (score is not None and parent_score is not None) else None
        delta_str = f" ({delta:+.4f})" if delta is not None else ""
        score_str = f" (score: {score:.4f}{delta_str})" if score is not None else ""
        outcome_section = f"\n**Outcome**: {outcome.upper()}{score_str}"

    diagnostic_section = ""
    if active_skills:
        diagnostic_section += f"\n**Active Skills**: {', '.join(active_skills)}"
    if failure_category:
        diagnostic_section += f"\n**Failure Category**: {failure_category}"
    if root_cause:
        diagnostic_section += f"\n**Root Cause**: {root_cause}"

    entry = f"""
## {iteration}
**Proposal**: {proposal}
**Justification**: {justification}{outcome_section}{diagnostic_section}

"""
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry)

    logger.info("feedback.append", iteration=iteration, outcome=outcome,
                 score=score, path=str(path))


def read_feedback_history(path: Path) -> str:
    """读取反馈历史。

    Args:
        path: 反馈历史文件路径

    Returns:
        反馈内容，若文件不存在则返回默认消息
    """
    if path.exists():
        content = path.read_text(encoding="utf-8")
        logger.info("feedback.read", path=str(path), size=len(content))
        return content

    logger.info("feedback.read_empty", path=str(path))
    return "No previous attempts."
