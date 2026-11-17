"""Static analysis engine over single files and whole projects."""
from analyzer.engine import FileInput, StaticAnalysisEngine
from analyzer.rules import all_rules


def test_rule_registry_is_populated():
    rules = all_rules()
    assert len(rules) >= 50
    ids = {rule.id for rule in rules}
    assert {"BUG001", "SEC001", "PERF001", "QUA001", "DOC001", "DUP001", "DEP001", "SYN001"}.issubset(ids)


def test_python_file_analysis_reports_findings_and_metrics():
    engine = StaticAnalysisEngine()
    source = "import os\n\ndef f(x=[]):\n    return eval(x)\n"
    analysis = engine.analyze_file(FileInput(1, "a.py", "/tmp/a.py", "Python", source))
    ids = {finding.rule_id for finding in analysis.findings}
    assert {"SEC001", "BUG002"}.issubset(ids)
    assert analysis.metrics["function_count"] == 1
    for finding in analysis.findings:
        if finding.line_start:
            assert finding.code_snippet is not None


def test_syntax_error_is_reported_as_finding():
    engine = StaticAnalysisEngine()
    analysis = engine.analyze_file(FileInput(1, "broken.py", "", "Python", "def broken(:\n    pass\n"))
    assert analysis.parse_error
    assert analysis.findings[0].rule_id == "SYN001"
    assert analysis.findings[0].severity == "CRITICAL"


def test_unknown_languages_are_skipped():
    engine = StaticAnalysisEngine()
    analysis = engine.analyze_file(FileInput(1, "notes.md", "", "Markdown", "# TODO: nothing\n"))
    assert analysis.findings == []


def test_javascript_file_uses_regex_rules():
    engine = StaticAnalysisEngine()
    source = "const password = 'supersecret123';\neval(input);\n"
    analysis = engine.analyze_file(FileInput(1, "app.js", "", "JavaScript", source))
    ids = {finding.rule_id for finding in analysis.findings}
    assert {"SEC101", "SEC104"}.issubset(ids)


def test_project_analysis_aggregates_and_detects_duplicates():
    block = "".join(f"value_{i} = {i}\n" for i in range(8))
    files = [
        FileInput(1, "a.py", "", "Python", "import os\n" + block),
        FileInput(2, "b.py", "", "Python", "import json\n" + block),
    ]
    engine = StaticAnalysisEngine()
    analysis = engine.analyze_project(files)
    assert len(analysis.files) == 2
    assert analysis.duplicate_groups
    summary = engine.stats(analysis)
    assert summary["files_analyzed"] == 2
    assert summary["duplicates"]["groups"] >= 1
    assert set(summary["severity_counts"]) == {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}


def test_engine_never_raises_on_hostile_input():
    engine = StaticAnalysisEngine()
    payloads = [
        FileInput(1, "a.py", "", "Python", "\x00\x01binary"),
        FileInput(2, "b.js", "", "JavaScript", "((((("),
        FileInput(3, "c.go", "", "Go", "package main\nfunc main(){}\n"),
    ]
    analysis = engine.analyze_project(payloads)
    assert len(analysis.files) == 3


def test_extra_findings_include_project_level_rules():
    block = "".join(f"line_{i} = {i}\n" for i in range(8))
    files = [FileInput(1, "a.py", "", "Python", block), FileInput(2, "b.py", "", "Python", block)]
    engine = StaticAnalysisEngine()
    analysis = engine.analyze_project(files)
    extra = engine.extra_findings(analysis)
    assert any(item["rule_id"] == "DUP001" for item in extra)
