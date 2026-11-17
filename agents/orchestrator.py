"""Multi-agent orchestrator: runs every review agent and aggregates the verdict."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence

from agents.base import AgentResult, ReviewAgent, ReviewContext
from agents.bug_agent import BugDetectionAgent
from agents.documentation_agent import DocumentationAgent
from agents.performance_agent import PerformanceAnalysisAgent
from agents.quality_agent import CodeQualityAgent
from agents.security_agent import SecurityAnalysisAgent
from llm.base import LLMProvider
from llm.local_provider import LocalHeuristicProvider

logger = logging.getLogger(__name__)

DEFAULT_AGENT_CLASSES = (
    BugDetectionAgent,
    SecurityAnalysisAgent,
    PerformanceAnalysisAgent,
    CodeQualityAgent,
    DocumentationAgent,
)

RISK_LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")


@dataclass
class ReviewResult:
    """Aggregated verdict of a multi-agent review."""

    agents: List[AgentResult] = field(default_factory=list)
    overall_score: float = 0.0
    risk_level: str = "LOW"
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    summary: str = ""
    provider: str = "local"
    llm_used: bool = False
    duration_seconds: float = 0.0
    project_id: int = 0

    def agent(self, name: str) -> Optional[AgentResult]:
        return next((a for a in self.agents if a.agent_name == name), None)

    def to_dict(self) -> Dict[str, object]:
        return {
            "project_id": self.project_id,
            "overall_score": round(self.overall_score, 1),
            "risk_level": self.risk_level,
            "total_findings": self.total_findings,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "summary": self.summary,
            "provider": self.provider,
            "llm_used": self.llm_used,
            "duration_seconds": round(self.duration_seconds, 3),
            "agents": [agent.to_dict() for agent in self.agents],
        }


class AgentOrchestrator:
    """Runs the five specialist agents and combines their scores."""

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        agents: Optional[Sequence[ReviewAgent]] = None,
    ):
        self.provider = provider or LocalHeuristicProvider()
        agent_classes = agents if agents is not None else DEFAULT_AGENT_CLASSES
        self.agents: List[ReviewAgent] = [
            agent if isinstance(agent, ReviewAgent) else agent(self.provider)
            for agent in agent_classes
        ]
        for agent in self.agents:
            agent.provider = self.provider
        self._normalise_weights()

    def _normalise_weights(self) -> None:
        total = sum(agent.weight for agent in self.agents) or 1.0
        for agent in self.agents:
            agent.weight = round(agent.weight / total, 4)

    # -- public API --------------------------------------------------------
    def describe_agents(self) -> List[Dict[str, object]]:
        return [agent.describe() for agent in self.agents]

    def run(
        self,
        context: ReviewContext,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> ReviewResult:
        started = time.perf_counter()
        results: List[AgentResult] = []
        total = len(self.agents)

        for index, agent in enumerate(self.agents):
            if progress_callback:
                progress_callback(agent.name, int(index / max(total, 1) * 100))
            try:
                results.append(agent.run(context))
            except Exception as error:  # pragma: no cover - defensive
                logger.exception("Agent %s failed", agent.name)
                results.append(
                    AgentResult(
                        agent_name=agent.name,
                        score=0.0,
                        weight=agent.weight,
                        summary=f"{agent.name} could not complete: {error}",
                        status="FAILED",
                    )
                )

        if progress_callback:
            progress_callback("Aggregating", 100)

        overall = self._overall_score(results)
        critical = sum(result.critical_count for result in results)
        high = sum(result.high_count for result in results)
        risk = self._risk_level(overall, critical, high)

        summary = ""
        if self.provider.available() and getattr(self.provider, "name", "local") != "local":
            try:
                summary = self.provider.review_summary(
                    overall, [result.to_dict() for result in results]
                )
            except Exception:  # pragma: no cover - defensive
                summary = ""
        if not summary:
            summary = self.provider.review_summary(
                overall, [result.to_dict() for result in results]
            )

        return ReviewResult(
            agents=results,
            overall_score=overall,
            risk_level=risk,
            total_findings=sum(result.findings_count for result in results),
            critical_count=critical,
            high_count=high,
            summary=summary,
            provider=getattr(self.provider, "name", "local"),
            llm_used=any(result.llm_used for result in results),
            duration_seconds=time.perf_counter() - started,
            project_id=context.project_id,
        )

    # -- scoring -----------------------------------------------------------
    @staticmethod
    def _overall_score(results: Sequence[AgentResult]) -> float:
        """Weighted average, capped when release-blocking issues exist.

        A single critical finding caps the project score at 65 and three or more
        high findings cap it at 80, so a dangerous release can never look clean.
        """
        if not results:
            return 0.0
        total_weight = sum(result.weight for result in results) or 1.0
        weighted = sum(result.score * result.weight for result in results) / total_weight
        critical = sum(result.critical_count for result in results)
        high = sum(result.high_count for result in results)
        if critical > 0:
            weighted = min(weighted, 65.0)
        elif high >= 3:
            weighted = min(weighted, 80.0)
        return round(max(0.0, min(100.0, weighted)), 1)

    @staticmethod
    def _risk_level(overall: float, critical: int, high: int) -> str:
        if critical > 0 or overall < 40:
            return "CRITICAL"
        if overall < 60 or high >= 5:
            return "HIGH"
        if overall < 80 or high > 0:
            return "MODERATE"
        return "LOW"
