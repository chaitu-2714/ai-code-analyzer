"""Documentation Agent - docstrings, comments and explainability."""
from __future__ import annotations

from typing import Dict, Sequence

from agents.base import ReviewAgent, ReviewContext


class DocumentationAgent(ReviewAgent):
    """Reviews how well the code explains itself: module/class/function
    docstrings and the comment ratio of larger files."""

    name = "Documentation Agent"
    role = "documentation and explainability review"
    categories = ("DOCUMENTATION",)
    rule_prefixes = ("DOC",)
    weight = 0.15
    description = "Checks docstring coverage and comment density for maintainability."

    def extra_penalty(self, context: ReviewContext, findings: Sequence[Dict[str, object]]) -> float:
        ratio = context.metrics.get("comment_ratio")
        penalty = 0.0
        if isinstance(ratio, (int, float)):
            if ratio < 0.02:
                penalty += 6.0
            elif ratio < 0.05:
                penalty += 3.0
        missing_docstrings = sum(
            1 for f in findings if str(f.get("rule_id")) in {"DOC001", "DOC002", "DOC003"}
        )
        penalty += min(missing_docstrings * 0.5, 10.0)
        return penalty

    def build_summary(self, context: ReviewContext, findings: Sequence[Dict[str, object]],
                      score: float, insights: Sequence[str]) -> str:
        ratio = context.metrics.get("comment_ratio")
        ratio_text = f" Comment ratio {float(ratio) * 100:.1f}%." if isinstance(ratio, (int, float)) else ""
        if not findings:
            return (
                f"Documentation Agent: documentation coverage looks healthy across "
                f"{context.files_analyzed} file(s). Score {score:.0f}/100.{ratio_text}"
            )
        missing = sum(
            1 for f in findings if str(f.get("rule_id")) in {"DOC001", "DOC002", "DOC003"}
        )
        head = f"Documentation Agent: {len(findings)} documentation gap(s), {missing} missing docstring(s)."
        return f"{head} Score {score:.0f}/100.{ratio_text} " + (insights[0] if insights else "")
