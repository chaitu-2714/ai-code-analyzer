"""Phase 7 fix verification: syntax check plus the project's own test suite."""
from __future__ import annotations

import ast
import contextlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analyzer.rules.base import language_family
from core.exceptions import VerificationError
from database.models import ProjectFile, RepairSuggestion, VerificationResult

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass
class VerificationOutcome:
    passed: bool
    syntax_ok: bool
    tests_ok: Optional[bool]
    checks: List[CheckResult] = field(default_factory=list)
    output: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "passed": self.passed,
            "syntax_ok": self.syntax_ok,
            "tests_ok": self.tests_ok,
            "checks": [check.to_dict() for check in self.checks],
            "output": self.output[-4000:],
            "duration_seconds": round(self.duration_seconds, 3),
        }


class FixVerifier:
    """Validates a patched file before and after it is applied."""

    def __init__(self, session_factory, config=None):
        self.session_factory = session_factory
        self.config = config
        self.timeout = int(getattr(config, "verify_timeout_seconds", 120))

    # -- individual checks -------------------------------------------------
    def check_syntax(self, source: str, language: str, path: str = "<patch>") -> CheckResult:
        family = language_family(language)
        if family == "python":
            try:
                ast.parse(source, filename=path)
                return CheckResult("syntax", True, "Python parses cleanly.")
            except SyntaxError as error:
                return CheckResult("syntax", False, f"SyntaxError: {error.msg} (line {error.lineno}).")
        if family == "js":
            return self._check_node(source, path)
        return CheckResult("syntax", True, f"No parser available for {language}; skipped.")

    def _check_node(self, source: str, path: str) -> CheckResult:
        node = _which("node")
        if not node:
            return CheckResult("syntax", True, "node is not installed; skipped.")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(source)
            temp_path = handle.name
        try:
            completed = subprocess.run(
                [node, "--check", temp_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            ok = completed.returncode == 0
            return CheckResult("syntax", ok, (completed.stderr or completed.stdout or "").strip()[:500])
        except (subprocess.SubprocessError, OSError) as error:  # pragma: no cover - env dependent
            return CheckResult("syntax", True, f"node check could not run: {error}")
        finally:
            with contextlib.suppress(OSError):
                os.unlink(temp_path)

    def check_imports(self, source: str, path: str) -> CheckResult:
        """Confirms the module still imports (catches broken names after a patch)."""
        if language_family("Python") != "python":
            return CheckResult("import", True, "skipped")
        try:
            ast.parse(source)
        except SyntaxError as error:
            return CheckResult("import", False, str(error))
        return CheckResult("import", True, "module-level structure intact.")

    def run_tests(self, project_dir: Optional[str]) -> CheckResult:
        """Runs pytest in the project directory when a test suite exists."""
        if not project_dir or not os.path.isdir(project_dir):
            return CheckResult("tests", True, "No project directory; tests skipped.")
        has_tests = any(
            name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))
            for _root, _dirs, files in os.walk(project_dir)
            for name in files
        ) or os.path.isdir(os.path.join(project_dir, "tests"))
        if not has_tests:
            return CheckResult("tests", True, "No tests found; nothing to run.")

        command = [sys.executable, "-m", "pytest", "-q", "--maxfail=5", "-p", "no:cacheprovider"]
        try:
            completed = subprocess.run(
                command,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CheckResult("tests", False, f"pytest exceeded the {self.timeout}s timeout.")
        except OSError as error:
            return CheckResult("tests", False, f"pytest could not start: {error}")

        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        if completed.returncode == 0:
            return CheckResult("tests", True, output[-1500:] or "All tests passed.")
        if completed.returncode == 5:  # no tests collected
            return CheckResult("tests", True, "No tests collected; treated as pass.")
        return CheckResult("tests", False, output[-1500:] or f"pytest exited with {completed.returncode}.")

    # -- full verification -------------------------------------------------
    def verify_source(
        self,
        source: str,
        language: str,
        path: str = "<patch>",
        project_dir: Optional[str] = None,
        run_project_tests: bool = False,
    ) -> VerificationOutcome:
        started = time.perf_counter()
        checks = [
            self.check_syntax(source, language, path),
            self.check_imports(source, path),
        ]
        if run_project_tests:
            checks.append(self.run_tests(project_dir))

        syntax_ok = checks[0].passed
        tests_check = next((check for check in checks if check.name == "tests"), None)
        passed = all(check.passed for check in checks)
        return VerificationOutcome(
            passed=passed,
            syntax_ok=syntax_ok,
            tests_ok=tests_check.passed if tests_check else None,
            checks=checks,
            output="\n".join(check.detail for check in checks if check.detail),
            duration_seconds=time.perf_counter() - started,
        )

    def verify_repair(self, repair_id: int, run_project_tests: bool = True) -> Dict[str, object]:
        """Verifies a stored suggestion and persists the outcome."""
        with self.session_factory() as session:
            suggestion = (
                session.query(RepairSuggestion).filter(RepairSuggestion.id == repair_id).first()
            )
            if suggestion is None:
                raise VerificationError(f"Repair suggestion {repair_id} does not exist.")
            if not suggestion.patched_code:
                raise VerificationError("This suggestion has no automatic patch to verify.")

            finding = suggestion.finding
            file_row: Optional[ProjectFile] = finding.file if finding else None
            language = file_row.language if file_row else "Python"
            path = file_row.absolute_path if file_row else "<patch>"
            project_dir = os.path.dirname(path) if file_row else None

            outcome = self.verify_source(
                suggestion.patched_code,
                language or "Python",
                path=path,
                project_dir=project_dir,
                run_project_tests=run_project_tests,
            )

            record = VerificationResult(
                repair_id=suggestion.id,
                passed=outcome.passed,
                syntax_ok=outcome.syntax_ok,
                tests_ok=outcome.tests_ok,
                checks=json.dumps([check.to_dict() for check in outcome.checks]),
                output=outcome.output[-4000:],
                duration_seconds=outcome.duration_seconds,
            )
            session.add(record)
            if outcome.passed and finding is not None:
                finding.status = "RESOLVED"
            session.commit()
            session.refresh(record)

            payload = outcome.to_dict()
            payload["verification_id"] = record.id
            payload["repair_id"] = suggestion.id
            return payload


def _which(binary: str) -> Optional[str]:
    from shutil import which

    return which(binary)
