"""The five review agents and the orchestrator."""
from agents import (
    AgentOrchestrator,
    BugDetectionAgent,
    CodeQualityAgent,
    DocumentationAgent,
    PerformanceAnalysisAgent,
    ReviewContext,
    SecurityAnalysisAgent,
)
from agents.base import score_from_findings


def finding(rule_id, category, severity, line=1, file_path="a.py"):
    return {
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "title": rule_id,
        "file_path": file_path,
        "line_start": line,
        "confidence": 0.9,
    }


def context(findings=None, **metrics):
    return ReviewContext(
        project_id=1,
        project_name="Demo",
        findings=findings or [],
        metrics=metrics,
        files_analyzed=2,
    )


def test_all_five_agents_are_registered_with_full_weight():
    orchestrator = AgentOrchestrator()
    agents = orchestrator.describe_agents()
    names = [agent["agent_name"] for agent in agents]
    assert names == [
        "Bug Detection Agent",
        "Security Analysis Agent",
        "Performance Analysis Agent",
        "Code Quality Agent",
        "Documentation Agent",
    ]
    assert abs(sum(agent["weight"] for agent in agents) - 1.0) < 1e-6


def test_each_agent_only_scores_its_own_categories():
    findings = [
        finding("BUG001", "BUG", "HIGH"),
        finding("SEC001", "SECURITY", "CRITICAL"),
        finding("PERF001", "PERFORMANCE", "MEDIUM"),
        finding("QUA003", "QUALITY", "MEDIUM"),
        finding("DOC003", "DOCUMENTATION", "MEDIUM"),
    ]
    ctx = context(findings)
    expected = {
        BugDetectionAgent: "BUG001",
        SecurityAnalysisAgent: "SEC001",
        PerformanceAnalysisAgent: "PERF001",
        CodeQualityAgent: "QUA003",
        DocumentationAgent: "DOC003",
    }
    for agent_class, rule_id in expected.items():
        result = agent_class().run(ctx)
        assert [f["rule_id"] for f in result.findings] == [rule_id]
        assert result.findings_count == 1


def test_clean_context_scores_one_hundred():
    result = SecurityAnalysisAgent().run(context())
    assert result.score == 100.0
    assert result.findings_count == 0
    assert "no" in result.summary.lower()


def test_scores_drop_with_severity():
    critical = SecurityAnalysisAgent().run(
        context([finding("SEC001", "SECURITY", "CRITICAL")])
    )
    low = SecurityAnalysisAgent().run(
        context([finding("SEC110", "SECURITY", "LOW")])
    )
    assert critical.score < low.score


def test_score_from_findings_is_bounded():
    many = [finding(f"SEC{i:03d}", "SECURITY", "CRITICAL") for i in range(50)]
    assert score_from_findings(many) == 0.0
    assert score_from_findings([]) == 100.0


def test_orchestrator_caps_score_when_critical_found():
    ctx = context([finding("SEC001", "SECURITY", "CRITICAL")])
    result = AgentOrchestrator().run(ctx)
    assert result.risk_level == "CRITICAL"
    assert result.overall_score <= 65.0
    assert result.critical_count == 1


def test_orchestrator_reports_low_risk_for_clean_project():
    result = AgentOrchestrator().run(context(comment_ratio=0.2, average_complexity=1.0))
    assert result.risk_level == "LOW"
    assert result.overall_score >= 95.0
    assert result.total_findings == 0


def test_quality_agent_penalises_complexity_and_duplication():
    ctx = context(
        [finding("QUA003", "QUALITY", "MEDIUM")],
        average_complexity=14.0,
        maintainability_index=30.0,
    )
    ctx.duplicate_groups = 3
    ctx.dependency_issues = 2
    result = CodeQualityAgent().run(ctx)
    assert result.score < 80.0


def test_documentation_agent_penalises_low_comment_ratio():
    ctx = context([], comment_ratio=0.0)
    assert DocumentationAgent().run(ctx).score < 100.0


def test_agent_result_serialises():
    result = SecurityAnalysisAgent().run(context([finding("SEC001", "SECURITY", "CRITICAL")]))
    payload = result.to_dict()
    assert payload["agent_name"] == "Security Analysis Agent"
    assert payload["critical_count"] == 1
    assert isinstance(payload["insights"], list)


def test_orchestrator_handles_failing_agent():
    class Broken(SecurityAnalysisAgent):
        def select_findings(self, context):
            raise RuntimeError("boom")

    orchestrator = AgentOrchestrator(agents=[Broken()])
    result = orchestrator.run(context([finding("SEC001", "SECURITY", "CRITICAL")]))
    assert result.agents[0].status == "FAILED"
    assert result.overall_score == 0.0


def test_orchestrator_progress_callback_is_called():
    seen = []
    AgentOrchestrator().run(context(), progress_callback=lambda name, pct: seen.append((name, pct)))
    assert seen and seen[-1][1] == 100
