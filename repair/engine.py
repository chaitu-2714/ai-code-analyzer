"""Phase 6 repair engine: turn findings into concrete, reviewable patches."""
from __future__ import annotations

import difflib
import logging
import shutil
from typing import Dict, List, Optional

from core.exceptions import RepairError
from core.timeutils import utcnow
from database.models import Finding, RepairSuggestion
from repair.fixers import apply_fixer, manual_hint, supported_rule_ids

logger = logging.getLogger(__name__)


class RepairEngine:
    """Interface for automated code repair engines.

    A suggestion never touches the file on disk.  :meth:`apply` performs the
    write, keeps a ``.bak`` copy and is always an explicit user action.
    """

    def __init__(self, session_factory, provider=None, config=None):
        self.session_factory = session_factory
        self.provider = provider
        self.config = config

    # -- helpers -----------------------------------------------------------
    def _read_source(self, finding: Finding) -> str:
        path = finding.file.absolute_path if finding.file else None
        if not path:
            raise RepairError("The finding is not linked to a file on disk.")
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read()
        except OSError as error:
            raise RepairError(f"Cannot read {path}: {error}") from error

    @staticmethod
    def _diff(original: str, patched: str, path: str) -> str:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )

    # -- suggestion --------------------------------------------------------
    def suggest_for_finding(self, finding_id: int, force: bool = False) -> Dict[str, object]:
        """Creates (or returns the existing) repair suggestion for a finding."""
        with self.session_factory() as session:
            finding = session.query(Finding).filter(Finding.id == finding_id).first()
            if finding is None:
                raise RepairError(f"Finding {finding_id} does not exist.")

            existing = (
                session.query(RepairSuggestion)
                .filter(RepairSuggestion.finding_id == finding_id)
                .order_by(RepairSuggestion.id.desc())
                .first()
            )
            if existing is not None and not force:
                return _repair_to_dict(existing)

            language = finding.file.language if finding.file else "Unknown"
            original = self._read_source(finding)
            payload = {
                "rule_id": finding.rule_id,
                "severity": finding.severity,
                "title": finding.title,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "suggestion": finding.suggestion,
                "code_snippet": finding.code_snippet,
            }

            result = apply_fixer(str(finding.rule_id or ""), original, payload, language)
            if result is not None and result.can_apply:
                suggestion = RepairSuggestion(
                    finding_id=finding.id,
                    rule_id=finding.rule_id,
                    strategy=result.strategy,
                    explanation=result.explanation,
                    original_code=original,
                    patched_code=result.patched_source,
                    diff=self._diff(original, result.patched_source or "", finding.file_path),
                    confidence=result.confidence,
                    status="SUGGESTED",
                )
            else:
                suggestion = RepairSuggestion(
                    finding_id=finding.id,
                    rule_id=finding.rule_id,
                    strategy="manual",
                    explanation=manual_hint(str(finding.rule_id or ""), finding.suggestion),
                    original_code=original,
                    patched_code=None,
                    diff=None,
                    confidence=0.0,
                    status="SUGGESTED",
                )
            session.add(suggestion)
            session.commit()
            session.refresh(suggestion)
            return _repair_to_dict(suggestion)

    def suggest_for_run(self, run_id: int, limit: int = 50, severities: Optional[List[str]] = None) -> List[Dict[str, object]]:
        """Suggests repairs for the most severe open findings of an analysis run."""
        with self.session_factory() as session:
            query = session.query(Finding).filter(
                Finding.analysis_run_id == run_id, Finding.status == "OPEN"
            )
            if severities:
                query = query.filter(Finding.severity.in_([s.upper() for s in severities]))
            order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
            findings = sorted(
                query.all(), key=lambda f: (order.get(f.severity, 9), f.file_path, f.line_start or 0)
            )[:limit]
            ids = [finding.id for finding in findings]

        return [self.suggest_for_finding(finding_id) for finding_id in ids]

    # -- queries -----------------------------------------------------------
    def get(self, repair_id: int) -> Optional[Dict[str, object]]:
        with self.session_factory() as session:
            suggestion = (
                session.query(RepairSuggestion).filter(RepairSuggestion.id == repair_id).first()
            )
            return _repair_to_dict(suggestion) if suggestion else None

    def list_for_finding(self, finding_id: int) -> List[Dict[str, object]]:
        with self.session_factory() as session:
            rows = (
                session.query(RepairSuggestion)
                .filter(RepairSuggestion.finding_id == finding_id)
                .order_by(RepairSuggestion.id.desc())
                .all()
            )
            return [_repair_to_dict(row) for row in rows]

    # -- apply / reject ----------------------------------------------------
    def apply(self, repair_id: int, write_backup: bool = True) -> Dict[str, object]:
        """Writes the patch to disk (with a ``.bak`` copy) and marks it applied."""
        with self.session_factory() as session:
            suggestion = (
                session.query(RepairSuggestion).filter(RepairSuggestion.id == repair_id).first()
            )
            if suggestion is None:
                raise RepairError(f"Repair suggestion {repair_id} does not exist.")
            if not suggestion.patched_code:
                raise RepairError("This suggestion has no automatic patch; apply it manually.")
            finding = suggestion.finding
            if finding is None or finding.file is None:
                raise RepairError("The suggestion is not linked to a file.")

            path = finding.file.absolute_path
            try:
                if write_backup:
                    shutil.copyfile(path, f"{path}.bak")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(suggestion.patched_code)
            except OSError as error:
                raise RepairError(f"Could not write {path}: {error}") from error

            suggestion.status = "APPLIED"
            suggestion.applied_at = utcnow()
            session.commit()
            logger.info("Applied repair %s to %s", repair_id, path)
            return _repair_to_dict(suggestion)

    def reject(self, repair_id: int) -> bool:
        with self.session_factory() as session:
            suggestion = (
                session.query(RepairSuggestion).filter(RepairSuggestion.id == repair_id).first()
            )
            if suggestion is None:
                return False
            suggestion.status = "REJECTED"
            session.commit()
            return True

    def revert(self, repair_id: int) -> Dict[str, object]:
        """Restores the ``.bak`` copy created by :meth:`apply`."""
        with self.session_factory() as session:
            suggestion = (
                session.query(RepairSuggestion).filter(RepairSuggestion.id == repair_id).first()
            )
            if suggestion is None or suggestion.finding is None or suggestion.finding.file is None:
                raise RepairError("Repair suggestion or its file is missing.")
            path = suggestion.finding.file.absolute_path
            backup = f"{path}.bak"
            try:
                shutil.copyfile(backup, path)
            except OSError as error:
                raise RepairError(f"Could not restore {backup}: {error}") from error
            suggestion.status = "SUGGESTED"
            suggestion.applied_at = None
            session.commit()
            return _repair_to_dict(suggestion)

    # -- introspection -----------------------------------------------------
    @staticmethod
    def supported_rules() -> List[str]:
        return supported_rule_ids()


def _repair_to_dict(suggestion: RepairSuggestion) -> Dict[str, object]:
    return {
        "repair_id": suggestion.id,
        "finding_id": suggestion.finding_id,
        "rule_id": suggestion.rule_id,
        "strategy": suggestion.strategy,
        "explanation": suggestion.explanation,
        "diff": suggestion.diff,
        "patched_code": suggestion.patched_code,
        "confidence": suggestion.confidence,
        "status": suggestion.status,
        "applied_at": suggestion.applied_at.isoformat() if suggestion.applied_at else None,
        "can_apply": bool(suggestion.patched_code),
    }
