"""Provider-agnostic LLM interface.

The platform must work with **no network access at all**, so every provider
implements :meth:`agent_insights` with a deterministic fallback.  A hosted
provider only *enriches* the deterministic review; it never gates it.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Sequence

from core.exceptions import LLMError
from llm.insights import local_insights, parse_insight_list, render_prompt

logger = logging.getLogger(__name__)

#: Process-wide health flags so one failed provider is not retried per review.
PROVIDER_HEALTH: Dict[str, bool] = {}


def provider_is_healthy(name: str) -> bool:
    return PROVIDER_HEALTH.get(name, True)


def mark_provider_unhealthy(name: str) -> None:
    PROVIDER_HEALTH[name] = False


def reset_provider_health() -> None:
    PROVIDER_HEALTH.clear()


class LLMProvider(ABC):
    """Interface for LLM service providers."""

    name: str = "base"
    model: str = ""

    # -- capability --------------------------------------------------------
    def available(self) -> bool:
        """Whether this provider can be used in the current environment.

        A provider that failed once during a run is disabled for the rest of
        that run, so a blocked network never costs one timeout per agent.
        """
        return not getattr(self, "_disabled", False) and provider_is_healthy(self.name)

    # -- raw generation ----------------------------------------------------
    @abstractmethod
    def generate(self, prompt: str, system: Optional[str] = None, max_tokens: int = 800) -> str:
        """Generates text for ``prompt``; raises :class:`LLMError` on failure."""

    # -- review helpers ----------------------------------------------------
    def agent_insights(
        self,
        agent_name: str,
        role: str,
        findings: Sequence[Dict[str, object]],
        metrics: Optional[Dict[str, object]] = None,
        limit: int = 5,
    ) -> List[str]:
        """Insights for one agent; falls back to deterministic analysis on error."""
        fallback = local_insights(agent_name, findings, metrics, limit=limit)
        if not self.available():
            return fallback
        prompt = render_prompt(agent_name, role, findings, metrics, limit=limit)
        try:
            text = self.generate(prompt, system=role, max_tokens=600)
        except LLMError as error:
            logger.info("LLM provider %s unavailable for %s: %s", self.name, agent_name, error)
            self._disabled = True
            mark_provider_unhealthy(self.name)
            return fallback
        except Exception as error:  # pragma: no cover - defensive
            logger.warning("Unexpected LLM failure for %s: %s", agent_name, error)
            return fallback
        parsed = parse_insight_list(text, limit=limit)
        return parsed or fallback

    def review_summary(self, overall_score: float, agent_results: Sequence[Dict[str, object]]) -> str:
        """One-paragraph summary of a completed multi-agent review."""
        weakest = sorted(agent_results, key=lambda r: float(r.get("score", 100.0)))[:2]
        strong = [
            r
            for r in agent_results
            if float(r.get("score", 0)) >= 90 and int(r.get("findings_count", 0)) == 0
        ]
        parts = [
            f"Overall quality score {overall_score:.1f}/100 across {len(agent_results)} agents."
        ]
        if weakest and float(weakest[0].get("score", 100)) < 100:
            parts.append(
                "Weakest dimensions: "
                + ", ".join(
                    f"{r.get('agent_name')} ({float(r.get('score', 0)):.0f})" for r in weakest
                )
                + "."
            )
        if strong:
            parts.append("Clean dimensions: " + ", ".join(str(r.get("agent_name")) for r in strong) + ".")
        return " ".join(parts)

    def describe(self) -> Dict[str, object]:
        return {"provider": self.name, "model": self.model, "available": self.available()}
