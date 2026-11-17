"""Regex / line based rule pack used for non-Python languages and cross-cutting checks."""
from __future__ import annotations

import re
from typing import List, Optional, Pattern, Tuple

from analyzer.rules.base import (
    Category,
    Rule,
    RuleFinding,
    Severity,
    family_matches,
    finding_from_rule,
    register_all,
)

GENERIC_RULES: List[Rule] = [
    Rule(
        id="SEC101",
        title="Hardcoded credential",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        description="A password, token or key is embedded in source code.",
        suggestion="Move the value to an environment variable or secret manager and rotate it.",
        languages=("any",),
        detector="regex",
    ),
    Rule(
        id="SEC102",
        title="Private key committed to source",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        description="A PEM private key block is present in the file.",
        suggestion="Remove the key from the repository, rotate it and load it from a secret store.",
        languages=("any",),
        detector="regex",
    ),
    Rule(
        id="SEC103",
        title="Cloud provider access key",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        description="An AWS/GitHub/Slack style access token literal was detected.",
        suggestion="Revoke the token, rotate it and load it from the environment.",
        languages=("any",),
        detector="regex",
    ),
    Rule(
        id="SEC104",
        title="Dynamic code evaluation",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="eval() / new Function() execute arbitrary strings as code.",
        suggestion="Parse the input as data (JSON) and dispatch through an allow-list.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="SEC105",
        title="HTML injected into the DOM",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="Assigning untrusted data to innerHTML enables cross-site scripting.",
        suggestion="Use textContent, or sanitise with a library such as DOMPurify.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="SEC106",
        title="document.write usage",
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        description="document.write can inject markup and blocks the parser.",
        suggestion="Build DOM nodes with createElement/appendChild instead.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="SEC107",
        title="Dangerous React HTML injection",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="dangerouslySetInnerHTML bypasses React's escaping.",
        suggestion="Render text, or sanitise the HTML before injecting it.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="SEC108",
        title="Shell command from child_process",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="child_process.exec runs a shell command and is injectable.",
        suggestion="Use execFile/spawn with an argument array.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="SEC109",
        title="Plaintext HTTP endpoint",
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        description="An http:// URL sends traffic without TLS.",
        suggestion="Use https:// for network calls.",
        languages=("any",),
        detector="regex",
    ),
    Rule(
        id="SEC110",
        title="Stack trace printed to output",
        category=Category.SECURITY,
        severity=Severity.LOW,
        description="printStackTrace exposes internals and bypasses structured logging.",
        suggestion="Log through the application logger with an appropriate level.",
        languages=("java",),
        detector="regex",
    ),
    Rule(
        id="BUG101",
        title="Loose equality comparison",
        category=Category.BUG,
        severity=Severity.LOW,
        description="`==` performs type coercion in JavaScript and hides bugs.",
        suggestion="Use `===` / `!==`.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="BUG102",
        title="Debugger statement left in code",
        category=Category.BUG,
        severity=Severity.LOW,
        description="A `debugger` statement halts execution when devtools are open.",
        suggestion="Remove the statement before shipping.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="QUA101",
        title="TODO / FIXME marker",
        category=Category.QUALITY,
        severity=Severity.INFO,
        description="Unresolved work is recorded in a comment.",
        suggestion="Track it in the issue tracker or resolve it.",
        languages=("any",),
        detector="regex",
    ),
    Rule(
        id="QUA102",
        title="Very long line",
        category=Category.QUALITY,
        severity=Severity.INFO,
        description="The line exceeds 200 characters and is hard to review.",
        suggestion="Wrap the expression or split the statement.",
        languages=("any",),
        detector="line",
    ),
    Rule(
        id="QUA103",
        title="console.log left in code",
        category=Category.QUALITY,
        severity=Severity.LOW,
        description="console.log output is unstructured and usually temporary.",
        suggestion="Use the project logger, or remove the statement.",
        languages=("js",),
        detector="regex",
    ),
    Rule(
        id="QUA104",
        title="var declaration",
        category=Category.QUALITY,
        severity=Severity.LOW,
        description="`var` is function-scoped and hoisted, unlike let/const.",
        suggestion="Use `const` by default and `let` when reassignment is needed.",
        languages=("js",),
        detector="regex",
    ),
]

register_all(GENERIC_RULES)

_RULES_BY_ID = {rule.id: rule for rule in GENERIC_RULES}

_PLACEHOLDER_HINTS = ("xxx", "changeme", "example", "dummy", "placeholder", "your_", "your-", "<", "${", "***")

_PATTERN_TABLE: List[Tuple[str, Pattern[str]]] = [
    (
        "SEC101",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
            r"private[_-]?key|client[_-]?secret)\b\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']"
        ),
    ),
    ("SEC102", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "SEC103",
        re.compile(
            r"\b(AKIA[0-9A-Z]{16}"          # AWS access key id
            r"|ghp_[A-Za-z0-9]{30,}"        # GitHub personal access token
            r"|xox[baprs]-[A-Za-z0-9-]{10,}"  # Slack token
            r"|sk_live_[A-Za-z0-9]{10,}"    # Stripe live secret
            r"|sk_test_[A-Za-z0-9]{10,}"    # Stripe test secret
            r"|sk-[A-Za-z0-9_\-]{20,}"      # OpenAI style key
            r"|AIza[0-9A-Za-z_\-]{20,}"     # Google API key
            r")\b"
        ),
    ),
    ("SEC104", re.compile(r"\b(eval\s*\(|new\s+Function\s*\()")),
    ("SEC105", re.compile(r"\.innerHTML\s*\+?=")),
    ("SEC106", re.compile(r"\bdocument\.write\s*\(")),
    ("SEC107", re.compile(r"dangerouslySetInnerHTML")),
    ("SEC108", re.compile(r"child_process\.(exec|execSync)\s*\(")),
    ("SEC109", re.compile(r"[\"']http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)[^\"'\s]+[\"']")),
    ("SEC110", re.compile(r"\.printStackTrace\s*\(")),
    ("BUG101", re.compile(r"[^=!<>]==(?!=)[^=]")),
    ("BUG102", re.compile(r"^\s*debugger\s*;?\s*$", re.MULTILINE)),
    ("QUA101", re.compile(r"(?i)\b(TODO|FIXME|HACK|XXX)\b")),
    ("QUA103", re.compile(r"\bconsole\.(log|debug)\s*\(")),
    ("QUA104", re.compile(r"^\s*var\s+[A-Za-z_$]", re.MULTILINE)),
]

# Rules that should only fire for specific language families.
_PATTERN_LANGUAGE_OVERRIDE = {
    "SEC104": ("js",),
    "SEC105": ("js",),
    "SEC106": ("js",),
    "SEC107": ("js",),
    "SEC108": ("js",),
    "SEC110": ("java",),
    "BUG101": ("js",),
    "BUG102": ("js",),
    "QUA103": ("js",),
    "QUA104": ("js",),
}

# Files where credential-looking literals are expected and should not be reported.
_TEST_PATH_HINTS = ("test_", "_test.", ".test.", "spec.", "fixtures/", "mocks/")


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _is_placeholder(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def analyze_with_regex(
    source: str,
    language: Optional[str],
    path: str = "",
    skip_rules: Tuple[str, ...] = (),
) -> List[RuleFinding]:
    """Runs the regex rule pack over ``source``."""
    findings: List[RuleFinding] = []
    lines = source.splitlines()
    is_test_path = any(hint in path.lower() for hint in _TEST_PATH_HINTS)

    for rule_id, pattern in _PATTERN_TABLE:
        if rule_id in skip_rules:
            continue
        rule = _RULES_BY_ID[rule_id]
        families = _PATTERN_LANGUAGE_OVERRIDE.get(rule_id, rule.languages)
        if not family_matches(families, language):
            continue
        for match in pattern.finditer(source):
            if rule_id == "SEC101" and (is_test_path or _is_placeholder(match.group(0))):
                continue
            if rule_id == "SEC103" and is_test_path:
                continue
            line = _line_of(source, match.start())
            finding = finding_from_rule(
                rule,
                line_start=line,
                line_end=line,
                column_start=match.start() - source.rfind("\n", 0, match.start()) - 1,
                code_snippet=lines[line - 1].strip() if line - 1 < len(lines) else None,
                confidence=0.9 if rule_id in {"SEC101", "SEC102", "SEC103"} else 0.75,
            )
            findings.append(finding)

    # Very long lines
    long_rule = _RULES_BY_ID["QUA102"]
    for index, line in enumerate(lines, start=1):
        if len(line) > 200 and "QUA102" not in skip_rules:
            findings.append(
                finding_from_rule(
                    long_rule,
                    line_start=index,
                    line_end=index,
                    description=f"Line {index} is {len(line)} characters long.",
                    confidence=0.99,
                )
            )
    return findings


def analyze_python_regex_extras(source: str, path: str = "") -> List[RuleFinding]:
    """Cross-cutting regex rules that also apply to Python files."""
    return analyze_with_regex(source, "Python", path)
