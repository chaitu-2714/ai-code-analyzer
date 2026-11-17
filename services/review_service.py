"""Phase 5 service: run the multi-agent review and persist agent scores."""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Dict, List, Optional

from agents.base import ReviewContext
from agents.orchestrator import AgentOrchestrator, ReviewResult
from core.exceptions import AnalysisError
from core.timeutils import utcnow
from database.models import AgentReview, AnalysisRun, DuplicateGroup, Finding, Project, ReviewSession
from llm.factory import create_provider
from services.analysis_service import AnalysisService

logger = logging.getLogger(__name__)


class ReviewService:
    """Turns an analysis run into a persisted, scored multi-agent review."""

    def __init__(self, session_factory, config=None, provider=None, analysis_service=None,
                 orchestrator: Optional[AgentOrchestrator] = None):
        self.session_factory = session_factory
        self.config = config
        self.provider = provider or create_provider(config)
        self.analysis_service = analysis_service or AnalysisService(session_factory, config)
        self.orchestrator = orchestrator or AgentOrchestrator(provider=self.provider)

    # -- context building --------------------------------------------------
    def build_context(
        self,
        project_id: int,
        analysis_run_id: int,
        diff_text: Optional[str] = None,
    ) -> ReviewContext:
        with self.session_factory() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project is None:
                raise AnalysisError(f"Project {project_id} does not exist.")

            findings = (
                session.query(Finding)
                .filter(Finding.analysis_run_id == analysis_run_id)
                .all()
            )
            payload = [
                {
                    "id": row.id,
                    "rule_id": row.rule_id,
                    "category": row.category,
                    "severity": row.severity,
                    "title": row.title,
                    "description": row.description,
                    "file_path": row.file_path,
                    "line_start": row.line_start,
                    "line_end": row.line_end,
                    "code_snippet": row.code_snippet,
                    "suggestion": row.suggestion,
                    "confidence": row.confidence,
                }
                for row in findings
            ]
            if diff_text:
                from analyzer.diff_parser import filter_findings_to_diff

                payload = filter_findings_to_diff(payload, diff_text)

            duplicate_groups = (
                session.query(DuplicateGroup)
                .filter(DuplicateGroup.analysis_run_id == analysis_run_id)
                .count()
            )
            run = session.query(AnalysisRun).filter(AnalysisRun.id == analysis_run_id).first()
            files_analyzed = run.files_analyzed if run else 0

        metrics = self.analysis_service.metrics(project_id, run_id=analysis_run_id)
        dependency_issues = sum(
            1
            for dependency in self.analysis_service.dependencies(analysis_run_id)
            if dependency["is_missing"] or dependency["is_circular"]
        )
        return ReviewContext(
            project_id=project_id,
            project_name=project.name,
            findings=payload,
            metrics=metrics,
            files_analyzed=files_analyzed,
            duplicate_groups=duplicate_groups,
            dependency_issues=dependency_issues,
        )

    # -- main entry point --------------------------------------------------
    def review_project(
        self,
        project_id: int,
        analysis_run_id: Optional[int] = None,
        run_analysis_if_missing: bool = True,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        provider_mode: Optional[str] = None,
        diff_text: Optional[str] = None,
    ) -> Dict[str, object]:
        """Runs (or reuses) an analysis run, then reviews it with every agent."""
        started = time.perf_counter()
        if provider_mode:
            self.provider = create_provider(self.config, provider_mode)
            self.orchestrator = AgentOrchestrator(provider=self.provider)

        if analysis_run_id is None:
            latest = self.analysis_service.latest_run(project_id)
            if latest and latest["status"] == "COMPLETED":
                analysis_run_id = int(latest["run_id"])
            elif run_analysis_if_missing:
                if progress_callback:
                    progress_callback("Analysing project", 5)
                summary = self.analysis_service.run(project_id)
                analysis_run_id = int(summary["run_id"])
            else:
                raise AnalysisError("No completed analysis run; run the analysis first.")

        context = self.build_context(project_id, analysis_run_id, diff_text=diff_text)
        if progress_callback:
            progress_callback("Reviewing", 15)

        result = self.orchestrator.run(
            context,
            progress_callback=(
                (lambda name, pct: progress_callback(name, 15 + int(pct * 0.8)))
                if progress_callback
                else None
            ),
        )
        session_id = self._persist_review(project_id, analysis_run_id, result)
        if progress_callback:
            progress_callback("Completed", 100)

        payload = result.to_dict()
        payload.update(
            {
                "session_id": session_id,
                "analysis_run_id": analysis_run_id,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        )
        logger.info(
            "Review session %s: score %.1f (%s) from %s findings",
            session_id,
            result.overall_score,
            result.risk_level,
            result.total_findings,
        )
        return payload

    def _persist_review(self, project_id: int, analysis_run_id: int, result: ReviewResult) -> int:
        with self.session_factory() as session:
            review = ReviewSession(
                project_id=project_id,
                analysis_run_id=analysis_run_id,
                status="completed",
                overall_score=result.overall_score,
                risk_level=result.risk_level,
                summary=result.summary,
                provider=result.provider,
                created_at=utcnow(),
                completed_at=utcnow(),
            )
            session.add(review)
            session.flush()

            for agent in result.agents:
                session.add(
                    AgentReview(
                        review_session_id=review.id,
                        agent_name=agent.agent_name,
                        score=agent.score,
                        weight=agent.weight,
                        status=agent.status,
                        summary=agent.summary,
                        insights=json.dumps(agent.insights),
                        findings_count=agent.findings_count,
                        critical_count=agent.critical_count,
                        high_count=agent.high_count,
                        llm_used=bool(agent.llm_used),
                        duration_seconds=agent.duration_seconds,
                    )
                )
            session.commit()
            return review.id

    # -- queries -----------------------------------------------------------
    def get_review(self, session_id: int) -> Optional[Dict[str, object]]:
        with self.session_factory() as session:
            review = session.query(ReviewSession).filter(ReviewSession.id == session_id).first()
            if review is None:
                return None
            agents = (
                session.query(AgentReview)
                .filter(AgentReview.review_session_id == session_id)
                .all()
            )
            return {
                "session_id": review.id,
                "project_id": review.project_id,
                "analysis_run_id": review.analysis_run_id,
                "status": review.status,
                "overall_score": review.overall_score,
                "risk_level": review.risk_level,
                "summary": review.summary,
                "provider": review.provider,
                "created_at": review.created_at.isoformat() if review.created_at else None,
                "completed_at": review.completed_at.isoformat() if review.completed_at else None,
                "agents": [
                    {
                        "agent_name": agent.agent_name,
                        "score": agent.score,
                        "weight": agent.weight,
                        "status": agent.status,
                        "summary": agent.summary,
                        "insights": _load_json_list(agent.insights),
                        "findings_count": agent.findings_count,
                        "critical_count": agent.critical_count,
                        "high_count": agent.high_count,
                        "llm_used": bool(agent.llm_used),
                        "duration_seconds": agent.duration_seconds,
                    }
                    for agent in agents
                ],
            }

    def list_reviews(self, project_id: int, limit: int = 20) -> List[Dict[str, object]]:
        with self.session_factory() as session:
            reviews = (
                session.query(ReviewSession)
                .filter(ReviewSession.project_id == project_id)
                .order_by(ReviewSession.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "session_id": review.id,
                    "status": review.status,
                    "overall_score": review.overall_score,
                    "risk_level": review.risk_level,
                    "created_at": review.created_at.isoformat() if review.created_at else None,
                }
                for review in reviews
            ]

    def latest_review(self, project_id: int) -> Optional[Dict[str, object]]:
        reviews = self.list_reviews(project_id, limit=1)
        return self.get_review(int(reviews[0]["session_id"])) if reviews else None

    def quality_trend(self, project_id: int, limit: int = 20) -> List[Dict[str, object]]:
        """Score history for the trend chart, oldest first."""
        with self.session_factory() as session:
            reviews = (
                session.query(ReviewSession)
                .filter(
                    ReviewSession.project_id == project_id,
                    ReviewSession.overall_score.isnot(None),
                )
                .order_by(ReviewSession.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "session_id": review.id,
                    "overall_score": review.overall_score,
                    "risk_level": review.risk_level,
                    "created_at": review.created_at.isoformat() if review.created_at else None,
                }
                for review in reversed(reviews)
            ]

    def agent_leaderboard(self, project_id: int) -> List[Dict[str, object]]:
        """Average score per agent across every review of a project."""
        with self.session_factory() as session:
            reviews = (
                session.query(ReviewSession.id)
                .filter(ReviewSession.project_id == project_id)
                .all()
            )
            ids = [row[0] for row in reviews]
            if not ids:
                return []
            rows = (
                session.query(AgentReview)
                .filter(AgentReview.review_session_id.in_(ids))
                .all()
            )
            buckets: Dict[str, List[float]] = {}
            for row in rows:
                if row.score is None:
                    continue
                buckets.setdefault(row.agent_name, []).append(float(row.score))
            return sorted(
                (
                    {"agent_name": name, "average_score": round(sum(values) / len(values), 1), "reviews": len(values)}
                    for name, values in buckets.items()
                ),
                key=lambda item: item["average_score"],
            )


def _load_json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return [str(item) for item in value] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
