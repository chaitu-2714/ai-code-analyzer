"""Code Quality Agent - structure, complexity, duplication and dependencies."""
from __future__ import annotations

from typing import Dict, Sequence

from agents.base import ReviewAgent, ReviewContext


class CodeQualityAgent(ReviewAgent):
    """Reviews maintainability: function size, cyclomatic complexity, nesting,
    duplicated blocks and dependency hygiene."""

    name = "Code Quality Agent"
    role = "maintainability, structure and duplication review"
    categories = ("QUALITY", "DUPLICATION", "DEPENDENCY")
    rule_prefixes = ("QUA", "DUP", "DEP")
    weight = 0.20
    description = "Scores complexity, nesting, duplication and dependency graph health."

    def extra_penalty(self, context: ReviewContext, findings: Sequence[Dict[str, object]]) -> float:
        penalty = 0.0
        average_complexity = context.metrics.get("average_complexity") or 0
        if isinstance(average_complexity, (int, float)) and average_complexity > 6:
            penalty += min((float(average_complexity) - 6) * 2.0, 12.0)

        maintainability = context.metrics.get("maintainability_index")
        if isinstance(maintainability, (int, float)) and maintainability < 55:
            penalty += min((55 - float(maintainability)) * 0.35, 12.0)

        if context.duplicate_groups:
            penalty += min(context.duplicate_groups * 1.5, 8.0)
        if context.dependency_issues:
            penalty += min(context.dependency_issues * 1.0, 6.0)
        return penalty

    def build_summary(self, context: ReviewContext, findings: Sequence[Dict[str, object]],
                      score: float, insights: Sequence[str]) -> str:
        maintainability = context.metrics.get("maintainability_index")
        complexity = context.metrics.get("average_complexity")
        metrics_text = ""
        if maintainability is not None or complexity is not None:
            metrics_text = (
                f" Maintainability {maintainability if maintainability is not None else 'n/a'}/100,"
                f" average complexity {complexity if complexity is not None else 'n/a'}."
            )
        if not findings:
            return (
                f"Code Quality Agent: no structural issues in {context.files_analyzed} file(s). "
                f"Score {score:.0f}/100.{metrics_text}"
            )
        head = (
            f"Code Quality Agent: {len(findings)} maintainability issue(s) "
            f"({context.duplicate_groups} duplicate block group(s)). Score {score:.0f}/100."
        )
        return f"{head}{metrics_text} " + (insights[0] if insights else "")
