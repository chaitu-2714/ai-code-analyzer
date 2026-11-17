"""Phase 6: template fixers and the repair engine."""
import ast
import os

import pytest

from core.exceptions import RepairError
from repair.engine import RepairEngine
from repair.fixers import apply_fixer, manual_hint, supported_rule_ids
from services.analysis_service import AnalysisService


def patch(rule_id, source, line=1):
    result = apply_fixer(rule_id, source, {"line_start": line, "rule_id": rule_id}, "Python")
    assert result is not None, f"{rule_id} produced no patch"
    return result


def test_supported_rules_are_documented():
    rules = supported_rule_ids()
    assert "BUG001" in rules and "SEC006" in rules
    assert len(rules) >= 15


def test_bare_except_patch_is_valid_python():
    result = patch("BUG001", "def f():\n    try:\n        pass\n    except:\n        pass\n", line=4)
    assert "except Exception:" in result.patched_source
    ast.parse(result.patched_source)


def test_none_comparison_patch():
    result = patch("BUG003", "def f(x):\n    return x == None\n", line=2)
    assert "is None" in result.patched_source
    ast.parse(result.patched_source)


def test_mutable_default_patch_inserts_guard():
    result = patch("BUG002", "def f(x, cache=[]):\n    return cache\n")
    assert "cache=None" in result.patched_source
    assert "if cache is None:" in result.patched_source
    ast.parse(result.patched_source)


def test_eval_patch_adds_ast_import():
    result = patch("SEC001", "def f(p):\n    return eval(p)\n", line=2)
    assert "ast.literal_eval" in result.patched_source
    assert "import ast" in result.patched_source
    ast.parse(result.patched_source)


def test_yaml_and_verify_patches():
    yaml_result = patch("SEC005", "import yaml\ndef f(d):\n    return yaml.load(d)\n", line=3)
    assert "yaml.safe_load" in yaml_result.patched_source

    verify_result = patch(
        "SEC010",
        "import requests\ndef f(u):\n    return requests.get(u, verify=False)\n",
        line=3,
    )
    assert "verify=False" not in verify_result.patched_source


def test_hardcoded_secret_patch_uses_env():
    result = patch("SEC006", 'API_KEY = "sk_live_123456789"\n')
    assert 'os.getenv("API_KEY"' in result.patched_source
    ast.parse(result.patched_source)


def test_unused_import_removal():
    result = patch("BUG004", "import json\n\nprint(1)\n")
    assert "import json" not in result.patched_source


def test_docstring_patches():
    module = patch("DOC001", "def f():\n    return 1\n")
    assert module.patched_source.startswith('"""')

    function = patch("DOC003", "def f():\n    return 1\n")
    assert '"""' in function.patched_source

    klass = patch("DOC002", "class A:\n    pass\n")
    assert '"""' in klass.patched_source


def test_javascript_fixers():
    loose = apply_fixer("BUG101", "if (a == b) {}\n", {"line_start": 1}, "JavaScript")
    assert "===" in loose.patched_source

    var = apply_fixer("QUA104", "var total = 1;\n", {"line_start": 1}, "JavaScript")
    assert "const total" in var.patched_source


def test_fixers_are_language_gated():
    from repair.fixers import apply_fixer, fixer_families

    assert fixer_families("SEC001") == ("python",)
    assert fixer_families("BUG101") == ("js",)
    # A Python rule must not patch Ruby, and a JS rule must not patch Python.
    assert apply_fixer("SEC001", "x = eval(y)\n", {"line_start": 1}, "Ruby") is None
    assert apply_fixer("BUG101", "if (a == b) {}\n", {"line_start": 1}, "Python") is None
    assert apply_fixer("BUG101", "if (a == b) {}\n", {"line_start": 1}, "JavaScript") is not None


def test_manual_hint_is_used_when_no_fixer_exists():
    hint = manual_hint("QUA001")
    assert hint and "extract" in hint.lower()
    assert apply_fixer("QUA001", "def f(): pass\n", {"line_start": 1}, "Python") is None
    assert manual_hint("UNKNOWN", "do it by hand") == "do it by hand"


def test_engine_creates_manual_suggestion_for_unsupported_rule(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    engine = RepairEngine(session_factory)
    suggestions = engine.suggest_for_run(1, limit=40)
    assert suggestions
    manual = [item for item in suggestions if item["strategy"] == "manual"]
    assert manual and manual[0]["can_apply"] is False


def test_apply_and_revert_keeps_backup(session_factory, indexed_project, tmp_path):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    engine = RepairEngine(session_factory)
    suggestions = [item for item in engine.suggest_for_run(1, limit=40) if item["can_apply"]]
    assert suggestions

    applied = engine.apply(int(suggestions[0]["repair_id"]))
    assert applied["status"] == "APPLIED"

    finding_id = int(suggestions[0]["finding_id"])
    with session_factory() as session:
        from database.models import Finding

        finding = session.query(Finding).filter(Finding.id == finding_id).first()
        path = finding.file.absolute_path
    assert os.path.exists(f"{path}.bak")
    assert os.path.exists(path)

    engine.revert(int(suggestions[0]["repair_id"]))
    with open(f"{path}.bak", encoding="utf-8") as handle:
        original = handle.read()
    with open(path, encoding="utf-8") as handle:
        restored = handle.read()
    assert original == restored


def test_apply_without_patch_raises(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    engine = RepairEngine(session_factory)
    manual = [
        item for item in engine.suggest_for_run(1, limit=40) if not item["can_apply"]
    ]
    assert manual
    with pytest.raises(RepairError):
        engine.apply(int(manual[0]["repair_id"]))


def test_suggest_is_idempotent_unless_forced(session_factory, indexed_project):
    service = AnalysisService(session_factory)
    service.run(indexed_project.id)
    engine = RepairEngine(session_factory)
    first = engine.suggest_for_run(1, limit=3)
    second = engine.suggest_for_run(1, limit=3)
    assert [item["repair_id"] for item in first] == [item["repair_id"] for item in second]
