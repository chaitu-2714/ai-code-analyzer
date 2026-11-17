"""Rule metadata, severity/category vocabulary and the global rule registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Tuple


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class Category(str, Enum):
    SYNTAX = "SYNTAX"
    BUG = "BUG"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    QUALITY = "QUALITY"
    DOCUMENTATION = "DOCUMENTATION"
    DUPLICATION = "DUPLICATION"
    DEPENDENCY = "DEPENDENCY"


#: Ordered worst-first, used for sorting and reporting.
SEVERITY_ORDER: Tuple[str, ...] = (
    Severity.CRITICAL.value,
    Severity.HIGH.value,
    Severity.MEDIUM.value,
    Severity.LOW.value,
    Severity.INFO.value,
)

SEVERITY_RANK: Dict[str, int] = {name: index for index, name in enumerate(SEVERITY_ORDER)}

#: Score penalty applied to an agent score for a single finding of this severity.
SEVERITY_PENALTY: Dict[str, float] = {
    Severity.CRITICAL.value: 20.0,
    Severity.HIGH.value: 10.0,
    Severity.MEDIUM.value: 4.0,
    Severity.LOW.value: 1.5,
    Severity.INFO.value: 0.4,
}

#: Language families a rule can target.
LANGUAGE_FAMILIES: Dict[str, Tuple[str, ...]] = {
    "python": ("python", "py"),
    "js": ("javascript", "jsx", "typescript", "tsx", "node"),
    "java": ("java", "kotlin", "scala"),
    "go": ("go", "golang"),
    "ruby": ("ruby", "rb"),
    "php": ("php",),
    "c": ("c", "header"),
    "cpp": ("c++", "cpp"),
    "csharp": ("c#", "csharp"),
    "shell": ("shell", "bash", "sh", "batch", "powershell"),
}


def language_family(language: Optional[str]) -> str:
    """Maps a detected language label (e.g. ``"TypeScript (TSX)"``) to a family."""
    if not language:
        return "unknown"
    label = language.strip().lower()
    for family, tokens in LANGUAGE_FAMILIES.items():
        for token in tokens:
            if token in label:
                return family
    return "unknown"


def family_matches(rule_families: Iterable[str], language: Optional[str]) -> bool:
    """True when a rule targets ``language`` (``"any"`` matches everything)."""
    declared = tuple(rule_families)
    if not declared or "any" in declared:
        return True
    return language_family(language) in declared


@dataclass(frozen=True)
class Rule:
    """Static description of a detector rule."""

    id: str
    title: str
    category: Category
    severity: Severity
    description: str
    suggestion: str
    languages: Tuple[str, ...] = ("any",)
    detector: str = "ast"
    tags: Tuple[str, ...] = ()

    def matches_language(self, language: Optional[str]) -> bool:
        return family_matches(self.languages, language)

    @property
    def category_value(self) -> str:
        return self.category.value if isinstance(self.category, Category) else str(self.category)

    @property
    def severity_value(self) -> str:
        return self.severity.value if isinstance(self.severity, Severity) else str(self.severity)


@dataclass
class RuleFinding:
    """A single issue reported by a rule for one file."""

    rule_id: str
    title: str
    category: str
    severity: str
    description: str
    suggestion: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    code_snippet: Optional[str] = None
    confidence: float = 0.8
    detector: str = "ast"
    extra: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "suggestion": self.suggestion,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "column_start": self.column_start,
            "column_end": self.column_end,
            "code_snippet": self.code_snippet,
            "confidence": self.confidence,
            "detector": self.detector,
        }


_REGISTRY: Dict[str, Rule] = {}


def register(rule: Rule) -> Rule:
    """Registers a rule; re-registering the same id replaces the previous entry."""
    _REGISTRY[rule.id] = rule
    return rule


def register_all(rules: Iterable[Rule]) -> None:
    for rule in rules:
        register(rule)


def get_rule(rule_id: str) -> Optional[Rule]:
    return _REGISTRY.get(rule_id)


def all_rules() -> List[Rule]:
    return sorted(_REGISTRY.values(), key=lambda r: r.id)


def rules_for_language(language: Optional[str]) -> List[Rule]:
    return [rule for rule in all_rules() if rule.matches_language(language)]


def rules_by_category(category: str) -> List[Rule]:
    wanted = str(getattr(category, "value", category)).upper()
    return [rule for rule in all_rules() if rule.category_value.upper() == wanted]


def finding_from_rule(rule: Rule, **kwargs) -> RuleFinding:
    """Builds a :class:`RuleFinding` pre-filled from the rule definition."""
    kwargs.setdefault("title", rule.title)
    kwargs.setdefault("description", rule.description)
    kwargs.setdefault("suggestion", rule.suggestion)
    kwargs.setdefault("detector", rule.detector)
    return RuleFinding(
        rule_id=rule.id,
        category=rule.category_value,
        severity=rule.severity_value,
        **kwargs,
    )
