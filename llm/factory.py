"""Provider factory with graceful degradation to the offline provider."""
from __future__ import annotations

import logging
import os
from typing import Optional

from core.exceptions import LLMError
from llm.base import LLMProvider, provider_is_healthy
from llm.local_provider import LocalHeuristicProvider

logger = logging.getLogger(__name__)

VALID_MODES = ("auto", "local", "gemini")
DEFAULT_MODEL = "gemini-3.8-flash"


def _clean(model: Optional[str]) -> str:
    text = str(model or "").strip().strip('"').strip("'")
    text = text.removeprefix("models/")
    lowered = text.lower()
    if not text or any(token in lowered for token in ("your_", "placeholder", "model_name", "xxx")):
        return DEFAULT_MODEL
    return text


class _EnvSettings:
    """Minimal settings view so the factory works without a Config object."""

    def __init__(self, **kwargs):
        self.llm_provider = kwargs.get("llm_provider", os.getenv("LLM_PROVIDER", "auto").strip().lower())
        self.gemini_api_key = kwargs.get("gemini_api_key", os.getenv("GEMINI_API_KEY", "").strip())
        self.gemini_model = kwargs.get(
            "gemini_model", _clean(os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
        )
        self.gemini_timeout = float(kwargs.get("gemini_timeout", os.getenv("GEMINI_TIMEOUT", "15.0")))
        self.gemini_max_retries = int(kwargs.get("gemini_max_retries", os.getenv("GEMINI_MAX_RETRIES", "1")))


def create_provider(config=None, mode: Optional[str] = None) -> LLMProvider:
    """Builds the configured provider.

    ``auto`` (the default) uses Gemini when a key is configured and silently
    falls back to the offline provider otherwise, so the agents always work.
    """
    settings = config if config is not None else _EnvSettings()
    requested = (mode or getattr(settings, "llm_provider", "auto") or "auto").strip().lower()
    if requested not in VALID_MODES:
        logger.warning("Unknown LLM_PROVIDER '%s'; using 'auto'.", requested)
        requested = "auto"

    if requested == "local":
        return LocalHeuristicProvider()

    api_key = getattr(settings, "gemini_api_key", "") or ""
    if requested == "gemini" and not api_key:
        logger.warning("LLM_PROVIDER=gemini but GEMINI_API_KEY is empty; using the offline provider.")
        return LocalHeuristicProvider()

    if api_key and not provider_is_healthy("gemini"):
        logger.info("Gemini failed earlier in this run; using the offline provider.")
        return LocalHeuristicProvider()

    if api_key:
        try:
            from llm.gemini_provider import GeminiProvider

            return GeminiProvider(
                api_key=api_key,
                model=_clean(getattr(settings, "gemini_model", DEFAULT_MODEL)),
                timeout=float(getattr(settings, "gemini_timeout", 30.0)),
                max_retries=int(getattr(settings, "gemini_max_retries", 1)),
            )
        except LLMError as error:
            logger.warning("Gemini provider unavailable (%s); using the offline provider.", error)

    return LocalHeuristicProvider()


def provider_for(config, requested: Optional[str] = None) -> LLMProvider:
    """Alias kept for readability in services."""
    return create_provider(config, requested)
