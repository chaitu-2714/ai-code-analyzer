"""Phase 8: markdown, HTML and JSON reports."""
import json
import os

from reports import ReportGenerator
from services.review_service import ReviewService


def make_report(session_factory, indexed_project):
    review_service = ReviewService(session_factory)
    result = review_service.review_project(indexed_project.id)
    generator = ReportGenerator(session_factory, review_service=review_service)
    return generator, result, review_service


def test_markdown_report_contains_scores_and_findings(session_factory, indexed_project):
    generator, result, _ = make_report(session_factory, indexed_project)
    markdown = generator.generate_report(int(result["session_id"]), "markdown")
    assert "# Code Review Report" in markdown
    assert "Agent scores" in markdown
    assert "Security Analysis Agent" in markdown
    assert "CRITICAL" in markdown


def test_html_report_is_self_contained(session_factory, indexed_project):
    generator, result, _ = make_report(session_factory, indexed_project)
    html = generator.generate_report(int(result["session_id"]), "html")
    assert html.startswith("<!DOCTYPE html>")
    assert "<table>" in html
    assert str(result["overall_score"]) in html


def test_json_report_round_trips(session_factory, indexed_project):
    generator, result, _ = make_report(session_factory, indexed_project)
    payload = json.loads(generator.generate_report(int(result["session_id"]), "json"))
    assert payload["session_id"] == result["session_id"]
    assert len(payload["agents"]) == 5
    assert payload["findings"]


def test_export_writes_file(session_factory, indexed_project, tmp_path):
    generator, result, _ = make_report(session_factory, indexed_project)
    target = tmp_path / "reports" / "review.md"
    path = generator.export(int(result["session_id"]), str(target))
    assert os.path.exists(path)
    assert os.path.getsize(path) > 200


def test_unsupported_format_raises(session_factory, indexed_project):
    import pytest

    from core.exceptions import ApplicationError

    generator, result, _ = make_report(session_factory, indexed_project)
    with pytest.raises(ApplicationError):
        generator.generate_report(int(result["session_id"]), "pdf")


def test_project_summary_payload(session_factory, indexed_project):
    generator, result, _ = make_report(session_factory, indexed_project)
    summary = generator.project_summary(indexed_project.id)
    assert summary["latest_score"] == result["overall_score"]
    assert summary["reviews"] == 1
    assert summary["trend"]
    assert summary["open_findings"] > 0
