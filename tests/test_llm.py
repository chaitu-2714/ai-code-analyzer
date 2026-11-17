"""LLM layer: offline provider, factory fallback, prompt parsing and Gemini errors."""
import json

import pytest

from core.exceptions import LLMError
from llm.base import PROVIDER_HEALTH, reset_provider_health
from llm.factory import create_provider
from llm.insights import local_insights, parse_insight_list, render_prompt
from llm.local_provider import LocalHeuristicProvider


class Settings:
    def __init__(self, **kwargs):
        self.llm_provider = kwargs.get("llm_provider", "auto")
        self.gemini_api_key = kwargs.get("gemini_api_key", "")
        self.gemini_model = kwargs.get("gemini_model", "gemini-3.8-flash")
        self.gemini_timeout = kwargs.get("gemini_timeout", 1.0)
        self.gemini_max_retries = kwargs.get("gemini_max_retries", 0)


@pytest.fixture(autouse=True)
def clear_health():
    reset_provider_health()
    yield
    reset_provider_health()


def test_local_provider_is_always_available():
    provider = LocalHeuristicProvider()
    assert provider.available()
    assert provider.describe()["provider"] == "local"


def test_local_generate_raises():
    with pytest.raises(LLMError):
        LocalHeuristicProvider().generate("hi")


def test_local_insights_summarise_findings():
    findings = [
        {"rule_id": "SEC001", "severity": "CRITICAL", "title": "Use of eval/exec",
         "file_path": "a.py", "line_start": 3},
        {"rule_id": "SEC001", "severity": "CRITICAL", "title": "Use of eval/exec",
         "file_path": "b.py", "line_start": 9},
    ]
    insights = local_insights("Security Analysis Agent", findings, {"average_complexity": 4.0})
    assert any("2x" in item for item in insights)
    assert any("critical" in item.lower() for item in insights)


def test_local_insights_when_clean():
    insights = local_insights("Bug Detection Agent", [], {})
    assert "No bug detection agent issues" in insights[0]


def test_parse_insight_list_handles_json_and_prose():
    assert parse_insight_list('["a b c", "d e f"]') == ["a b c", "d e f"]
    assert parse_insight_list('```json\n["one two three"]\n```') == ["one two three"]
    assert parse_insight_list("Some long sentence that is not json at all") == [
        "Some long sentence that is not json at all"
    ]


def test_render_prompt_mentions_findings():
    prompt = render_prompt("Agent", "role", [{"rule_id": "BUG001", "severity": "HIGH",
                                              "title": "Bare except", "file_path": "a.py",
                                              "line_start": 2}], {"lines_of_code": 10})
    assert "BUG001" in prompt and "JSON array" in prompt


def test_factory_returns_local_without_key():
    provider = create_provider(Settings())
    assert provider.name == "local"


def test_factory_local_mode_forces_local():
    provider = create_provider(Settings(llm_provider="local", gemini_api_key="key"))
    assert provider.name == "local"


def test_factory_builds_gemini_with_key():
    provider = create_provider(Settings(gemini_api_key="fake-key"))
    assert provider.name == "gemini"
    assert provider.model == "gemini-3.8-flash"


def test_placeholder_model_falls_back_to_default():
    provider = create_provider(Settings(gemini_api_key="k", gemini_model="YOUR_SUPPORTED_GEMINI_MODEL"))
    assert provider.model == "gemini-3.8-flash"


def test_gemini_http_error_becomes_llm_error(monkeypatch):
    from llm import gemini_provider

    def boom(*args, **kwargs):
        raise gemini_provider.urllib.error.URLError("no network")

    monkeypatch.setattr(gemini_provider.urllib.request, "urlopen", boom)
    provider = gemini_provider.GeminiProvider(api_key="k", model="m", timeout=0.5, max_retries=0)
    with pytest.raises(LLMError):
        provider.generate("hello")


def test_gemini_extracts_text(monkeypatch):
    from llm import gemini_provider

    payload = json.dumps({"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}).encode()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return payload

    monkeypatch.setattr(gemini_provider.urllib.request, "urlopen", lambda *a, **k: Response())
    provider = gemini_provider.GeminiProvider(api_key="k", model="m", timeout=1, max_retries=0)
    assert provider.generate("hello") == "OK"


def test_failed_provider_is_not_retried(monkeypatch):
    from llm import gemini_provider

    calls = {"count": 0}

    def boom(*args, **kwargs):
        calls["count"] += 1
        raise gemini_provider.urllib.error.URLError("blocked")

    monkeypatch.setattr(gemini_provider.urllib.request, "urlopen", boom)
    provider = create_provider(Settings(gemini_api_key="k", gemini_timeout=0.5))
    first = provider.agent_insights("Agent", "role", [], {})
    assert first  # deterministic fallback always returns something
    assert PROVIDER_HEALTH.get("gemini") is False
    assert calls["count"] == 1
    assert create_provider(Settings(gemini_api_key="k")).name == "local"


def test_agent_insights_falls_back_to_local_insights():
    findings = [{"rule_id": "BUG001", "severity": "HIGH", "title": "Bare except",
                 "file_path": "a.py", "line_start": 4}]
    provider = LocalHeuristicProvider()
    assert provider.agent_insights("Bug Detection Agent", "bugs", findings, {}) == local_insights(
        "Bug Detection Agent", findings, {}
    )
