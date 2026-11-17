"""Duplicate-block detection."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

_COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", ";")


@dataclass
class DuplicateInstanceResult:
    file_id: int
    relative_path: str
    line_start: int
    line_end: int
    code_hash: str


@dataclass
class DuplicateGroupResult:
    similarity: str
    line_count: int
    code_hash: str
    instances: List[DuplicateInstanceResult] = field(default_factory=list)

    @property
    def locations(self) -> List[str]:
        return [f"{i.relative_path}:{i.line_start}-{i.line_end}" for i in self.instances]


def _normalise_source(content: str) -> List[Tuple[int, str]]:
    """Returns (original line number, normalised text) for code lines only."""
    result: List[Tuple[int, str]] = []
    for index, raw in enumerate(content.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(_COMMENT_PREFIXES):
            continue
        result.append((index, " ".join(stripped.split())))
    return result


def _hash_lines(lines: Sequence[str]) -> str:
    digest = hashlib.sha256("\n".join(lines).encode("utf-8", "ignore"))
    return digest.hexdigest()


def detect_duplicates(
    files: Sequence[Tuple[int, str, str]],
    window: int = 6,
    min_lines: int = 6,
    max_groups: int = 200,
) -> List[DuplicateGroupResult]:
    """Finds duplicated blocks across ``files``.

    ``files`` is a sequence of ``(file_id, relative_path, content)``.
    ``window`` is the shingle size used to seed a match; matches are then
    extended forward as far as they stay identical.
    """
    window = max(window, 2)
    min_lines = max(min_lines, window)

    normalised: Dict[int, List[Tuple[int, str]]] = {}
    index: Dict[str, List[Tuple[int, int]]] = {}
    paths: Dict[int, str] = {}

    for file_id, path, content in files:
        paths[file_id] = path
        lines = _normalise_source(content)
        normalised[file_id] = lines
        if len(lines) < window:
            continue
        for start in range(len(lines) - window + 1):
            shingle = [text for _ln, text in lines[start : start + window]]
            index.setdefault(_hash_lines(shingle), []).append((file_id, start))

    groups: List[DuplicateGroupResult] = []
    seen: set = set()

    for code_hash, locations in index.items():
        if len(locations) < 2:
            continue
        if len({(fid, start) for fid, start in locations}) < 2:
            continue

        # Extend every location forward while the next line still matches.
        anchor_file, anchor_start = locations[0]
        anchor_lines = normalised[anchor_file]
        block = window
        while True:
            next_index = anchor_start + block
            if next_index >= len(anchor_lines):
                break
            candidate = anchor_lines[next_index][1]
            if all(
                start + block < len(normalised[fid])
                and normalised[fid][start + block][1] == candidate
                for fid, start in locations
            ):
                block += 1
            else:
                break

        if block < min_lines:
            continue

        key = (anchor_file, anchor_start, block)
        if key in seen:
            continue
        seen.add(key)

        instances = []
        for file_id, start in locations:
            lines = normalised[file_id]
            line_start = lines[start][0]
            line_end = lines[min(start + block - 1, len(lines) - 1)][0]
            instances.append(
                DuplicateInstanceResult(
                    file_id=file_id,
                    relative_path=paths.get(file_id, ""),
                    line_start=line_start,
                    line_end=line_end,
                    code_hash=code_hash,
                )
            )

        groups.append(
            DuplicateGroupResult(
                similarity="Exact",
                line_count=block,
                code_hash=code_hash,
                instances=instances,
            )
        )
        if len(groups) >= max_groups:
            break

    groups.sort(key=lambda group: (-group.line_count, group.code_hash))
    return _drop_overlapping(groups)


def _ranges(group: DuplicateGroupResult):
    return [(instance.file_id, instance.line_start, instance.line_end) for instance in group.instances]


def _overlaps(left, right) -> bool:
    if left[0] != right[0]:
        return False
    return left[1] <= right[2] and right[1] <= left[2]


def _drop_overlapping(groups: List[DuplicateGroupResult]) -> List[DuplicateGroupResult]:
    """Keeps only maximal blocks: a group fully covered by a bigger one is dropped."""
    kept: List[DuplicateGroupResult] = []
    for group in groups:
        candidate_ranges = _ranges(group)
        redundant = False
        for existing in kept:
            existing_ranges = _ranges(existing)
            if all(
                any(_overlaps(candidate, other) for other in existing_ranges)
                for candidate in candidate_ranges
            ):
                redundant = True
                break
        if not redundant:
            kept.append(group)
    return kept


def duplicate_summary(groups: Sequence[DuplicateGroupResult]) -> Dict[str, object]:
    """Aggregate numbers used by the quality agent and reports."""
    duplicated_lines = sum(group.line_count for group in groups)
    return {
        "groups": len(groups),
        "duplicated_lines": duplicated_lines,
        "largest_block": max((group.line_count for group in groups), default=0),
    }


def finding_specs_from_duplicates(
    groups: Sequence[DuplicateGroupResult],
    file_paths: Optional[Dict[int, str]] = None,
) -> List[Dict[str, object]]:
    """Converts duplicate groups into finding payloads for the persistence layer."""
    specs: List[Dict[str, object]] = []
    for group in groups:
        first = group.instances[0]
        path = (file_paths or {}).get(first.file_id, first.relative_path or f"file#{first.file_id}")
        others = ", ".join(
            f"{(file_paths or {}).get(i.file_id, i.relative_path or f'file#{i.file_id}')}:{i.line_start}"
            for i in group.instances[1:]
        )
        specs.append(
            {
                "rule_id": "DUP001",
                "category": "DUPLICATION",
                "severity": "MEDIUM" if group.line_count < 25 else "HIGH",
                "title": "Duplicated code block",
                "description": (
                    f"{group.line_count} identical lines appear in {len(group.instances)} places"
                    + (f" (also at {others})" if others else "")
                    + "."
                ),
                "suggestion": "Extract the shared block into a single reusable function/module.",
                "file_id": first.file_id,
                "file_path": path,
                "line_start": first.line_start,
                "line_end": first.line_end,
                "confidence": 0.85,
                "detector": "duplication",
            }
        )
    return specs
