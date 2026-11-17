"""Multi-agent code review package (Phase 5).

Five specialist agents review one analysis run and the orchestrator aggregates
their verdicts into a single score and risk level.
"""
from agents.base import AgentResult, ReviewAgent, ReviewContext, score_from_findings  # noqa: F401
from agents.bug_agent import BugDetectionAgent  # noqa: F401
from agents.documentation_agent import DocumentationAgent  # noqa: F401
from agents.orchestrator import (  # noqa: F401
    DEFAULT_AGENT_CLASSES,
    AgentOrchestrator,
    ReviewResult,
)
from agents.performance_agent import PerformanceAnalysisAgent  # noqa: F401
from agents.quality_agent import CodeQualityAgent  # noqa: F401
from agents.security_agent import SecurityAnalysisAgent  # noqa: F401

__all__ = [
    "DEFAULT_AGENT_CLASSES",
    "AgentOrchestrator",
    "AgentResult",
    "BugDetectionAgent",
    "CodeQualityAgent",
    "DocumentationAgent",
    "PerformanceAnalysisAgent",
    "ReviewAgent",
    "ReviewContext",
    "ReviewResult",
    "SecurityAnalysisAgent",
    "score_from_findings",
]
