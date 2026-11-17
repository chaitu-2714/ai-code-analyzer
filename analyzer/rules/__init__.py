"""Rule packs for the static analysis engine.

Importing this package registers every rule in the global registry, so
``analyzer.rules.base.all_rules()`` returns the full catalogue.
"""
from analyzer.rules.base import (  # noqa: F401
    Category,
    Rule,
    RuleFinding,
    Severity,
    all_rules,
    finding_from_rule,
    get_rule,
    language_family,
    register,
    register_all,
    rules_by_category,
    rules_for_language,
)
from analyzer.rules.project_rules import PROJECT_RULES  # noqa: F401
from analyzer.rules.python_rules import PYTHON_RULES, analyze_python  # noqa: F401
from analyzer.rules.regex_rules import GENERIC_RULES, analyze_with_regex  # noqa: F401

__all__ = [
    "GENERIC_RULES",
    "PROJECT_RULES",
    "PYTHON_RULES",
    "Category",
    "Rule",
    "RuleFinding",
    "Severity",
    "all_rules",
    "analyze_python",
    "analyze_with_regex",
    "finding_from_rule",
    "get_rule",
    "language_family",
    "register",
    "register_all",
    "rules_by_category",
    "rules_for_language",
]
