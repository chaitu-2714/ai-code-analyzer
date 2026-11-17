"""Bug Detection Agent - correctness issues that break behaviour at runtime."""
from __future__ import annotations

from typing import Dict, Sequence

from agents.base import ReviewAgent, ReviewContext


class BugDetectionAgent(ReviewAgent):
    """Reviews syntax errors, swallowed exceptions, mutable defaults and
    other correctness problems that surface as production bugs."""

    name = "Bug Detection Agent"
    role = "finding logic errors and runtime failures"
    categories = ("BUG", "SYNTAX")
    rule_prefixes = ("BUG", "SYN")
    weight = 0.25
    description = "Detects runtime defects: bare excepts, mutable defaults, syntax errors, self-assignment."

    def extra_penalty(self, context: ReviewContext, findings: Sequence[Dict[str, object]]) -> float:
        penalty = 0.0
        syntax_errors = [f for f in findings if str(f.get("rule_id")) == "SYN001"]
        if syntax_errors:
            penalty += 8.0 * min(len(syntax_errors), 3)
        swallowed = [f for f in findings if str(f.get("rule_id")) in {"BUG001", "BUG005"}]
        if swallowed:
            penalty += 2.0 * min(len(swallowed), 4)
        return penalty

    def build_summary(self, context: ReviewContext, findings: Sequence[Dict[str, object]],
                      score: float, insights: Sequence[str]) -> str:
        if not findings:
            return (
                f"Bug Detection Agent: no correctness defects in {context.files_analyzed} file(s). "
                f"Score {score:.0f}/100."
            )
        syntax = sum(1 for f in findings if str(f.get("rule_id")) == "SYN001")
        head = f"Bug Detection Agent: {len(findings)} correctness issue(s)"
        if syntax:
            head += f", {syntax} of them syntax errors that block analysis"
        return f"{head}. Score {score:.0f}/100. " + (insights[0] if insights else "")
