"""Phase 3 service: analysis runs persisted to the database."""
import pytest

from core.exceptions import AnalysisError
from services.analysis_service import AnalysisService


def test_run_persists_findings_metrics_and_run(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    summary = service.run(indexed_project.id)

    assert summary["status"] == "COMPLETED"
    assert summary["files_analyzed"] >= 3
    assert summary["findings"] > 0

    run = service.latest_run(indexed_project.id)
    assert run["run_id"] == summary["run_id"]
    assert run["status"] == "COMPLETED"

    findings = service.findings(indexed_project.id)
    assert findings
    severities = {finding["severity"] for finding in findings}
    assert "CRITICAL" in severities
    assert any(finding["rule_id"] == "SEC001" for finding in findings)

    metrics = service.metrics(indexed_project.id)
    assert metrics["files"] >= 3
    assert metrics["lines_of_code"] > 0
    assert metrics["maintainability_index"] is not None


def test_severity_filter_and_counts(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    counts = service.severity_counts(indexed_project.id)
    critical = service.findings(indexed_project.id, severity="CRITICAL")
    assert len(critical) == counts["CRITICAL"]
    assert all(finding["severity"] == "CRITICAL" for finding in critical)


def test_dependencies_and_duplicates_are_stored(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    summary = service.run(indexed_project.id)
    run_id = int(summary["run_id"])
    assert isinstance(service.dependencies(run_id), list)
    assert isinstance(service.duplicates(run_id), list)


def test_analysis_fails_without_files(session_factory, project_repo):
    project = project_repo.create(name="Empty")
    service = AnalysisService(session_factory)
    with pytest.raises(AnalysisError):
        service.run(project.id)
    run = service.latest_run(project.id)
    assert run["status"] == "FAILED"
    assert run["error_message"]


def test_unknown_project_raises(session_factory):
    service = AnalysisService(session_factory)
    with pytest.raises(AnalysisError):
        service.run(9999)


def test_project_metrics(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    stats = service.project_metrics(indexed_project.id)
    assert stats["files"] >= 3
    assert stats["runs"] == 1
    assert stats["findings"] > 0


def test_findings_are_sorted_worst_first(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    findings = service.findings(indexed_project.id)
    ranks = [order.index(finding["severity"]) for finding in findings]
    assert ranks == sorted(ranks)
