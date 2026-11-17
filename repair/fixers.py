"""Template based fixers (Phase 6).

Every fixer receives the full file source plus the finding and returns a
:class:`FixResult`.  A fixer returns ``None`` when it cannot patch safely; the
engine then records a *manual* suggestion with guidance instead of guessing.

Python patches are always re-parsed before being returned, so a fixer can never
produce a file that no longer compiles.
"""
from __future__ import annotations

import ast
import contextvars
import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

from analyzer.rules.base import family_matches, language_family


@dataclass
class FixResult:
    patched_source: Optional[str]
    explanation: str
    confidence: float
    strategy: str = "template"

    @property
    def can_apply(self) -> bool:
        return self.patched_source is not None


MANUAL_HINTS: Dict[str, str] = {
    "BUG006": "Move the return out of the finally block; keep only cleanup there.",
    "PERF001": "Wrap the open() call in a `with` statement and re-indent the block.",
    "PERF002": "Collect the parts in a list and join once with ''.join(parts).",
    "PERF003": "Iterate directly (`for item in items`) or use enumerate().",
    "PERF004": "Flatten the loops using a lookup dict/set or precomputed index.",
    "QUA001": "Extract cohesive blocks into smaller, well-named helper functions.",
    "QUA002": "Group related parameters into a dataclass/config object.",
    "QUA003": "Split branches into helpers or table-drive the decision logic.",
    "QUA004": "Use guard clauses and early returns to flatten the nesting.",
    "QUA005": "Replace the wildcard import with explicit names.",
    "QUA007": "Add parameter and return type annotations.",
    "QUA008": "Rename the variable so it no longer shadows a builtin.",
    "QUA101": "Resolve the TODO or move it into the issue tracker.",
    "QUA102": "Wrap the long expression across multiple lines.",
    "DUP001": "Extract the duplicated block into one shared function or module.",
    "DEP001": "Add the package to your dependency manifest or fix the import path.",
    "DEP002": "Move shared code into a lower-level module to break the cycle.",
    "BUG009": "Replace the assert with an explicit `raise ValueError(...)`.",
    "SEC009": "Use tempfile.NamedTemporaryFile or tempfile.mkstemp.",
    "SEC101": "Move the credential to the environment and rotate it immediately.",
    "SEC102": "Remove the key from the repository and rotate it.",
    "SEC103": "Revoke the token, then load it from the environment.",
    "SEC104": "Parse the payload as JSON and dispatch through an allow-list.",
    "SEC105": "Use textContent or sanitise the HTML (e.g. DOMPurify).",
    "SEC106": "Build DOM nodes with createElement/appendChild.",
    "SEC107": "Render text, or sanitise the HTML before injecting it.",
    "SEC108": "Use execFile/spawn with an argument array.",
    "SEC109": "Switch the endpoint to https://.",
    "SEC110": "Log through the application logger instead of printing the trace.",
    "BUG101": "Replace `==` with `===` (and `!=` with `!==`).",
    "BUG102": "Delete the debugger statement.",
    "QUA103": "Remove the console.log or use the project logger.",
}

_PY_LOGGER_IMPORT = "import logging"
_PY_LOGGER_SETUP = "logger = logging.getLogger(__name__)"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _lines(source: str) -> List[str]:
    return source.splitlines()


def _join(lines: Sequence[str]) -> str:
    return "\n".join(lines) + ("\n" if lines else "")


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _last_import_line(lines: List[str]) -> int:
    """1-based number of the last top-level import (0 when there is none)."""
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        last = 0
        for index, line in enumerate(lines):
            if line.startswith(("import ", "from ")):
                last = index + 1
        return last

    last = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last = max(last, getattr(node, "end_lineno", node.lineno) or node.lineno)
        elif isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant):
            continue  # module docstring / bare string
        else:
            break
    return last


def _docstring_end_line(lines: List[str]) -> int:
    """1-based line where the module docstring ends (0 when there is none)."""
    try:
        tree = ast.parse("\n".join(lines))
    except SyntaxError:
        return 0
    if not tree.body:
        return 0
    first = tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(getattr(first, "value", None), ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return getattr(first, "end_lineno", first.lineno) or first.lineno
    return 0


def _import_insert_index(lines: List[str]) -> int:
    """0-based index where a new import belongs (after docstring and imports)."""
    return max(_last_import_line(lines), _docstring_end_line(lines))


def _ensure_import(lines: List[str], statement: str) -> List[str]:
    """Adds ``statement`` after the module docstring and the existing imports."""
    module = statement.split()[1].split(".")[0]
    pattern = re.compile(rf"^\s*(import\s+{re.escape(module)}\b|from\s+{re.escape(module)}\b)")
    if any(pattern.match(line) for line in lines):
        return lines
    index = _import_insert_index(lines)
    if index > 0 and index == _docstring_end_line(lines) and index < len(lines) and lines[index].strip():
        lines.insert(index, "")
        index += 1
    lines.insert(index, statement)
    return lines


def _ensure_logger(lines: List[str]) -> List[str]:
    """Makes sure ``logger`` exists, defined *after* the imports."""
    lines = _ensure_import(lines, _PY_LOGGER_IMPORT)
    if any(_PY_LOGGER_SETUP in candidate for candidate in lines):
        return lines
    insert_at = _import_insert_index(lines)
    lines.insert(insert_at, _PY_LOGGER_SETUP)
    if insert_at + 1 < len(lines) and lines[insert_at + 1].strip():
        lines.insert(insert_at + 1, "")
    if insert_at > 0 and lines[insert_at - 1].strip():
        lines.insert(insert_at, "")
    return lines


#: Fixers that delete or rewrite lines other patches rely on.  They are applied
#: only on a fresh analysis (never inside a batched sweep).
BATCH_UNSAFE_RULES = frozenset({"BUG004"})


def is_batch_safe(rule_id: str) -> bool:
    """True when the fixer may run alongside other fixes in the same pass."""
    return str(rule_id or "") not in BATCH_UNSAFE_RULES


def _validate_python(source: str) -> bool:
    try:
        ast.parse(source)
        return True
    except SyntaxError:
        return False


#: Callers that validate the patch themselves can switch the internal
#: re-parse off (it roughly halves the cost of a large batched rewrite).
_VALIDATE_PATCHES: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "validate_patches", default=True
)


def _result(source: str, explanation: str, confidence: float, language: str) -> Optional[FixResult]:
    if _VALIDATE_PATCHES.get() and language_family(language) == "python" and not _validate_python(source):
        return None
    return FixResult(source, explanation, confidence)


# ---------------------------------------------------------------------------
# Python fixers
# ---------------------------------------------------------------------------

def fix_bare_except(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    line = lines[index]
    if not re.match(r"^\s*except\s*:\s*$", line):
        return None
    indent = _indent_of(line)
    lines[index] = f"{indent}except Exception:  # noqa: BLE001 - narrowed deliberately"
    return _result(
        _join(lines),
        "Replaced the bare except with `except Exception:` so SystemExit and KeyboardInterrupt "
        "still propagate while ordinary errors are handled.",
        0.8,
        language,
    )


def fix_swallowed_exception(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    # Walk forward to the `pass` that swallows the exception.
    for offset in range(index, min(index + 3, len(lines))):
        if re.match(r"^\s*pass\s*$", lines[offset]):
            indent = _indent_of(lines[offset])
            lines[offset] = f'{indent}logger.exception("Unexpected error")'
            lines = _ensure_logger(lines)
            return _result(
                _join(lines),
                "Replaced `pass` with `logger.exception(...)` so the failure is recorded instead of hidden.",
                0.7,
                language,
            )
    return None


def fix_none_comparison(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"==\s*None\b", "is None", original)
    patched = re.sub(r"!=\s*None\b", "is not None", patched)
    patched = re.sub(r"==\s*True\b", "is True", patched)
    patched = re.sub(r"==\s*False\b", "is False", patched)
    patched = re.sub(r"!=\s*True\b", "is not True", patched)
    patched = re.sub(r"!=\s*False\b", "is not False", patched)
    if patched == original:
        return None
    lines[index] = patched
    return _result(
        _join(lines),
        "Switched the comparison to identity (`is None` / `is not None`), which cannot be overridden by __eq__.",
        0.85,
        language,
    )


def fix_is_literal(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"\bis\s+not\s+([\"'\d])", r"!= \1", original)
    patched = re.sub(r"\bis\s+([\"'\d])", r"== \1", patched)
    if patched == original:
        return None
    lines[index] = patched
    return _result(
        _join(lines),
        "Replaced identity comparison against a literal with value comparison.",
        0.8,
        language,
    )


def fix_unused_import(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    line = lines[index]
    if not re.match(r"^\s*(import|from)\s", line):
        return None
    # Only delete single-line imports without a trailing continuation.
    if line.rstrip().endswith(("\\", "(", ",")):
        return None
    removed = line.strip()
    del lines[index]
    return _result(
        _join(lines),
        f"Removed the unused import `{removed}`.",
        0.8,
        language,
    )


def fix_eval(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"\beval\s*\(", "ast.literal_eval(", original)
    if patched == original:
        return None
    lines[index] = patched
    lines = _ensure_import(lines, "import ast")
    return _result(
        _join(lines),
        "Replaced eval() with ast.literal_eval(), which only accepts literal data and cannot execute code.",
        0.6,
        language,
    )


def fix_shell_true(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r",?\s*shell\s*=\s*True", "", original)
    if patched == original:
        return None
    lines[index] = patched
    return _result(
        _join(lines),
        "Removed `shell=True` so the command is no longer interpreted by a shell. "
        "Pass the command as a list of arguments.",
        0.5,
        language,
    )


def fix_os_system(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    match = re.search(r"os\.system\s*\((.*)\)\s*$", original)
    if not match:
        return None
    argument = match.group(1)
    lines[index] = original[: match.start()] + f"subprocess.run(shlex.split({argument}), check=True)"
    lines = _ensure_import(lines, "import subprocess")
    lines = _ensure_import(lines, "import shlex")
    return _result(
        _join(lines),
        "Replaced os.system() with subprocess.run(shlex.split(...), check=True): no shell, and failures raise.",
        0.55,
        language,
    )


def fix_yaml_load(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"\byaml\.(unsafe_)?load\s*\(", "yaml.safe_load(", original)
    if patched == original:
        return None
    lines[index] = patched
    return _result(
        _join(lines),
        "Switched to yaml.safe_load(), which cannot construct arbitrary Python objects.",
        0.85,
        language,
    )


def fix_weak_hash(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = original.replace("hashlib.md5", "hashlib.sha256").replace("hashlib.sha1", "hashlib.sha256")
    if patched == original:
        return None
    lines[index] = patched
    return _result(
        _join(lines),
        "Replaced the weak digest with SHA-256.",
        0.7,
        language,
    )


def fix_verify_false(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r",?\s*verify\s*=\s*False", "", original)
    if patched == original:
        return None
    lines[index] = patched
    return _result(
        _join(lines),
        "Removed `verify=False` so TLS certificates are validated again.",
        0.8,
        language,
    )


def fix_hardcoded_secret(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    line = lines[index]
    match = re.match(r"^(\s*)([A-Za-z_][\w]*)\s*=\s*([\"']).*?\3\s*(#.*)?$", line)
    if not match:
        return None
    indent, name, _quote, comment = match.group(1), match.group(2), match.group(3), match.group(4) or ""
    lines[index] = f'{indent}{name} = os.getenv("{name}", ""){("  " + comment.strip()) if comment else ""}'
    lines = _ensure_import(lines, "import os")
    return _result(
        _join(lines),
        f"Replaced the hardcoded value of `{name}` with an environment lookup. "
        "Rotate the leaked credential and set the variable in your environment.",
        0.75,
        language,
    )


def fix_print(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"(?<![\w.])print\s*\(", "logger.info(", original)
    if patched == original:
        return None
    lines[index] = patched
    lines = _ensure_logger(lines)
    return _result(
        _join(lines),
        "Replaced print() with logger.info() so output is levelled and redirectable.",
        0.7,
        language,
    )


def fix_mutable_default(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    header = lines[index]
    match = re.match(r"^(\s*)(async\s+)?def\s+(\w+)\s*\((.*)\)\s*(->.*)?:\s*$", header)
    if not match:
        return None
    indent, _async, name, params, returns = match.groups()
    new_params, changed = _neutralise_defaults(params)
    if not changed:
        return None
    signature = f"{indent}{'async ' if _async else ''}def {name}({new_params}){(returns or '')}:"
    body_index = index + 1
    # Skip an existing docstring so the guard is inserted after it.
    insert_at = body_index
    if body_index < len(lines) and re.match(r"^\s*(\"\"\"|''')", lines[body_index]):
        quote = '"""' if '"""' in lines[body_index] else "'''"
        if lines[body_index].strip().count(quote) < 2:
            for offset in range(body_index + 1, len(lines)):
                insert_at = offset + 1
                if quote in lines[offset]:
                    break
        else:
            insert_at = body_index + 1

    guards: List[str] = []
    for name, default in changed:
        guards.append(f"{indent}    if {name} is None:")
        guards.append(f"{indent}        {name} = {_fresh_container(default)}")
    lines[index] = signature
    for offset, guard in enumerate(guards):
        lines.insert(insert_at + offset, guard)
    return _result(
        _join(lines),
        "Replaced the mutable default(s) "
        + ", ".join(name for name, _default in changed)
        + " with None and initialised them inside the function.",
        0.7,
        language,
    )


def _neutralise_defaults(params: str):
    """Turns `x=[]` style defaults into `x=None`; returns (params, names)."""
    changed: List[tuple] = []
    pieces = _split_params(params)
    rebuilt: List[str] = []
    for piece in pieces:
        match = re.match(r"^(\s*)(\*{0,2}\w+)\s*=\s*(.+?)\s*$", piece)
        if match and re.match(r"^(\[\]|\{\}|set\(\)|list\(\)|dict\(\))$", match.group(3)):
            rebuilt.append(f"{match.group(2)}=None")
            changed.append((match.group(2).lstrip("*"), match.group(3)))
        else:
            rebuilt.append(piece.strip())
    return ", ".join(part for part in rebuilt if part.strip()), changed


def _split_params(params: str) -> List[str]:
    depth = 0
    current = ""
    pieces: List[str] = []
    for char in params:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            pieces.append(current)
            current = ""
        else:
            current += char
    if current.strip():
        pieces.append(current)
    return pieces


def _fresh_container(default: str) -> str:
    """Empty container literal matching the original default."""
    if default.startswith("{"):
        return "{}"
    if default.startswith(("set", "dict")):
        return "{}" if default.startswith("dict") else "set()"
    return "[]"


def fix_module_docstring(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    if not lines:
        return None
    insert_at = 0
    while insert_at < min(len(lines), 3) and (
        lines[insert_at].startswith("#!") or "coding:" in lines[insert_at]
    ):
        insert_at += 1
    # A module docstring has to be the very first statement of the file.
    try:
        if ast.get_docstring(ast.parse("\n".join(lines))) is not None:
            return None
    except SyntaxError:
        return None
    if insert_at < len(lines) and lines[insert_at].lstrip()[:3] in ('"""', "'''"):
        return None
    stem = str(finding.get("file_path") or "module").split("/")[-1].rsplit(".", 1)[0]
    lines.insert(insert_at, f'"""{stem.replace("_", " ").capitalize()} module."""')
    if insert_at + 1 < len(lines) and lines[insert_at + 1].strip():
        lines.insert(insert_at + 1, "")
    return _result(_join(lines), "Added a module docstring.", 0.85, language)


def fix_class_docstring(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    header = lines[index]
    match = re.match(r"^(\s*)class\s+(\w+)", header)
    if not match:
        return None
    indent, name = match.group(1), match.group(2)
    # The class header may span lines; find the line ending with a colon.
    insert_at = index
    while insert_at < len(lines) - 1 and not lines[insert_at].rstrip().endswith(":"):
        insert_at += 1
    if insert_at + 1 < len(lines) and '"""' in lines[insert_at + 1]:
        return None
    lines.insert(insert_at + 1, f'{indent}    """{name}."""')
    return _result(_join(lines), f"Added a docstring to class `{name}`.", 0.8, language)


def fix_function_docstring(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    match = re.match(r"^(\s*)(async\s+)?def\s+(\w+)", lines[index])
    if not match:
        return None
    indent, _async, name = match.group(1), match.group(2), match.group(3)
    insert_at = index
    while insert_at < len(lines) - 1 and not lines[insert_at].rstrip().endswith(":"):
        insert_at += 1
    if insert_at + 1 < len(lines) and re.match(r"^\s*(\"\"\"|''')", lines[insert_at + 1]):
        return None
    docstring = (
        "Initialise the instance."
        if name == "__init__"
        else f"{name.replace('_', ' ').capitalize()}."
    )
    lines.insert(insert_at + 1, f'{indent}    """{docstring}"""')
    return _result(_join(lines), f"Added a docstring to `{name}`.", 0.75, language)


# ---------------------------------------------------------------------------
# JavaScript / TypeScript fixers
# ---------------------------------------------------------------------------

def fix_loose_equality(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"([^=!<>])==(?!=)", r"\1===", original)
    patched = re.sub(r"([^=!<>])!=(?!=)", r"\1!==", patched)
    if patched == original:
        return None
    lines[index] = patched
    return FixResult(_join(lines), "Replaced loose equality with strict equality (=== / !==).", 0.8)


def fix_var_declaration(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    original = lines[index]
    patched = re.sub(r"^(\s*)var\s+", r"\1const ", original)
    if patched == original:
        return None
    lines[index] = patched
    return FixResult(_join(lines), "Replaced `var` with `const` (use `let` if it is reassigned).", 0.6)


def fix_debugger(source: str, finding: Dict[str, object], language: str) -> Optional[FixResult]:
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    if "debugger" not in lines[index]:
        return None
    del lines[index]
    return FixResult(_join(lines), "Removed the debugger statement.", 0.85)


FIXERS: Dict[str, Callable[[str, Dict[str, object], str], Optional[FixResult]]] = {
    "BUG001": fix_bare_except,
    "BUG002": fix_mutable_default,
    "BUG003": fix_none_comparison,
    "BUG004": fix_unused_import,
    "BUG005": fix_swallowed_exception,
    "BUG008": fix_is_literal,
    "BUG101": fix_loose_equality,
    "BUG102": fix_debugger,
    "SEC001": fix_eval,
    "SEC002": fix_shell_true,
    "SEC003": fix_os_system,
    "SEC005": fix_yaml_load,
    "SEC006": fix_hardcoded_secret,
    "SEC007": fix_weak_hash,
    "SEC010": fix_verify_false,
    "SEC101": fix_hardcoded_secret,
    "SEC103": fix_hardcoded_secret,
    "QUA006": fix_print,
    "QUA104": fix_var_declaration,
    "DOC001": fix_module_docstring,
    "DOC002": fix_class_docstring,
    "DOC003": fix_function_docstring,
}


#: Language families each fixer may touch.  A Python fixer must never rewrite
#: Ruby or PHP, and the JavaScript fixers must never touch Python.
FIXER_FAMILIES: Dict[str, tuple] = {
    "BUG101": ("js",),
    "BUG102": ("js",),
    "QUA104": ("js",),
    "SEC101": ("python", "js"),
    "SEC103": ("python", "js"),
}
DEFAULT_FIXER_FAMILIES: tuple = ("python",)


def fixer_families(rule_id: str) -> tuple:
    """Language families a rule's fixer is allowed to touch."""
    return FIXER_FAMILIES.get(str(rule_id or ""), DEFAULT_FIXER_FAMILIES)


def fix_hardcoded_secret_js(
    source: str, finding: Dict[str, object], language: str
) -> Optional[FixResult]:
    """JavaScript/TypeScript: ``const KEY = "..."`` -> ``process.env.KEY``."""
    lines = _lines(source)
    index = (finding.get("line_start") or 1) - 1
    if not (0 <= index < len(lines)):
        return None
    match = re.match(
        r"^(\s*)(?:(const|let|var)\s+)?([A-Za-z_$][\w$]*)\s*=\s*([\"']).*?\4\s*;?\s*$",
        lines[index],
    )
    if not match:
        return None
    indent, declaration, name, _quote = match.group(1), match.group(2), match.group(3), match.group(4)
    prefix = f"{declaration} " if declaration else ""
    lines[index] = f'{indent}{prefix}{name} = process.env.{name} || "";'
    return FixResult(
        _join(lines),
        f"Replaced the hardcoded value of `{name}` with `process.env.{name}`. "
        "Rotate the leaked credential and set the variable in your environment.",
        0.6,
    )


def apply_fixer(
    rule_id: str,
    source: str,
    finding: Dict[str, object],
    language: str,
    validate: bool = True,
) -> Optional[FixResult]:
    """Runs the fixer registered for ``rule_id`` (``None`` when unavailable).

    The fixer is only used when it targets the snippet's language family, so a
    Python rewrite can never be injected into JavaScript, Ruby, PHP and friends.
    ``validate=False`` skips the internal re-parse; only pass it when the caller
    validates the returned source itself.
    """
    rule_id = str(rule_id or "")
    fixer = FIXERS.get(rule_id)
    if fixer is None:
        return None
    if not family_matches(fixer_families(rule_id), language):
        return None
    if rule_id in {"SEC101", "SEC103"} and family_matches(("js",), language):
        fixer = fix_hardcoded_secret_js
    token = _VALIDATE_PATCHES.set(bool(validate))
    try:
        return fixer(source, finding, language)
    except Exception:  # pragma: no cover - a fixer must never break the engine
        return None
    finally:
        _VALIDATE_PATCHES.reset(token)


def manual_hint(rule_id: str, suggestion: Optional[str] = None) -> str:
    return MANUAL_HINTS.get(str(rule_id or "")) or suggestion or (
        "No automatic patch is available for this finding; apply the suggested fix manually."
    )


def supported_rule_ids() -> List[str]:
    return sorted(FIXERS)
