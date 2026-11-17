"""Phase 7: fix verification checks."""

from services.analysis_service import AnalysisService
from verification.verifier import FixVerifier


def test_syntax_check_accepts_valid_python(session_factory):
    outcome = FixVerifier(session_factory).verify_source("def f():\n    return 1\n", "Python")
    assert outcome.passed
    assert outcome.syntax_ok
    assert outcome.checks[0].name == "syntax"


def test_syntax_check_rejects_broken_python(session_factory):
    outcome = FixVerifier(session_factory).verify_source("def f(:\n", "Python")
    assert not outcome.passed
    assert not outcome.syntax_ok
    assert "SyntaxError" in outcome.checks[0].detail


def test_tests_are_skipped_without_suite(session_factory, tmp_path):
    (tmp_path / "module.py").write_text("x = 1\n")
    verifier = FixVerifier(session_factory)
    check = verifier.run_tests(str(tmp_path))
    assert check.passed
    assert "No tests" in check.detail


def test_tests_run_when_present(session_factory, tmp_path):
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    verifier = FixVerifier(session_factory)
    check = verifier.run_tests(str(tmp_path))
    assert check.passed


def test_failing_tests_are_reported(session_factory, tmp_path):
    (tmp_path / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    verifier = FixVerifier(session_factory)
    check = verifier.run_tests(str(tmp_path))
    assert not check.passed


def test_verify_repair_persists_result(session_factory, indexed_project):
    from repair.engine import RepairEngine

    AnalysisService(session_factory).run(indexed_project.id)
    repairs = RepairEngine(session_factory).suggest_for_run(1, limit=40)
    auto = [item for item in repairs if item["can_apply"]]
    assert auto

    verifier = FixVerifier(session_factory)
    outcome = verifier.verify_repair(int(auto[0]["repair_id"]), run_project_tests=False)
    assert outcome["syntax_ok"] is True
    assert outcome["verification_id"]


def test_verify_missing_repair_raises(session_factory):
    import pytest

    from core.exceptions import VerificationError

    with pytest.raises(VerificationError):
        FixVerifier(session_factory).verify_repair(99999)
