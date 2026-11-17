"""Compiler page backend: snippet review, compile check and code rewrite."""
import pytest

from core.exceptions import ApplicationError
from services.playground_service import PlaygroundService, detect_language

BUGGY = '''import os

API_KEY = "sk_live_1234567890abcdef"

def run(payload, cache=[]):
    result = eval(payload)
    cache.append(result)
    if payload == None:
        return []
    return result
'''


@pytest.fixture
def playground():
    return PlaygroundService(config=None)


def test_detect_language_from_code_and_filename():
    assert detect_language("def f():\n    return 1\n") == "Python"
    assert detect_language("const a = 1;\nfunction f() {}\n") == "JavaScript"
    assert detect_language("public class A { }") == "Java"
    assert detect_language("x = 1", filename="app.js") == "JavaScript"
    assert detect_language("package main\nfunc main() {}\n") == "Go"


def test_compile_check_accepts_and_rejects_python(playground):
    assert playground.compile_check("x = 1\n", "Python")["ok"]
    broken = playground.compile_check("def f(:\n", "Python")
    assert not broken["ok"]
    assert "SyntaxError" in broken["message"]


def test_review_snippet_returns_five_agents(playground):
    review = playground.review_snippet(BUGGY)
    assert review["language"] == "Python"
    assert len(review["agents"]) == 5
    assert review["findings"]
    assert review["compile"]["ok"] is True
    assert review["risk_level"] == "CRITICAL"
    rule_ids = {finding["rule_id"] for finding in review["findings"]}
    assert {"SEC006", "SEC001", "BUG002", "BUG003"}.issubset(rule_ids)
    for agent in review["agents"]:
        assert agent["insights"]


def test_review_rejects_empty_input(playground):
    with pytest.raises(ApplicationError):
        playground.review_snippet("   \n  ")


def test_rewrite_fixes_code_and_improves_score(playground):
    result = playground.rewrite_snippet(BUGGY)
    assert result["changed"] is True
    assert result["compile"]["ok"] is True
    assert result["after"]["overall_score"] > result["before"]["overall_score"]
    assert result["after"]["findings"] < result["before"]["findings"]

    code = result["rewritten_code"]
    assert "ast.literal_eval" in code
    assert "is None" in code
    assert "cache=None" in code
    assert 'sk_live_1234567890abcdef' not in code
    assert result["diff"].startswith("--- a/")

    applied_rules = {item["rule_id"] for item in result["applied"]}
    assert {"SEC001", "SEC006", "BUG002", "BUG003"}.issubset(applied_rules)


def test_rewrite_removes_bare_key_token(playground):
    result = playground.rewrite_snippet('KEY = "sk_live_abcdef1234567890"\n')
    assert "sk_live_abcdef1234567890" not in result["rewritten_code"]
    assert 'os.getenv("KEY"' in result["rewritten_code"]


def test_rewrite_is_stable_when_nothing_to_fix(playground):
    clean = '''"""Tidy module."""


def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right
'''
    result = playground.rewrite_snippet(clean)
    assert result["compile"]["ok"] is True
    assert result["after"]["findings"] == 0
    assert result["rewritten_code"].strip() == clean.strip()


def test_rewrite_handles_syntax_error_input(playground):
    result = playground.rewrite_snippet("def broken(:\n    pass\n")
    assert result["compile"]["ok"] is False
    assert result["notes"], "a note should explain that rewriting stopped"


def test_rewrite_javascript(playground):
    code = "var total = 0;\nif (a == b) { total = 1; }\n"
    result = playground.rewrite_snippet(code)
    assert result["language"] == "JavaScript"
    assert "const total" in result["rewritten_code"]
    assert "===" in result["rewritten_code"]


def test_rewrite_never_returns_invalid_python(playground):
    result = playground.rewrite_snippet(BUGGY)
    compile(result["rewritten_code"], "snippet.py", "exec")


def test_rewritten_module_actually_runs(playground):
    """The rewritten file must not reference modules it no longer imports."""
    code = (
        "import os\nimport yaml\n\n"
        'API_KEY = "sk_live_abcdef1234567890"\n\n'
        "def load(path, cache=[]):\n"
        "    f = open(path)\n"
        "    data = yaml.load(f.read())\n"
        "    cache.append(data)\n"
        "    return data\n\n"
        "def run(payload):\n"
        "    return eval(payload)\n\n"
        "class Thing:\n"
        "    def method(self):\n"
        "        try:\n"
        '            return os.system("ls")\n'
        "        except:\n"
        "            pass\n"
    )
    result = playground.rewrite_snippet(code)
    namespace = {}
    exec(compile(result["rewritten_code"], "rewritten.py", "exec"), namespace)
    assert namespace["API_KEY"] == ""            # env lookup, not the secret
    assert callable(namespace["run"])
    assert "os" in namespace and "logging" in namespace


def test_logger_is_defined_after_the_imports(playground):
    code = "import json\n\ndef f(x):\n    print(x)\n    return x\n"
    code_out = playground.rewrite_snippet(code)["rewritten_code"]
    logger_line = code_out.index("logger = logging.getLogger")
    import_line = code_out.index("import logging")
    assert import_line < logger_line
    namespace = {}
    exec(compile(code_out, "r.py", "exec"), namespace)


def test_unused_import_is_kept_when_a_fix_needs_it(playground):
    """`os` starts unused-ish, then os.system is rewritten; os.getenv must survive."""
    code = 'import os\n\nKEY = "sk_live_abcdef1234567890"\n\ndef f(c):\n    return os.system(c)\n'
    result = playground.rewrite_snippet(code)
    out = result["rewritten_code"]
    assert "os.getenv" in out
    assert "import os" in out, out
    namespace = {}
    exec(compile(out, "r.py", "exec"), namespace)


def test_large_file_is_rewritten_in_few_sweeps(playground):
    code = "\n\n".join(
        f"def fn_{i}(x, cache=[]):\n    if x == None:\n        return eval(str(x))"
        for i in range(40)
    )
    result = playground.rewrite_snippet(code)
    assert len(result["applied"]) >= 100
    assert max(item["pass"] for item in result["applied"]) <= 5
    assert result["compile"]["ok"] is True
    assert result["after"]["overall_score"] > result["before"]["overall_score"]


def test_python_fixers_never_touch_other_languages(playground):
    """A Ruby/PHP/Java snippet must never receive a Python patch."""
    samples = {
        "Ruby": 'PASSWORD = "hunter2secret"\n\ndef f(x)\n  eval(x)\nend\n',
        "PHP": '<?php\n$password = "hunter2secret";\n',
        "Java": 'class A {\n  String password = "hunter2secret";\n}\n',
        "Shell": '#!/bin/bash\npassword="hunter2secret"\n',
        "Go": 'package main\n\nconst password = "hunter2secret"\n',
    }
    for language, code in samples.items():
        result = playground.rewrite_snippet(code, language)
        assert result["applied"] == [], f"{language} received {result['applied']}"
        assert result["rewritten_code"] == code
        assert result["before"]["findings"] > 0, f"{language} found no findings at all"


def test_javascript_secret_becomes_process_env(playground):
    result = playground.rewrite_snippet('const password = "hunter2secret";\n', "JavaScript")
    assert "process.env.password" in result["rewritten_code"]
    assert "os.getenv" not in result["rewritten_code"]


def test_typescript_check_is_not_a_false_failure(playground):
    code = 'interface U { name: string; }\nexport function f(u: U): string { return u.name; }\n'
    result = playground.compile_check(code, "TypeScript", "a.ts")
    assert result["ok"] is True, result["message"]
    assert "skipped" in result["message"].lower() or "clean" in result["message"].lower()


def test_llm_flag_degrades_gracefully(playground):
    result = playground.rewrite_snippet("import os\nprint('x')\n", use_llm=True)
    assert result["compile"]["ok"] is True
    assert result["llm_used"] is False  # no reachable provider in tests


def test_max_passes_limits_sweeps(playground):
    single = playground.rewrite_snippet(BUGGY, max_passes=1)
    full = playground.rewrite_snippet(BUGGY)
    assert {item["pass"] for item in single["applied"]} == {1}
    assert len(single["applied"]) <= len(full["applied"])
    assert single["compile"]["ok"] is True
