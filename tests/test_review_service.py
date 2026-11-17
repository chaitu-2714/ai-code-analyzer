"""Phase 5 service: multi-agent review persisted per agent."""
from services.analysis_service import AnalysisService
from services.review_service import ReviewService


def test_review_runs_analysis_and_persists_agents(session_factory, indexed_project):
    review_service = ReviewService(session_factory)
    result = review_service.review_project(indexed_project.id)

    assert result["session_id"]
    assert 0 <= result["overall_score"] <= 100
    assert result["risk_level"] in {"LOW", "MODERATE", "HIGH", "CRITICAL"}
    assert len(result["agents"]) == 5
    names = {agent["agent_name"] for agent in result["agents"]}
    assert "Security Analysis Agent" in names

    stored = review_service.get_review(int(result["session_id"]))
    assert stored["overall_score"] == result["overall_score"]
    assert len(stored["agents"]) == 5
    assert all(isinstance(agent["insights"], list) for agent in stored["agents"])


def test_review_reuses_latest_analysis_run(session_factory, indexed_project):
    analysis = AnalysisService(session_factory)
    summary = analysis.run(indexed_project.id)
    review_service = ReviewService(session_factory, analysis_service=analysis)
    result = review_service.review_project(indexed_project.id)
    assert result["analysis_run_id"] == summary["run_id"]


def test_review_without_analysis_can_refuse(session_factory, indexed_project):
    review_service = ReviewService(session_factory)
    try:
        review_service.review_project(indexed_project.id, run_analysis_if_missing=False)
    except Exception as error:
        assert "analysis" in str(error).lower()
    else:  # pragma: no cover - defensive
        raise AssertionError("expected an error when no analysis run exists")


def test_quality_trend_and_leaderboard(session_factory, indexed_project):
    review_service = ReviewService(session_factory)
    review_service.review_project(indexed_project.id)
    review_service.review_project(indexed_project.id)

    trend = review_service.quality_trend(indexed_project.id)
    assert len(trend) == 2
    assert trend[-1]["overall_score"] is not None

    leaderboard = review_service.agent_leaderboard(indexed_project.id)
    assert len(leaderboard) == 5
    assert all("average_score" in row for row in leaderboard)


def test_review_filters_findings_by_diff(session_factory, indexed_project):
    review_service = ReviewService(session_factory)
    full = review_service.review_project(indexed_project.id)

    diff = (
        "--- a/bad_app.py\n+++ b/bad_app.py\n"
        "@@ -1,3 +1,3 @@\n import os\n+API_KEY = 'sk_live_abcdef123456'\n"
    )
    scoped = review_service.review_project(indexed_project.id, diff_text=diff)
    assert scoped["total_findings"] <= full["total_findings"]


def test_latest_review_returns_none_when_missing(session_factory, project_repo):
    project = project_repo.create(name="No reviews")
    assert ReviewService(session_factory).latest_review(project.id) is None
