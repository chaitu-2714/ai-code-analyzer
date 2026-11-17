"""LLM integration layer (Phase 4).

Exports the provider interface, the offline provider and the factory.  Importing
this package never performs network I/O.
"""
from llm.base import LLMProvider  # noqa: F401
from llm.factory import create_provider, provider_for  # noqa: F401
from llm.insights import local_insights, parse_insight_list, render_prompt  # noqa: F401
from llm.local_provider import LocalHeuristicProvider  # noqa: F401

__all__ = [
    "LLMProvider",
    "LocalHeuristicProvider",
    "create_provider",
    "local_insights",
    "parse_insight_list",
    "provider_for",
    "render_prompt",
]
