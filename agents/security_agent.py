"""Security Analysis Agent - injection, secrets and unsafe primitives."""
from __future__ import annotations

from typing import Dict, Sequence

from agents.base import ReviewAgent, ReviewContext


class SecurityAnalysisAgent(ReviewAgent):
    """Reviews the codebase for exploitable patterns: code execution, injection,
    hardcoded credentials, unsafe deserialisation and disabled TLS checks."""

    name = "Security Analysis Agent"
    role = "security and vulnerability review"
    categories = ("SECURITY",)
    rule_prefixes = ("SEC",)
    weight = 0.25
    description = "Flags injection, eval/exec, secrets in source, weak crypto and insecure transport."

    def extra_penalty(self, context: ReviewContext, findings: Sequence[Dict[str, object]]) -> float:
        critical = sum(1 for f in findings if str(f.get("severity")) == "CRITICAL")
        secrets = sum(1 for f in findings if str(f.get("rule_id")) in {"SEC006", "SEC101", "SEC102", "SEC103"})
        return 6.0 * min(critical, 3) + 4.0 * min(secrets, 3)

    def build_summary(self, context: ReviewContext, findings: Sequence[Dict[str, object]],
                      score: float, insights: Sequence[str]) -> str:
        if not findings:
            return (
                f"Security Analysis Agent: no exploitable patterns detected across "
                f"{context.files_analyzed} file(s). Score {score:.0f}/100."
            )
        critical = sum(1 for f in findings if str(f.get("severity")) == "CRITICAL")
        head = f"Security Analysis Agent: {len(findings)} security finding(s)"
        if critical:
            head += f" including {critical} critical - treat as release blocking"
        return f"{head}. Score {score:.0f}/100. " + (insights[0] if insights else "")
