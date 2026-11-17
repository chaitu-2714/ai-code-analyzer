"""Phase 9: git-aware diff parsing so a review can target only changed lines."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

_HUNK = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<old_len>\d+))? \+(?P<new>\d+)(?:,(?P<new_len>\d+))? @@")


@dataclass
class DiffHunk:
    old_start: int
    old_length: int
    new_start: int
    new_length: int


@dataclass
class DiffFile:
    path: str
    added_lines: List[int] = field(default_factory=list)
    removed_lines: List[int] = field(default_factory=list)
    hunks: List[DiffHunk] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "added_lines": len(self.added_lines),
            "removed_lines": len(self.removed_lines),
            "hunks": len(self.hunks),
        }


def parse_unified_diff(text: str) -> List[DiffFile]:
    """Parses ``git diff`` / ``git show`` output into per-file change maps."""
    files: List[DiffFile] = []
    current: Optional[DiffFile] = None
    old_line = new_line = 0

    for raw in (text or "").splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target in ("/dev/null", ""):
                current = None
                continue
            path = target.removeprefix("b/")
            current = DiffFile(path=path)
            files.append(current)
            continue
        if raw.startswith("--- "):
            continue
        match = _HUNK.match(raw)
        if match:
            old_line = int(match.group("old"))
            new_line = int(match.group("new"))
            if current is not None:
                current.hunks.append(
                    DiffHunk(
                        old_start=old_line,
                        old_length=int(match.group("old_len") or 1),
                        new_start=new_line,
                        new_length=int(match.group("new_len") or 1),
                    )
                )
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            current.added_lines.append(new_line)
            new_line += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            current.removed_lines.append(old_line)
            old_line += 1
        elif raw.startswith(" "):
            old_line += 1
            new_line += 1

    return files


def changed_line_map(diff_text: str) -> Dict[str, List[int]]:
    """``{path: [added line numbers]}`` for every changed file."""
    return {item.path: sorted(set(item.added_lines)) for item in parse_unified_diff(diff_text)}


def filter_findings_to_diff(
    findings: Sequence[Dict[str, object]],
    diff_text: str,
    context_lines: int = 0,
) -> List[Dict[str, object]]:
    """Keeps findings whose line falls inside an added hunk (or the whole file)."""
    changes = changed_line_map(diff_text)
    if not changes:
        return list(findings)

    filtered: List[Dict[str, object]] = []
    for finding in findings:
        path = str(finding.get("file_path") or "")
        lines = changes.get(path)
        if lines is None:
            # File may appear with a different prefix; try a suffix match.
            lines = next(
                (value for key, value in changes.items() if key.endswith(path) or path.endswith(key)),
                None,
            )
        if lines is None:
            continue
        line = finding.get("line_start")
        if not isinstance(line, int):
            filtered.append(finding)
            continue
        if any(abs(line - changed) <= context_lines for changed in lines):
            filtered.append(finding)
    return filtered


def diff_summary(diff_text: str) -> Dict[str, object]:
    files = parse_unified_diff(diff_text)
    return {
        "files_changed": len(files),
        "added_lines": sum(len(item.added_lines) for item in files),
        "removed_lines": sum(len(item.removed_lines) for item in files),
        "files": [item.to_dict() for item in files],
    }
