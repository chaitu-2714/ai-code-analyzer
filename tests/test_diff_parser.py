"""Phase 9: unified diff parsing and diff-scoped reviews."""
from analyzer.diff_parser import changed_line_map, diff_summary, filter_findings_to_diff, parse_unified_diff

DIFF = """diff --git a/app/x.py b/app/x.py
--- a/app/x.py
+++ b/app/x.py
@@ -1,4 +1,5 @@
 import os
+import sys
 def f():
-    pass
+    return 1
     return 2
"""


def test_parse_unified_diff():
    files = parse_unified_diff(DIFF)
    assert len(files) == 1
    assert files[0].path == "app/x.py"
    assert files[0].added_lines == [2, 4]
    assert files[0].removed_lines == [3]
    assert files[0].hunks[0].new_start == 1


def test_changed_line_map_and_summary():
    assert changed_line_map(DIFF) == {"app/x.py": [2, 4]}
    summary = diff_summary(DIFF)
    assert summary["files_changed"] == 1
    assert summary["added_lines"] == 2


def test_filter_findings_to_diff():
    findings = [
        {"file_path": "app/x.py", "line_start": 2, "rule_id": "BUG004"},
        {"file_path": "app/x.py", "line_start": 40, "rule_id": "QUA001"},
        {"file_path": "other.py", "line_start": 2, "rule_id": "SEC001"},
    ]
    kept = filter_findings_to_diff(findings, DIFF)
    assert [item["rule_id"] for item in kept] == ["BUG004"]


def test_empty_diff_keeps_everything():
    findings = [{"file_path": "a.py", "line_start": 1}]
    assert filter_findings_to_diff(findings, "") == findings


def test_context_lines_widens_the_window():
    findings = [{"file_path": "app/x.py", "line_start": 6, "rule_id": "X"}]
    assert filter_findings_to_diff(findings, DIFF, context_lines=0) == []
    assert filter_findings_to_diff(findings, DIFF, context_lines=3)
