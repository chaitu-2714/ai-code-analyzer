"""Static analysis engine: runs every rule pack over a file or a whole project."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from analyzer.complexity import generic_metrics, python_metrics
from analyzer.dependencies import (
    DependencyResult,
    analyze_dependencies,
    dependency_findings,
)
from analyzer.duplicates import (
    DuplicateGroupResult,
    detect_duplicates,
    duplicate_summary,
    finding_specs_from_duplicates,
)
from analyzer.rules.base import (
    SEVERITY_RANK,
    Category,
    Rule,
    RuleFinding,
    Severity,
    finding_from_rule,
    language_family,
    register,
)
from analyzer.rules.python_rules import analyze_python
from analyzer.rules.regex_rules import analyze_with_regex

logger = logging.getLogger(__name__)

SYNTAX_RULE = register(
    Rule(
        id="SYN001",
        title="File cannot be parsed",
        category=Category.SYNTAX,
        severity=Severity.CRITICAL,
        description="The source file contains a syntax error and cannot be parsed.",
        suggestion="Fix the syntax error; nothing else in this file can be analysed reliably.",
        languages=("any",),
        detector="parser",
    )
)

#: Languages that are not analysed at all (data / markup only).
SKIPPED_LANGUAGES = {"Markdown", "Text", "JSON", "XML", "YAML", "TOML", "Unknown", "Batch"}


@dataclass
class FileInput:
    """Everything the engine needs to analyse one file."""

    file_id: int
    relative_path: str
    absolute_path: str = ""
    language: str = "Python"
    content: str = ""


@dataclass
class FileAnalysis:
    file: FileInput
    findings: List[RuleFinding] = field(default_factory=list)
    metrics: Dict[str, object] = field(default_factory=dict)
    parse_error: Optional[str] = None


@dataclass
class ProjectAnalysis:
    files: List[FileAnalysis] = field(default_factory=list)
    duplicate_groups: List[DuplicateGroupResult] = field(default_factory=list)
    dependencies: List[DependencyResult] = field(default_factory=list)

    @property
    def findings(self) -> List[RuleFinding]:
        collected: List[RuleFinding] = []
        for analysis in self.files:
            collected.extend(analysis.findings)
        return collected

    @property
    def metrics(self) -> Dict[str, object]:
        return _aggregate_metrics(self.files)

    def findings_by_severity(self) -> Dict[str, int]:
        counts = {name: 0 for name in SEVERITY_RANK}
        for finding in self.findings:
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def summary(self) -> Dict[str, object]:
        counts = self.findings_by_severity()
        return {
            "files_analyzed": len(self.files),
            "findings": len(self.findings),
            "severity_counts": counts,
            "duplicate_groups": len(self.duplicate_groups),
            "dependencies": len(self.dependencies),
            "metrics": self.metrics,
        }


def _aggregate_metrics(files: Sequence[FileAnalysis]) -> Dict[str, object]:
    loc = sum(int(f.metrics.get("lines_of_code", 0)) for f in files)
    functions = sum(int(f.metrics.get("function_count", 0)) for f in files)
    classes = sum(int(f.metrics.get("class_count", 0)) for f in files)
    comments = sum(int(f.metrics.get("comment_lines", 0)) for f in files)
    complexities = [float(f.metrics.get("average_complexity", 1.0)) for f in files if f.metrics]
    mis = [float(f.metrics["maintainability_index"]) for f in files if f.metrics.get("maintainability_index") is not None]
    return {
        "lines_of_code": loc,
        "function_count": functions,
        "class_count": classes,
        "comment_lines": comments,
        "average_complexity": round(sum(complexities) / len(complexities), 2) if complexities else 0.0,
        "max_complexity": max((int(f.metrics.get("max_complexity", 0)) for f in files), default=0),
        "maintainability_index": round(sum(mis) / len(mis), 2) if mis else None,
        "comment_ratio": round(comments / loc, 3) if loc else 0.0,
    }


class StaticAnalysisEngine:
    """Deterministic, offline static analysis over a set of files."""

    def __init__(
        self,
        long_function_threshold: int = 50,
        complexity_threshold: int = 10,
        max_parameters: int = 5,
        nesting_threshold: int = 4,
        duplicate_window: int = 6,
        max_file_bytes: int = 1_000_000,
    ):
        self.long_function_threshold = long_function_threshold
        self.complexity_threshold = complexity_threshold
        self.max_parameters = max_parameters
        self.nesting_threshold = nesting_threshold
        self.duplicate_window = duplicate_window
        self.max_file_bytes = max_file_bytes

    # -- single file -------------------------------------------------------
    def analyze_file(self, file_input: FileInput) -> FileAnalysis:
        analysis = FileAnalysis(file=file_input)
        language = file_input.language
        content = file_input.content or ""

        if language in SKIPPED_LANGUAGES or len(content.encode("utf-8", "ignore")) > self.max_file_bytes:
            analysis.metrics = generic_metrics(content, language)
            return analysis

        family = language_family(language)
        lines = content.splitlines()

        if family == "python":
            try:
                findings = analyze_python(
                    content,
                    path=file_input.relative_path,
                    long_function_threshold=self.long_function_threshold,
                    complexity_threshold=self.complexity_threshold,
                    max_parameters=self.max_parameters,
                    nesting_threshold=self.nesting_threshold,
                )
                analysis.metrics = python_metrics(content)
            except SyntaxError as error:
                analysis.parse_error = str(error)
                findings = [
                    finding_from_rule(
                        SYNTAX_RULE,
                        line_start=getattr(error, "lineno", 1),
                        line_end=getattr(error, "lineno", 1),
                        description=f"SyntaxError: {error.msg} (line {getattr(error, 'lineno', '?')}).",
                        confidence=1.0,
                    )
                ]
                analysis.metrics = generic_metrics(content, language)
            findings.extend(
                analyze_with_regex(content, language, file_input.relative_path, skip_rules=("SEC101",))
            )
        else:
            findings = analyze_with_regex(content, language, file_input.relative_path)
            analysis.metrics = generic_metrics(content, language)

        analysis.findings = _dedupe_and_enrich(findings, lines)
        return analysis

    # -- project -----------------------------------------------------------
    def analyze_project(
        self,
        files: Sequence[FileInput],
        detect_duplicate_blocks: bool = True,
        resolve_dependencies: bool = True,
        check_installed_packages: bool = True,
    ) -> ProjectAnalysis:
        result = ProjectAnalysis()
        for file_input in files:
            try:
                result.files.append(self.analyze_file(file_input))
            except Exception as error:  # pragma: no cover - defensive
                logger.error("Analysis failed for %s: %s", file_input.relative_path, error)
                result.files.append(
                    FileAnalysis(
                        file=file_input,
                        findings=[
                            finding_from_rule(
                                SYNTAX_RULE,
                                line_start=1,
                                description=f"Analysis failed: {error}",
                            )
                        ],
                        parse_error=str(error),
                    )
                )

        if detect_duplicate_blocks:
            try:
                result.duplicate_groups = detect_duplicates(
                    [(f.file.file_id, f.file.relative_path, f.file.content) for f in result.files],
                    window=self.duplicate_window,
                )
            except Exception as error:  # pragma: no cover - defensive
                logger.warning("Duplicate detection failed: %s", error)

        if resolve_dependencies:
            try:
                result.dependencies = analyze_dependencies(
                    [
                        (f.file.file_id, f.file.relative_path, f.file.language, f.file.content)
                        for f in result.files
                    ],
                    check_installed=check_installed_packages,
                )
            except Exception as error:  # pragma: no cover - defensive
                logger.warning("Dependency analysis failed: %s", error)

        return result

    # -- helpers -----------------------------------------------------------
    def extra_findings(self, analysis: ProjectAnalysis) -> List[Dict[str, object]]:
        """Duplicate and dependency findings as persistence-ready dicts."""
        path_by_file = {f.file.file_id: f.file.relative_path for f in analysis.files}
        payloads = finding_specs_from_duplicates(analysis.duplicate_groups, path_by_file)
        payloads.extend(dependency_findings(analysis.dependencies, path_by_file))
        return payloads

    def stats(self, analysis: ProjectAnalysis) -> Dict[str, object]:
        summary = analysis.summary()
        summary["duplicates"] = duplicate_summary(analysis.duplicate_groups)
        return summary


def _dedupe_and_enrich(findings: Sequence[RuleFinding], lines: Sequence[str]) -> List[RuleFinding]:
    """Removes duplicate findings, fills in snippets and sorts worst-first."""
    unique: Dict[tuple, RuleFinding] = {}
    for finding in findings:
        key = (finding.rule_id, finding.line_start, finding.column_start)
        if key in unique:
            continue
        if not finding.code_snippet and finding.line_start:
            index = finding.line_start - 1
            if 0 <= index < len(lines):
                finding.code_snippet = lines[index].strip()[:400]
        unique[key] = finding

    return sorted(
        unique.values(),
        key=lambda f: (
            SEVERITY_RANK.get(f.severity, 99),
            f.line_start or 0,
            f.rule_id,
        ),
    )
