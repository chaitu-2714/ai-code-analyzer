"""Rule pack behaviour on Python sources."""
import ast

from analyzer.rules.python_rules import analyze_python


def rule_ids(source):
    return {finding.rule_id for finding in analyze_python(source)}


def test_detects_core_bug_and_security_rules():
    source = (
        'import os\n'
        'API_KEY = "sk_live_1234567890abcdef"\n'
        'def f(payload, cache=[]):\n'
        '    result = eval(payload)\n'
        '    try:\n'
        '        os.system(payload)\n'
        '    except:\n'
        '        pass\n'
        '    if payload == None:\n'
        '        return []\n'
        '    return result\n'
    )
    ids = rule_ids(source)
    for expected in ("SEC006", "SEC001", "SEC003", "BUG001", "BUG002", "BUG003"):
        assert expected in ids, f"{expected} not detected in {sorted(ids)}"


def test_detects_quality_and_documentation_rules():
    body = "\n".join(f"    value_{i} = {i}" for i in range(60))
    source = (
        "def long_function(a, b, c, d, e, f):\n"
        f"{body}\n"
        "    return a\n"
    )
    ids = rule_ids(source)
    assert "QUA001" in ids       # function too long
    assert "QUA002" in ids       # too many parameters
    assert "DOC001" in ids       # module docstring
    assert "DOC003" in ids       # function docstring
    assert "QUA007" in ids       # missing type hints


def test_detects_unused_import_and_wildcard():
    ids = rule_ids("import json\nfrom os.path import *\n")
    assert "BUG004" in ids
    assert "QUA005" in ids


def test_detects_nested_loops_and_string_concat():
    source = (
        "def f(matrix):\n"
        "    out = ''\n"
        "    for row in matrix:\n"
        "        for cell in row:\n"
        "            for digit in cell:\n"
        "                out += str(digit)\n"
        "    return out\n"
    )
    ids = rule_ids(source)
    assert "PERF004" in ids
    assert "PERF002" in ids


def test_open_inside_with_is_not_flagged():
    source = (
        '"""Doc."""\n'
        "def read(path):\n"
        '    """Read a file."""\n'
        "    with open(path) as handle:\n"
        "        return handle.read()\n"
    )
    ids = rule_ids(source)
    assert "PERF001" not in ids


def test_sql_formatting_and_yaml_rules():
    source = (
        "import yaml\n"
        "def q(cursor, name):\n"
        "    cursor.execute(\"SELECT * FROM t WHERE n = '%s'\" % name)\n"
        "    return yaml.load('a: 1')\n"
    )
    ids = rule_ids(source)
    assert "SEC008" in ids
    assert "SEC005" in ids


def test_clean_module_produces_no_high_severity_findings():
    clean = '''"""Clean module."""


def add(left: int, right: int) -> int:
    """Add two numbers."""
    return left + right
'''
    findings = analyze_python(clean)
    severe = [f for f in findings if f.severity in ("CRITICAL", "HIGH")]
    assert severe == []


def test_syntax_error_raises():
    import pytest

    with pytest.raises(SyntaxError):
        analyze_python("def broken(:\n    pass\n")


def test_every_finding_has_line_and_rule():
    findings = analyze_python("import os\nprint('x')\n")
    assert findings
    for finding in findings:
        assert finding.rule_id
        assert finding.line_start is None or finding.line_start >= 1
        assert ast is not None
