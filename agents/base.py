"""Base classes shared by every review agent (Phase 5)."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from analyzer.rules.base import SEVERITY_PENALTY, SEVERITY_RANK, get_rule
from llm.base import LLMProvider
from llm.insights import local_insights, truncate

logger = logging.getLogger(__name__)


@dataclass
class ReviewContext:
    """Everything an agent needs: findings, metrics and project identity."""

    project_id: int = 0
    project_name: str = ""
    findings: List[Dict[str, object]] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)
    files_analyzed: int = 0
    duplicate_groups: int = 0
    dependency_issues: int = 0

    def by_categories(self, categories: Sequence[str]) -> List[Dict[str, object]]:
        wanted = {category.upper() for category in categories}
        return [f for f in self.findings if str(f.get("category", "")).upper() in wanted]

    def by_rule_prefixes(self, prefixes: Sequence[str]) -> List[Dict[str, object]]:
        wanted = tuple(prefix.upper() for prefix in prefixes)
        return [
            f
            for f in self.findings
            if str(f.get("rule_id") or "").upper().startswith(wanted)
        ]


@dataclass
class AgentResult:
    """Structured output of one agent."""

    agent_name: str
    score: float
    weight: float = 0.0
    summary: str = ""
    insights: List[str] = field(default_factory=list)
    findings: List[Dict[str, object]] = field(default_factory=list)
    findings_count: int = 0
    critical_count: int = 0
    high_count: int = 0
    llm_used: bool = False
    provider: str = "local"
    status: str = "COMPLETED"
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "agent_name": self.agent_name,
            "score": round(self.score, 1),
            "weight": self.weight,
            "summary": self.summary,
            "insights": list(self.insights),
            "findings_count": self.findings_count,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "llm_used": self.llm_used,
            "provider": self.provider,
            "status": self.status,
            "duration_seconds": round(self.duration_seconds, 3),
        }


def score_from_findings(
    findings: Sequence[Dict[str, object]],
    extra_penalty: float = 0.0,
    floor: float = 0.0,
) -> float:
    """Severity weighted penalty with diminishing returns, mapped to 0-100."""
    ordered = sorted(
        findings, key=lambda f: SEVERITY_RANK.get(str(f.get("severity")), 99)
    )
    penalty = 0.0
    for index, finding in enumerate(ordered):
        base = SEVERITY_PENALTY.get(str(finding.get("severity")), 1.0)
        confidence = finding.get("confidence")
        weight = float(confidence) if isinstance(confidence, (int, float)) else 1.0
        penalty += (base * max(min(weight, 1.0), 0.2)) / (1 + 0.35 * index)
    penalty += max(extra_penalty, 0.0)
    return round(max(floor, min(100.0, 100.0 - penalty)), 1)


class ReviewAgent:
    """Interface for multi-agent code review.

    A concrete agent declares the finding categories it owns, scores them and
    produces a short, actionable narrative.  The narrative comes from the
    configured :class:`LLMProvider` when one is available, otherwise from the
    deterministic local analysis.
    """

    name: str = "Review Agent"
    role: str = "general code review"
    categories: Sequence[str] = ()
    rule_prefixes: Sequence[str] = ()
    weight: float = 0.0
    description: str = ""

    def __init__(self, provider: Optional[LLMProvider] = None):
        self.provider = provider

    # -- selection ---------------------------------------------------------
    def select_findings(self, context: ReviewContext) -> List[Dict[str, object]]:
        selected: List[Dict[str, object]] = []
        if self.categories:
            selected.extend(context.by_categories(self.categories))
        if self.rule_prefixes:
            for finding in context.by_rule_prefixes(self.rule_prefixes):
                if finding not in selected:
                    selected.append(finding)
        selected.sort(key=lambda f: SEVERITY_RANK.get(str(f.get("severity")), 99))
        return selected

    def extra_penalty(self, context: ReviewContext, findings: Sequence[Dict[str, object]]) -> float:
        """Hook for metric-driven penalties (complexity, comment ratio, ...)."""
        return 0.0

    # -- run ---------------------------------------------------------------
    def run_review(self, project_id: int) -> AgentResult:
        """Legacy entry point kept for API compatibility."""
        raise NotImplementedError(
            "run_review(project_id) is not supported directly; call run(ReviewContext) "
            "or use AgentOrchestrator.review_project()."
        )

    def run(self, context: ReviewContext) -> AgentResult:
        started = time.perf_counter()
        findings = self.select_findings(context)
        penalty = self.extra_penalty(context, findings)
        score = score_from_findings(findings, extra_penalty=penalty)

        llm_used = False
        insights: List[str] = []
        provider_name = getattr(self.provider, "name", "local")
        if self.provider is not None and self.provider.available():
            before = list(insights)
            insights = self.provider.agent_insights(
                self.name, self.role, findings, context.metrics, limit=5
            )
            llm_used = bool(insights) and insights != before and provider_name != "local"
        if not insights:
            insights = local_insights(self.name, findings, context.metrics)

        result = AgentResult(
            agent_name=self.name,
            score=score,
            weight=self.weight,
            summary=self.build_summary(context, findings, score, insights),
            insights=insights,
            findings=findings,
            findings_count=len(findings),
            critical_count=sum(1 for f in findings if str(f.get("severity")) == "CRITICAL"),
            high_count=sum(1 for f in findings if str(f.get("severity")) == "HIGH"),
            llm_used=llm_used,
            provider=provider_name,
            duration_seconds=time.perf_counter() - started,
        )
        return result

    # -- narrative ---------------------------------------------------------
    def build_summary(
        self,
        context: ReviewContext,
        findings: Sequence[Dict[str, object]],
        score: float,
        insights: Sequence[str],
    ) -> str:
        if not findings:
            return (
                f"{self.name}: no {self.role} issues found in "
                f"{context.files_analyzed} analysed file(s). Score {score:.0f}/100."
            )
        top = findings[0]
        rule = get_rule(str(top.get("rule_id"))) if top.get("rule_id") else None
        title = rule.title if rule else str(top.get("title") or top.get("rule_id"))
        location = f"{top.get('file_path', '?')}:{top.get('line_start', '?')}"
        critical = sum(1 for f in findings if str(f.get("severity")) == "CRITICAL")
        high = sum(1 for f in findings if str(f.get("severity")) == "HIGH")
        mix = ", ".join(
            part for part in (f"{critical} critical" if critical else "", f"{high} high" if high else "") if part
        )
        mix_text = f" ({mix})" if mix else ""
        return truncate(
            f"{self.name}: {len(findings)} finding(s){mix_text}; score {score:.0f}/100. "
            f"Top risk: {title} at {location}. {insights[0] if insights else ''}",
            600,
        )

    def describe(self) -> Dict[str, object]:
        return {
            "agent_name": self.name,
            "role": self.role,
            "description": self.description,
            "categories": list(self.categories),
            "weight": self.weight,
        }
