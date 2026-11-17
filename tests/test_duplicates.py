"""Duplicate block detection."""
from analyzer.duplicates import (
    detect_duplicates,
    duplicate_summary,
    finding_specs_from_duplicates,
)

BLOCK = """def compute(values):
    total = 0
    count = 0
    for value in values:
        if value is not None:
            total += value
            count += 1
    return total / count if count else 0
"""


def test_identical_blocks_are_grouped():
    files = [(1, "a.py", BLOCK), (2, "b.py", BLOCK)]
    groups = detect_duplicates(files, window=6)
    assert len(groups) == 1
    assert len(groups[0].instances) == 2
    assert groups[0].line_count >= 6
    assert groups[0].instances[0].relative_path == "a.py"


def test_short_overlap_is_not_reported():
    files = [
        (1, "a.py", "x = 1\ny = 2\nz = 3\n"),
        (2, "b.py", "x = 1\ny = 2\nz = 3\n"),
    ]
    assert detect_duplicates(files, window=6, min_lines=6) == []


def test_different_code_is_not_grouped():
    files = [(1, "a.py", BLOCK), (2, "b.py", BLOCK.replace("total", "amount"))]
    assert detect_duplicates(files, window=6) == []


def test_summary_and_finding_payloads():
    files = [(1, "a.py", BLOCK), (2, "b.py", BLOCK)]
    groups = detect_duplicates(files, window=6)
    summary = duplicate_summary(groups)
    assert summary["groups"] == 1
    assert summary["largest_block"] >= 6

    specs = finding_specs_from_duplicates(groups, {1: "a.py", 2: "b.py"})
    assert specs and specs[0]["rule_id"] == "DUP001"
    assert specs[0]["category"] == "DUPLICATION"
    assert specs[0]["file_path"] == "a.py"
