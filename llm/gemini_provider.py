"""Google Gemini provider (REST, no SDK dependency).

The API key is sent in the ``x-goog-api-key`` header so it never appears in a
URL, a log line or a stack trace.  Any failure raises :class:`LLMError`; agents
then fall back to the deterministic local provider.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

from core.exceptions import LLMError
from llm.base import LLMProvider, mark_provider_unhealthy

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.8-flash"


_SUGGESTED = re.compile(r"models/([A-Za-z0-9._\-]+)")


def _suggested_model(body: str) -> Optional[str]:
    """Extracts a replacement model name from a Gemini error body."""
    if not body or "no longer available" not in body.lower():
        return None
    for match in _SUGGESTED.finditer(body):
        candidate = match.group(1)
        if candidate and candidate != "generateContent":
            return candidate
    return None


def _sanitise_model(model: Optional[str]) -> str:
    """Guards against placeholder values in GEMINI_MODEL."""
    text = str(model or "").strip().strip('"').strip("'")
    text = text.removeprefix("models/")
    lowered = text.lower()
    if not text or any(token in lowered for token in ("your_", "placeholder", "model_name", "xxx")):
        return DEFAULT_MODEL
    return text


class GeminiProvider(LLMProvider):
    """Calls the Gemini ``generateContent`` endpoint."""

    name = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        timeout: float = 30.0,
        max_retries: int = 1,
    ):
        if not api_key or not str(api_key).strip():
            raise LLMError("GEMINI_API_KEY is not configured.")
        self._api_key = str(api_key).strip()
        self.model = _sanitise_model(model)
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))

    def available(self) -> bool:
        if not self._api_key or getattr(self, "_disabled", False):
            return False
        if not getattr(self, "_probed", False):
            self._probed = True
            if not self.probe():
                self._disabled = True
                mark_provider_unhealthy(self.name)
                return False
        return True

    def probe(self) -> bool:
        """Cheap connectivity + model check so a blocked network fails fast."""
        url = f"{API_ROOT}/{self.model}"
        request = urllib.request.Request(
            url, headers={"x-goog-api-key": self._api_key}, method="GET"
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self.timeout, 8.0)) as response:
                response.read(64)
            return True
        except urllib.error.HTTPError as error:
            if error.code in (400, 404):
                # The key is valid but the model name is not; let generate()
                # auto-heal from the error body rather than disabling here.
                return True
            logger.info("Gemini probe failed with HTTP %s; using the offline provider.", error.code)
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            logger.info("Gemini probe failed (%s); using the offline provider.", error)
            return False

    def __repr__(self) -> str:  # never leak the key
        return f"<GeminiProvider model='{self.model}'>"

    def generate(self, prompt: str, system: Optional[str] = None, max_tokens: int = 800) -> str:
        payload: Dict[str, object] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max(64, int(max_tokens)),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        body = json.dumps(payload).encode("utf-8")
        url = f"{API_ROOT}/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            url = f"{API_ROOT}/{self.model}:generateContent"
            request = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8", "ignore")
                return self._extract_text(raw)
            except urllib.error.HTTPError as error:
                detail = ""
                try:
                    detail = error.read().decode("utf-8", "ignore")[:400]
                except Exception:  # pragma: no cover - defensive
                    detail = ""
                summary = " ".join(detail.split())[:160]
                last_error = LLMError(f"Gemini HTTP {error.code}: {summary}")
                # A retired model name is recoverable: Google tells us the
                # replacement in the error body, so switch and retry once.
                suggested = _suggested_model(detail)
                if error.code == 404 and suggested and suggested != self.model:
                    logger.info("Model %s is retired; switching to %s.", self.model, suggested)
                    self.model = suggested
                    continue
                if error.code in (400, 401, 403, 404):
                    break  # configuration problem: retrying cannot help
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = LLMError(f"Gemini request failed: {error}")
            except json.JSONDecodeError as error:
                last_error = LLMError(f"Gemini returned invalid JSON: {error}")
            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 4))

        raise last_error or LLMError("Gemini request failed.")

    @staticmethod
    def _extract_text(raw: str) -> str:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as error:
            raise LLMError(f"Gemini returned invalid JSON: {error}") from error

        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            raise LLMError(f"Gemini returned no candidates ({feedback}).")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        if not text:
            raise LLMError("Gemini returned an empty response.")
        return text
