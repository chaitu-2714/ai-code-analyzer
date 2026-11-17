"""Phase 8 report generation: markdown, HTML and JSON quality reports."""
from __future__ import annotations

import html
import json
import logging
import os
from typing import Dict, List, Optional

from analyzer.rules.base import SEVERITY_ORDER, get_rule
from core.exceptions import ApplicationError
from core.timeutils import utcnow
from database.models import Finding, Project, ReviewSession

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Interface for generating review summaries."""

    def __init__(self, session_factory, review_service=None, analysis_service=None):
        self.session_factory = session_factory
        self.review_service = review_service
        self.analysis_service = analysis_service

    # -- data collection ---------------------------------------------------
    def _collect(self, session_id: int) -> Dict[str, object]:
        with self.session_factory() as session:
            review = (
                session.query(ReviewSession).filter(ReviewSession.id == session_id).first()
            )
            if review is None:
                raise ApplicationError(f"Review session {session_id} does not exist.")
            project = session.query(Project).filter(Project.id == review.project_id).first()
            findings = (
                session.query(Finding)
                .filter(Finding.analysis_run_id == review.analysis_run_id)
                .all()
                if review.analysis_run_id
                else []
            )
            finding_payload = [
                {
                    "rule_id": row.rule_id,
                    "category": row.category,
                    "severity": row.severity,
                    "title": row.title,
                    "description": row.description,
                    "file_path": row.file_path,
                    "line_start": row.line_start,
                    "suggestion": row.suggestion,
                    "code_snippet": row.code_snippet,
                    "status": row.status,
                }
                for row in findings
            ]

        agents: List[Dict[str, object]] = []
        if self.review_service is not None:
            detail = self.review_service.get_review(session_id)
            agents = detail.get("agents", []) if detail else []
        else:
            with self.session_factory() as session:
                from database.models import AgentReview

                rows = (
                    session.query(AgentReview)
                    .filter(AgentReview.review_session_id == session_id)
                    .all()
                )
                agents = [
                    {
                        "agent_name": row.agent_name,
                        "score": row.score,
                        "weight": row.weight,
                        "summary": row.summary,
                        "insights": json.loads(row.insights) if row.insights else [],
                        "findings_count": row.findings_count,
                        "critical_count": row.critical_count,
                        "high_count": row.high_count,
                        "llm_used": bool(row.llm_used),
                    }
                    for row in rows
                ]

        finding_payload.sort(
            key=lambda item: (
                SEVERITY_ORDER.index(item["severity"]) if item["severity"] in SEVERITY_ORDER else 99,
                item["file_path"],
                item["line_start"] or 0,
            )
        )
        return {
            "session_id": review.id,
            "project_id": review.project_id,
            "project_name": project.name if project else "Unknown project",
            "status": review.status,
            "overall_score": review.overall_score,
            "risk_level": review.risk_level,
            "summary": review.summary,
            "provider": review.provider,
            "created_at": review.created_at.isoformat() if review.created_at else None,
            "agents": agents,
            "findings": finding_payload,
        }

    @staticmethod
    def _severity_counts(findings: List[Dict[str, object]]) -> Dict[str, int]:
        counts = {name: 0 for name in SEVERITY_ORDER}
        for finding in findings:
            severity = str(finding.get("severity"))
            counts[severity] = counts.get(severity, 0) + 1
        return counts

    # -- public API --------------------------------------------------------
    def generate_report(self, session_id: int, format: str = "markdown") -> str:
        """Renders a report for ``session_id`` (markdown, html or json)."""
        data = self._collect(session_id)
        fmt = (format or "markdown").lower()
        if fmt in ("md", "markdown"):
            return self._render_markdown(data)
        if fmt in ("html", "htm"):
            return self._render_html(data)
        if fmt == "json":
            return json.dumps(data, indent=2, default=str)
        raise ApplicationError(f"Unsupported report format '{format}'. Use markdown, html or json.")

    def export(self, session_id: int, path: str, format: Optional[str] = None) -> str:
        """Writes the report to ``path`` and returns the path."""
        fmt = format or os.path.splitext(path)[1].lstrip(".") or "markdown"
        content = self.generate_report(session_id, fmt)
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        logger.info("Report for session %s written to %s", session_id, path)
        return path

    def project_summary(self, project_id: int, limit: int = 10) -> Dict[str, object]:
        """Compact quality intelligence payload used by the dashboard."""
        with self.session_factory() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            reviews = (
                session.query(ReviewSession)
                .filter(ReviewSession.project_id == project_id)
                .order_by(ReviewSession.id.desc())
                .limit(limit)
                .all()
            )
            findings = session.query(Finding).filter(Finding.project_id == project_id).all()
            return {
                "project_id": project_id,
                "project_name": project.name if project else None,
                "reviews": len(reviews),
                "latest_score": reviews[0].overall_score if reviews else None,
                "latest_risk": reviews[0].risk_level if reviews else None,
                "trend": [review.overall_score for review in reversed(reviews) if review.overall_score is not None],
                "severity_counts": self._severity_counts(
                    [{"severity": row.severity} for row in findings]
                ),
                "open_findings": sum(1 for row in findings if row.status == "OPEN"),
            }

    # -- renderers ---------------------------------------------------------
    def _render_markdown(self, data: Dict[str, object]) -> str:
        findings: List[Dict[str, object]] = data["findings"]  # type: ignore[assignment]
        counts = self._severity_counts(findings)
        lines = [
            f"# Code Review Report - {data['project_name']}",
            "",
            f"- **Session:** {data['session_id']}",
            f"- **Generated:** {utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"- **Overall score:** {data['overall_score']}/100",
            f"- **Risk level:** {data['risk_level']}",
            f"- **Analysis provider:** {data['provider']}",
            "",
            "## Summary",
            "",
            str(data["summary"] or "No summary available."),
            "",
            "## Agent scores",
            "",
            "| Agent | Score | Weight | Findings | Critical | High |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for agent in data["agents"]:  # type: ignore[union-attr]
            lines.append(
                "| {name} | {score} | {weight} | {count} | {crit} | {high} |".format(
                    name=agent.get("agent_name"),
                    score=agent.get("score"),
                    weight=agent.get("weight"),
                    count=agent.get("findings_count"),
                    crit=agent.get("critical_count"),
                    high=agent.get("high_count"),
                )
            )

        lines.extend(["", "## Findings by severity", ""])
        for severity in SEVERITY_ORDER:
            lines.append(f"- {severity}: {counts.get(severity, 0)}")

        lines.extend(["", "## Top findings", ""])
        for finding in findings[:40]:
            rule = get_rule(str(finding.get("rule_id") or ""))
            title = rule.title if rule else finding.get("title")
            lines.append(
                f"### [{finding.get('severity')}] {title} ({finding.get('rule_id')})"
            )
            lines.append(
                f"- Location: `{finding.get('file_path')}:{finding.get('line_start')}`"
            )
            if finding.get("code_snippet"):
                lines.append(f"- Code: `{finding['code_snippet']}`")
            if finding.get("suggestion"):
                lines.append(f"- Fix: {finding['suggestion']}")
            lines.append("")

        lines.extend(
            [
                "---",
                "",
                "_Generated by the AI Code Review & Automated Repair Platform._",
                "",
            ]
        )
        return "\n".join(lines)

    def _render_html(self, data: Dict[str, object]) -> str:
        findings: List[Dict[str, object]] = data["findings"]  # type: ignore[assignment]
        counts = self._severity_counts(findings)
        colors = {
            "CRITICAL": "#e5484d",
            "HIGH": "#f76b15",
            "MEDIUM": "#f5a524",
            "LOW": "#3b82f6",
            "INFO": "#8b8b9c",
        }
        rows = "\n".join(
            f"<tr><td>{html.escape(str(agent.get('agent_name')))}</td>"
            f"<td>{agent.get('score')}</td><td>{agent.get('findings_count')}</td>"
            f"<td>{agent.get('critical_count')}</td></tr>"
            for agent in data["agents"]  # type: ignore[union-attr]
        )
        cards = "\n".join(
            f'<div class="card"><span class="dot" style="background:{colors.get(severity, "#666")}"></span>'
            f"<strong>{severity}</strong><span>{counts.get(severity, 0)}</span></div>"
            for severity in SEVERITY_ORDER
        )
        finding_rows = "\n".join(
            f"<tr><td><span class='sev' style='background:{colors.get(str(f.get('severity')), '#666')}'>"
            f"{html.escape(str(f.get('severity')))}</span></td>"
            f"<td>{html.escape(str(f.get('rule_id')))}</td>"
            f"<td>{html.escape(str(f.get('title')))}</td>"
            f"<td><code>{html.escape(str(f.get('file_path')))}:{f.get('line_start')}</code></td></tr>"
            for f in findings[:60]
        )
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Code Review - {html.escape(str(data['project_name']))}</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1117;color:#e6e6ef;margin:0;padding:40px}}
h1{{margin:0 0 6px;font-size:28px}} .muted{{color:#8b8b9c}}
.cards{{display:flex;gap:12px;margin:24px 0;flex-wrap:wrap}}
.card{{background:#171a23;border:1px solid #242835;border-radius:10px;padding:14px 18px;display:flex;gap:10px;align-items:center}}
.dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
table{{width:100%;border-collapse:collapse;margin-top:16px;font-size:14px}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #242835}}
th{{color:#8b8b9c;font-weight:600}}
.sev{{padding:2px 8px;border-radius:6px;font-size:11px;color:#fff}}
code{{color:#a5b4fc}}
</style></head><body>
<h1>{html.escape(str(data['project_name']))}</h1>
<p class="muted">Session {data['session_id']} &middot; {html.escape(str(data['created_at']))} &middot; provider {html.escape(str(data['provider']))}</p>
<h2>Overall score: {data['overall_score']}/100 &mdash; risk {data['risk_level']}</h2>
<p>{html.escape(str(data['summary'] or ''))}</p>
<div class="cards">{cards}</div>
<h2>Agents</h2>
<table><thead><tr><th>Agent</th><th>Score</th><th>Findings</th><th>Critical</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Findings</h2>
<table><thead><tr><th>Severity</th><th>Rule</th><th>Title</th><th>Location</th></tr></thead>
<tbody>{finding_rows}</tbody></table>
</body></html>"""
