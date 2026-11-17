"""Regex rule pack behaviour for non-Python sources."""
from analyzer.rules.regex_rules import analyze_with_regex


def ids(source, language="JavaScript"):
    return {finding.rule_id for finding in analyze_with_regex(source, language)}


def test_javascript_security_rules():
    source = (
        "const token = 'ghp_abcdefghijklmnopqrstuvwxyz0123';\n"
        "eval(userInput);\n"
        "el.innerHTML = data;\n"
        "document.write(html);\n"
        "child_process.exec(cmd);\n"
        "fetch('http://example.com/api');\n"
    )
    found = ids(source)
    for expected in ("SEC101", "SEC103", "SEC104", "SEC105", "SEC106", "SEC108", "SEC109"):
        assert expected in found, f"{expected} missing from {sorted(found)}"


def test_javascript_style_rules():
    source = "var total = 0;\nif (a == b) { console.log('x'); }\ndebugger;\n"
    found = ids(source)
    assert {"QUA104", "BUG101", "QUA103", "BUG102"}.issubset(found)


def test_java_stack_trace_rule():
    assert "SEC110" in ids("catch (Exception e) { e.printStackTrace(); }", "Java")


def test_todo_and_long_line_rules():
    source = "# TODO: fix this\n" + "x = 1  # " + "y" * 250 + "\n"
    found = ids(source, "Python")
    assert "QUA101" in found
    assert "QUA102" in found


def test_private_key_block_is_critical():
    source = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow==\n-----END RSA PRIVATE KEY-----\n"
    findings = analyze_with_regex(source, "Python")
    keys = [f for f in findings if f.rule_id == "SEC102"]
    assert keys and keys[0].severity == "CRITICAL"


def test_known_token_shapes_are_detected_regardless_of_variable_name():
    for literal in (
        'KEY = "sk_live_abcdef123456789"',
        'x = "AIzaSyD-abcdefghijklmnopqrstuvwxyz12"',
        'token = "sk-proj-abcdefghijklmnopqrstuvwx"',
    ):
        found = ids(literal, "Python")
        assert "SEC103" in found, f"missed {literal}"


def test_placeholder_secrets_are_ignored():
    source = 'password = "your_password_here"\napi_key = "xxxxxxxxxxxx"\n'
    found = ids(source, "JavaScript")
    assert "SEC101" not in found


def test_skip_rules_parameter():
    source = 'password = "supersecretvalue"\n'
    assert "SEC101" in ids(source)
    skipped = {f.rule_id for f in analyze_with_regex(source, "JavaScript", skip_rules=("SEC101",))}
    assert "SEC101" not in skipped


def test_python_specific_rules_do_not_fire_on_javascript():
    found = ids("print('hello')\n")
    assert "QUA006" not in found
