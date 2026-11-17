"""Project-wide rules (duplication, dependency graph) that need more than one file."""
from __future__ import annotations

from analyzer.rules.base import Category, Rule, Severity, register_all

PROJECT_RULES = [
    Rule(
        id="DUP001",
        title="Duplicated code block",
        category=Category.DUPLICATION,
        severity=Severity.MEDIUM,
        description="Identical code appears in more than one place.",
        suggestion="Extract the shared block into one reusable function or module.",
        languages=("any",),
        detector="duplication",
    ),
    Rule(
        id="DEP001",
        title="Unresolved dependency",
        category=Category.DEPENDENCY,
        severity=Severity.MEDIUM,
        description="An imported module cannot be resolved in this environment or project.",
        suggestion="Add the package to the dependency manifest or fix the import path.",
        languages=("any",),
        detector="dependency",
    ),
    Rule(
        id="DEP002",
        title="Circular import",
        category=Category.DEPENDENCY,
        severity=Severity.HIGH,
        description="Two or more modules import each other, which breaks initialisation order.",
        suggestion="Move shared code into a lower-level module to break the cycle.",
        languages=("any",),
        detector="dependency",
    ),
]

register_all(PROJECT_RULES)
