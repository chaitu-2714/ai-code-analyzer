"""Phase 3 service: run static analysis over a project and persist the results."""
from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional, Sequence

from analyzer.engine import FileInput, ProjectAnalysis, StaticAnalysisEngine
from analyzer.rules.base import SEVERITY_ORDER
from core.exceptions import AnalysisError
from core.timeutils import utcnow
from database.models import (
    AnalysisRun,
    CodeMetric,
    Dependency,
    DuplicateGroup,
    DuplicateInstance,
    Finding,
    Project,
    ProjectFile,
)

logger = logging.getLogger(__name__)


class AnalysisService:
    """Owns the lifecycle of an :class:`AnalysisRun`."""

    def __init__(self, session_factory, config=None, engine: Optional[StaticAnalysisEngine] = None):
        self.session_factory = session_factory
        self.config = config
        self.engine = engine or StaticAnalysisEngine(
            long_function_threshold=getattr(config, "long_function_threshold", 50),
            complexity_threshold=getattr(config, "complexity_threshold", 10),
            duplicate_window=getattr(config, "duplicate_window_lines", 6),
            max_file_bytes=getattr(config, "max_file_size_bytes", 1_000_000),
        )

    # -- reading the workspace --------------------------------------------
    def _load_files(self, session, project_id: int) -> List[FileInput]:
        rows: Sequence[ProjectFile] = (
            session.query(ProjectFile)
            .filter(ProjectFile.project_id == project_id)
            .order_by(ProjectFile.relative_path)
            .all()
        )
        files: List[FileInput] = []
        for row in rows:
            try:
                with open(row.absolute_path, "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read()
            except OSError as error:
                logger.warning("Cannot read %s: %s", row.absolute_path, error)
                continue
            files.append(
                FileInput(
                    file_id=row.id,
                    relative_path=row.relative_path,
                    absolute_path=row.absolute_path,
                    language=row.language or "Unknown",
                    content=content,
                )
            )
        return files

    # -- main entry point --------------------------------------------------
    def run(
        self,
        project_id: int,
        progress_callback: Optional[Callable[[int], None]] = None,
        check_installed_packages: bool = True,
        detect_duplicate_blocks: bool = True,
    ) -> Dict[str, object]:
        """Analyses every indexed file of ``project_id`` and stores the findings."""
        started = time.perf_counter()
        with self.session_factory() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project is None:
                raise AnalysisError(f"Project {project_id} does not exist.")

            run = AnalysisRun(
                project_id=project_id,
                status="RUNNING",
                started_at=utcnow(),
            )
            session.add(run)
            session.commit()
            run_id = run.id

            try:
                files = self._load_files(session, project_id)
                if not files:
                    raise AnalysisError(
                        "No readable source files found. Import and index a project first."
                    )
                if progress_callback:
                    progress_callback(10)

                analysis = self.engine.analyze_project(
                    files,
                    detect_duplicate_blocks=detect_duplicate_blocks,
                    resolve_dependencies=True,
                    check_installed_packages=check_installed_packages,
                )
                if progress_callback:
                    progress_callback(70)

                finding_count = self._persist_findings(session, run_id, project_id, analysis)
                self._persist_metrics(session, run_id, analysis)
                self._persist_duplicates(session, run_id, analysis)
                self._persist_dependencies(session, run_id, analysis)

                duration = time.perf_counter() - started
                run.status = "COMPLETED"
                run.completed_at = utcnow()
                run.files_analyzed = len(analysis.files)
                run.findings_count = finding_count
                run.duration_seconds = round(duration, 3)
                session.commit()
                if progress_callback:
                    progress_callback(100)

                summary = self.engine.stats(analysis)
                summary.update(
                    {
                        "run_id": run_id,
                        "project_id": project_id,
                        "status": "COMPLETED",
                        "duration_seconds": round(duration, 3),
                    }
                )
                logger.info(
                    "Analysis run %s completed: %s files, %s findings in %.2fs",
                    run_id,
                    len(analysis.files),
                    finding_count,
                    duration,
                )
                return summary
            except Exception as error:
                session.rollback()
                run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
                if run is not None:
                    run.status = "FAILED"
                    run.completed_at = utcnow()
                    run.error_message = str(error)[:2000]
                    run.duration_seconds = round(time.perf_counter() - started, 3)
                    session.commit()
                logger.exception("Analysis run %s failed", run_id)
                if isinstance(error, AnalysisError):
                    raise
                raise AnalysisError(f"Analysis failed: {error}") from error

    # -- persistence helpers ----------------------------------------------
    def _persist_findings(self, session, run_id: int, project_id: int, analysis: ProjectAnalysis) -> int:
        count = 0
        for file_analysis in analysis.files:
            path = file_analysis.file.relative_path
            for finding in file_analysis.findings:
                session.add(
                    Finding(
                        analysis_run_id=run_id,
                        project_id=project_id,
                        file_id=file_analysis.file.file_id,
                        rule_id=finding.rule_id,
                        category=finding.category,
                        severity=finding.severity,
                        title=finding.title[:200],
                        description=finding.description,
                        file_path=path,
                        line_start=finding.line_start,
                        line_end=finding.line_end,
                        column_start=finding.column_start,
                        column_end=finding.column_end,
                        code_snippet=finding.code_snippet,
                        suggestion=finding.suggestion,
                        confidence=finding.confidence,
                        detector=finding.detector,
                        status="OPEN",
                    )
                )
                count += 1

        for payload in self.engine.extra_findings(analysis):
            session.add(
                Finding(
                    analysis_run_id=run_id,
                    project_id=project_id,
                    file_id=int(payload["file_id"]),
                    rule_id=str(payload.get("rule_id")),
                    category=str(payload.get("category")),
                    severity=str(payload.get("severity")),
                    title=str(payload.get("title"))[:200],
                    description=str(payload.get("description") or ""),
                    file_path=str(payload.get("file_path") or ""),
                    line_start=payload.get("line_start"),
                    line_end=payload.get("line_end"),
                    suggestion=str(payload.get("suggestion") or ""),
                    confidence=float(payload.get("confidence") or 0.7),
                    detector=str(payload.get("detector") or "engine"),
                    status="OPEN",
                )
            )
            count += 1
        session.flush()
        return count

    def _persist_metrics(self, session, run_id: int, analysis: ProjectAnalysis) -> None:
        for file_analysis in analysis.files:
            metrics = file_analysis.metrics or {}
            session.add(
                CodeMetric(
                    analysis_run_id=run_id,
                    file_id=file_analysis.file.file_id,
                    lines_of_code=int(metrics.get("lines_of_code") or 0),
                    blank_lines=int(metrics.get("blank_lines") or 0),
                    comment_lines=int(metrics.get("comment_lines") or 0),
                    function_count=int(metrics.get("function_count") or 0),
                    class_count=int(metrics.get("class_count") or 0),
                    average_complexity=float(metrics.get("average_complexity") or 0.0),
                    max_complexity=int(metrics.get("max_complexity") or 0),
                    maintainability_index=(
                        float(metrics["maintainability_index"])
                        if metrics.get("maintainability_index") is not None
                        else None
                    ),
                )
            )
        session.flush()

    def _persist_duplicates(self, session, run_id: int, analysis: ProjectAnalysis) -> None:
        for group in analysis.duplicate_groups:
            db_group = DuplicateGroup(
                analysis_run_id=run_id,
                similarity=group.similarity,
                line_count=group.line_count,
            )
            session.add(db_group)
            session.flush()
            for instance in group.instances:
                session.add(
                    DuplicateInstance(
                        group_id=db_group.id,
                        file_id=instance.file_id,
                        line_start=instance.line_start,
                        line_end=instance.line_end,
                        code_hash=instance.code_hash,
                    )
                )
        session.flush()

    def _persist_dependencies(self, session, run_id: int, analysis: ProjectAnalysis) -> None:
        for dependency in analysis.dependencies:
            session.add(
                Dependency(
                    analysis_run_id=run_id,
                    file_id=dependency.file_id,
                    imported_module=dependency.imported_module[:200],
                    import_type=dependency.import_type,
                    is_missing=bool(dependency.is_missing),
                    is_circular=bool(dependency.is_circular),
                )
            )
        session.flush()

    # -- queries -----------------------------------------------------------
    def latest_run(self, project_id: int) -> Optional[Dict[str, object]]:
        with self.session_factory() as session:
            run = (
                session.query(AnalysisRun)
                .filter(AnalysisRun.project_id == project_id)
                .order_by(AnalysisRun.id.desc())
                .first()
            )
            return _run_to_dict(run) if run else None

    def get_run(self, run_id: int) -> Optional[Dict[str, object]]:
        with self.session_factory() as session:
            run = session.query(AnalysisRun).filter(AnalysisRun.id == run_id).first()
            return _run_to_dict(run) if run else None

    def list_runs(self, project_id: int, limit: int = 20) -> List[Dict[str, object]]:
        with self.session_factory() as session:
            runs = (
                session.query(AnalysisRun)
                .filter(AnalysisRun.project_id == project_id)
                .order_by(AnalysisRun.id.desc())
                .limit(limit)
                .all()
            )
            return [_run_to_dict(run) for run in runs]

    def findings(
        self,
        project_id: int,
        run_id: Optional[int] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        file_path: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 2000,
    ) -> List[Dict[str, object]]:
        with self.session_factory() as session:
            if run_id is None:
                latest = (
                    session.query(AnalysisRun)
                    .filter(AnalysisRun.project_id == project_id, AnalysisRun.status == "COMPLETED")
                    .order_by(AnalysisRun.id.desc())
                    .first()
                )
                if latest is None:
                    return []
                run_id = latest.id

            query = session.query(Finding).filter(
                Finding.project_id == project_id, Finding.analysis_run_id == run_id
            )
            if severity:
                query = query.filter(Finding.severity == severity.upper())
            if category:
                query = query.filter(Finding.category == category.upper())
            if file_path:
                query = query.filter(Finding.file_path == file_path)
            if status:
                query = query.filter(Finding.status == status.upper())

            rows = query.limit(limit).all()
            return sorted(
                (_finding_to_dict(row) for row in rows),
                key=lambda item: (
                    SEVERITY_ORDER.index(item["severity"]) if item["severity"] in SEVERITY_ORDER else 99,
                    item["file_path"],
                    item["line_start"] or 0,
                ),
            )

    def severity_counts(self, project_id: int, run_id: Optional[int] = None) -> Dict[str, int]:
        counts = {name: 0 for name in SEVERITY_ORDER}
        for finding in self.findings(project_id, run_id=run_id):
            counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
        return counts

    def metrics(self, project_id: int, run_id: Optional[int] = None) -> Dict[str, object]:
        with self.session_factory() as session:
            if run_id is None:
                latest = (
                    session.query(AnalysisRun)
                    .filter(AnalysisRun.project_id == project_id, AnalysisRun.status == "COMPLETED")
                    .order_by(AnalysisRun.id.desc())
                    .first()
                )
                if latest is None:
                    return {}
                run_id = latest.id
            rows = session.query(CodeMetric).filter(CodeMetric.analysis_run_id == run_id).all()
            if not rows:
                return {}
            loc = sum(row.lines_of_code or 0 for row in rows)
            comments = sum(row.comment_lines or 0 for row in rows)
            mis = [row.maintainability_index for row in rows if row.maintainability_index is not None]
            complexities = [row.average_complexity or 0.0 for row in rows]
            return {
                "files": len(rows),
                "lines_of_code": loc,
                "function_count": sum(row.function_count or 0 for row in rows),
                "class_count": sum(row.class_count or 0 for row in rows),
                "comment_lines": comments,
                "comment_ratio": round(comments / loc, 3) if loc else 0.0,
                "average_complexity": round(sum(complexities) / len(complexities), 2) if complexities else 0.0,
                "max_complexity": max((row.max_complexity or 0 for row in rows), default=0),
                "maintainability_index": round(sum(mis) / len(mis), 2) if mis else None,
            }

    def duplicates(self, run_id: int) -> List[Dict[str, object]]:
        with self.session_factory() as session:
            groups = (
                session.query(DuplicateGroup)
                .filter(DuplicateGroup.analysis_run_id == run_id)
                .all()
            )
            payload = []
            for group in groups:
                payload.append(
                    {
                        "group_id": group.id,
                        "similarity": group.similarity,
                        "line_count": group.line_count,
                        "instances": [
                            {
                                "file_id": instance.file_id,
                                "line_start": instance.line_start,
                                "line_end": instance.line_end,
                            }
                            for instance in group.instances
                        ],
                    }
                )
            return payload

    def dependencies(self, run_id: int, only_problems: bool = True) -> List[Dict[str, object]]:
        with self.session_factory() as session:
            query = session.query(Dependency).filter(Dependency.analysis_run_id == run_id)
            if only_problems:
                query = query.filter(
                    (Dependency.is_missing.is_(True)) | (Dependency.is_circular.is_(True))
                )
            return [
                {
                    "file_id": row.file_id,
                    "module": row.imported_module,
                    "import_type": row.import_type,
                    "is_missing": bool(row.is_missing),
                    "is_circular": bool(row.is_circular),
                }
                for row in query.all()
            ]

    def project_metrics(self, project_id: int) -> Dict[str, object]:
        """Aggregated metrics used by the dashboard."""
        with self.session_factory() as session:
            files = session.query(ProjectFile).filter(ProjectFile.project_id == project_id).count()
            runs = (
                session.query(AnalysisRun)
                .filter(AnalysisRun.project_id == project_id)
                .count()
            )
            findings = (
                session.query(Finding).filter(Finding.project_id == project_id).count()
            )
            return {"files": files, "runs": runs, "findings": findings}


def _run_to_dict(run: AnalysisRun) -> Dict[str, object]:
    return {
        "run_id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "files_analyzed": run.files_analyzed,
        "findings_count": run.findings_count,
        "duration_seconds": run.duration_seconds,
        "error_message": run.error_message,
    }


def _finding_to_dict(finding: Finding) -> Dict[str, object]:
    return {
        "id": finding.id,
        "analysis_run_id": finding.analysis_run_id,
        "rule_id": finding.rule_id,
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "description": finding.description,
        "file_path": finding.file_path,
        "line_start": finding.line_start,
        "line_end": finding.line_end,
        "column_start": finding.column_start,
        "column_end": finding.column_end,
        "code_snippet": finding.code_snippet,
        "suggestion": finding.suggestion,
        "confidence": finding.confidence,
        "detector": finding.detector,
        "status": finding.status,
    }
