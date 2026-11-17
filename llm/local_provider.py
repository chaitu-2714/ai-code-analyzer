"""Offline provider: deterministic, dependency-free, always available."""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from core.exceptions import LLMError
from llm.base import LLMProvider
from llm.insights import local_insights, render_prompt


class LocalHeuristicProvider(LLMProvider):
    """Produces review insights from the analysis results without any model.

    ``generate`` is intentionally unsupported: this provider is not a language
    model.  Agents use :meth:`agent_insights`, which is fully deterministic and
    therefore reproducible in tests and on air-gapped machines.
    """

    name = "local"
    model = "heuristic-v1"

    def available(self) -> bool:
        return True

    def generate(self, prompt: str, system: Optional[str] = None, max_tokens: int = 800) -> str:
        raise LLMError(
            "The local provider has no generative model; use agent_insights() instead."
        )

    def agent_insights(
        self,
        agent_name: str,
        role: str,
        findings: Sequence[Dict[str, object]],
        metrics: Optional[Dict[str, object]] = None,
        limit: int = 5,
    ) -> List[str]:
        return local_insights(agent_name, findings, metrics, limit=limit)

    def preview_prompt(
        self,
        agent_name: str,
        role: str,
        findings: Sequence[Dict[str, object]],
        metrics: Optional[Dict[str, object]] = None,
    ) -> str:
        """Exposes the prompt a hosted provider would have received."""
        return render_prompt(agent_name, role, findings, metrics)
