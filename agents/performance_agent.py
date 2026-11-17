"""Performance Analysis Agent - resource and complexity hotspots."""
from __future__ import annotations

from typing import Dict, Sequence

from agents.base import ReviewAgent, ReviewContext


class PerformanceAnalysisAgent(ReviewAgent):
    """Reviews algorithmic and resource problems: quadratic string building,
    leaked file handles, nested loops and unnecessary indexing."""

    name = "Performance Analysis Agent"
    role = "performance and resource efficiency review"
    categories = ("PERFORMANCE",)
    rule_prefixes = ("PERF",)
    weight = 0.15
    description = "Detects leaked file handles, quadratic loops, nested loops and indexing anti-patterns."

    def extra_penalty(self, context: ReviewContext, findings: Sequence[Dict[str, object]]) -> float:
        penalty = 0.0
        max_complexity = context.metrics.get("max_complexity") or 0
        if isinstance(max_complexity, (int, float)) and max_complexity > 25:
            penalty += min((float(max_complexity) - 25) * 0.6, 8.0)
        return penalty

    def build_summary(self, context: ReviewContext, findings: Sequence[Dict[str, object]],
                      score: float, insights: Sequence[str]) -> str:
        if not findings:
            return (
                f"Performance Analysis Agent: no hot-path anti-patterns in "
                f"{context.files_analyzed} file(s). Score {score:.0f}/100."
            )
        loops = sum(1 for f in findings if str(f.get("rule_id")) in {"PERF002", "PERF004"})
        head = f"Performance Analysis Agent: {len(findings)} efficiency issue(s)"
        if loops:
            head += f", {loops} in loop-heavy code"
        return f"{head}. Score {score:.0f}/100. " + (insights[0] if insights else "")
