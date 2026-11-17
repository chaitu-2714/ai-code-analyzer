"""Python rule pack: AST based bug, security, performance, quality and docs rules."""
from __future__ import annotations

import ast
import re
from typing import Dict, List, Optional

from analyzer.complexity import _nesting_depth, node_complexity
from analyzer.rules.base import (
    Category,
    Rule,
    RuleFinding,
    Severity,
    finding_from_rule,
    register_all,
)

# ---------------------------------------------------------------------------
# Rule catalogue
# ---------------------------------------------------------------------------

PYTHON_RULES: List[Rule] = [
    # --- bugs -------------------------------------------------------------
    Rule(
        id="BUG001",
        title="Bare except clause",
        category=Category.BUG,
        severity=Severity.HIGH,
        description="A bare `except:` swallows every exception, including SystemExit and KeyboardInterrupt.",
        suggestion="Catch a specific exception type, or at least `except Exception as exc:` and log it.",
        languages=("python",),
    ),
    Rule(
        id="BUG002",
        title="Mutable default argument",
        category=Category.BUG,
        severity=Severity.MEDIUM,
        description="Mutable defaults are created once at definition time and leak state between calls.",
        suggestion="Use `None` as the default and create the container inside the function.",
        languages=("python",),
    ),
    Rule(
        id="BUG003",
        title="Comparison to None/True/False with ==",
        category=Category.BUG,
        severity=Severity.LOW,
        description="`== None` can be silently overridden by `__eq__`; identity comparison is intended here.",
        suggestion="Use `is None` / `is not None` (and `is True` / `is False`).",
        languages=("python",),
    ),
    Rule(
        id="BUG004",
        title="Unused import",
        category=Category.BUG,
        severity=Severity.LOW,
        description="The imported name is never referenced in this module.",
        suggestion="Remove the unused import or use it.",
        languages=("python",),
        detector="scope",
    ),
    Rule(
        id="BUG005",
        title="Exception silently swallowed",
        category=Category.BUG,
        severity=Severity.MEDIUM,
        description="`except Exception: pass` hides failures and makes production issues undiagnosable.",
        suggestion="Log the exception (with context) or re-raise it.",
        languages=("python",),
    ),
    Rule(
        id="BUG006",
        title="return inside finally",
        category=Category.BUG,
        severity=Severity.HIGH,
        description="Returning from `finally` discards in-flight exceptions and any pending return value.",
        suggestion="Move the return statement out of the `finally` block.",
        languages=("python",),
    ),
    Rule(
        id="BUG007",
        title="Self-assignment",
        category=Category.BUG,
        severity=Severity.LOW,
        description="A variable is assigned to itself, which is almost always a typo.",
        suggestion="Assign the intended source value.",
        languages=("python",),
    ),
    Rule(
        id="BUG008",
        title="`is` comparison with a literal",
        category=Category.BUG,
        severity=Severity.MEDIUM,
        description="Identity comparison against a literal value is unreliable across interpreters.",
        suggestion="Use `==` for value comparison and reserve `is` for None/True/False and sentinels.",
        languages=("python",),
    ),
    Rule(
        id="BUG009",
        title="assert used for runtime validation",
        category=Category.BUG,
        severity=Severity.LOW,
        description="Asserts are stripped when Python runs with `-O`, so they cannot validate input.",
        suggestion="Raise an explicit exception (e.g. ValueError) for input validation.",
        languages=("python",),
    ),
    # --- security ---------------------------------------------------------
    Rule(
        id="SEC001",
        title="Use of eval/exec",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        description="eval/exec execute arbitrary code from their input string.",
        suggestion="Use `ast.literal_eval`, `json.loads`, or an explicit mapping of allowed operations.",
        languages=("python",),
    ),
    Rule(
        id="SEC002",
        title="subprocess call with shell=True",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="`shell=True` passes the command to a shell, enabling command injection.",
        suggestion="Pass an argument list and keep `shell=False` (the default).",
        languages=("python",),
    ),
    Rule(
        id="SEC003",
        title="os.system / os.popen",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="Shell invocation through os.system/os.popen is injectable and cannot be timed out.",
        suggestion="Use `subprocess.run([...], check=True, timeout=...)`.",
        languages=("python",),
    ),
    Rule(
        id="SEC004",
        title="Unsafe deserialisation",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="pickle/marshal deserialise executable payloads and must never touch untrusted data.",
        suggestion="Use JSON or another data-only format for untrusted input.",
        languages=("python",),
    ),
    Rule(
        id="SEC005",
        title="yaml.load without SafeLoader",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="The default YAML loader can construct arbitrary Python objects.",
        suggestion="Use `yaml.safe_load(data)` or `Loader=yaml.SafeLoader`.",
        languages=("python",),
    ),
    Rule(
        id="SEC006",
        title="Hardcoded credential",
        category=Category.SECURITY,
        severity=Severity.CRITICAL,
        description="A password, token or API key is embedded directly in source code.",
        suggestion="Read the value from the environment or a secret manager and rotate the leaked value.",
        languages=("any",),
        detector="ast+regex",
    ),
    Rule(
        id="SEC007",
        title="Weak hash algorithm",
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        description="MD5/SHA-1 are broken for security purposes.",
        suggestion="Use SHA-256 or better, and a KDF (bcrypt/scrypt/argon2) for passwords.",
        languages=("python",),
    ),
    Rule(
        id="SEC008",
        title="SQL query built by string formatting",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="Interpolating values into SQL enables SQL injection.",
        suggestion="Use parameterised queries (`cursor.execute(sql, params)`).",
        languages=("python",),
    ),
    Rule(
        id="SEC009",
        title="Insecure temporary file",
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        description="`tempfile.mktemp` is race-prone and deprecated for security reasons.",
        suggestion="Use `tempfile.NamedTemporaryFile` or `tempfile.mkstemp`.",
        languages=("python",),
    ),
    Rule(
        id="SEC010",
        title="TLS verification disabled",
        category=Category.SECURITY,
        severity=Severity.HIGH,
        description="`verify=False` accepts any certificate, allowing man-in-the-middle attacks.",
        suggestion="Remove `verify=False` or point it at a trusted CA bundle.",
        languages=("python",),
    ),
    Rule(
        id="SEC011",
        title="World-writable permissions",
        category=Category.SECURITY,
        severity=Severity.MEDIUM,
        description="chmod 0o777 lets any local user modify the file.",
        suggestion="Grant the minimum required permission bits (e.g. 0o600 or 0o640).",
        languages=("python",),
    ),
    # --- performance ------------------------------------------------------
    Rule(
        id="PERF001",
        title="File opened without a context manager",
        category=Category.PERFORMANCE,
        severity=Severity.MEDIUM,
        description="`open()` outside a `with` block leaks a file descriptor when an exception occurs.",
        suggestion="Use `with open(...) as handle:`.",
        languages=("python",),
    ),
    Rule(
        id="PERF002",
        title="String concatenation inside a loop",
        category=Category.PERFORMANCE,
        severity=Severity.MEDIUM,
        description="Repeated `+=` on strings is quadratic; each step copies the whole buffer.",
        suggestion="Collect parts in a list and `''.join(parts)` once.",
        languages=("python",),
    ),
    Rule(
        id="PERF003",
        title="range(len(sequence)) indexing",
        category=Category.PERFORMANCE,
        severity=Severity.LOW,
        description="Indexing by range is slower and less readable than direct iteration.",
        suggestion="Use `for item in sequence:` or `for index, item in enumerate(sequence):`.",
        languages=("python",),
    ),
    Rule(
        id="PERF004",
        title="Triple-nested loop",
        category=Category.PERFORMANCE,
        severity=Severity.MEDIUM,
        description="Three or more nested loops multiply work and usually hide a better data structure.",
        suggestion="Flatten with a lookup dict/set, precomputed index, or `itertools.product`.",
        languages=("python",),
    ),
    # --- quality ----------------------------------------------------------
    Rule(
        id="QUA001",
        title="Function too long",
        category=Category.QUALITY,
        severity=Severity.MEDIUM,
        description="Long functions are hard to test and review.",
        suggestion="Extract cohesive blocks into well-named helper functions.",
        languages=("python",),
        detector="metric",
    ),
    Rule(
        id="QUA002",
        title="Too many parameters",
        category=Category.QUALITY,
        severity=Severity.LOW,
        description="Functions with many positional parameters are easy to call incorrectly.",
        suggestion="Group related parameters into a dataclass or configuration object.",
        languages=("python",),
        detector="metric",
    ),
    Rule(
        id="QUA003",
        title="High cyclomatic complexity",
        category=Category.QUALITY,
        severity=Severity.MEDIUM,
        description="Many independent branches make the function hard to reason about and test.",
        suggestion="Split branches into helpers, use early returns, or table-drive the logic.",
        languages=("python",),
        detector="metric",
    ),
    Rule(
        id="QUA004",
        title="Deeply nested control flow",
        category=Category.QUALITY,
        severity=Severity.MEDIUM,
        description="Deep nesting forces readers to keep too much context in mind.",
        suggestion="Use guard clauses and early returns to flatten the logic.",
        languages=("python",),
        detector="metric",
    ),
    Rule(
        id="QUA005",
        title="Wildcard import",
        category=Category.QUALITY,
        severity=Severity.LOW,
        description="`from module import *` hides where names come from and pollutes the namespace.",
        suggestion="Import the specific names you need.",
        languages=("python",),
    ),
    Rule(
        id="QUA006",
        title="print() instead of logging",
        category=Category.QUALITY,
        severity=Severity.LOW,
        description="print output cannot be levelled, filtered or redirected in production.",
        suggestion="Use the `logging` module (`logger.info(...)`).",
        languages=("python",),
    ),
    Rule(
        id="QUA007",
        title="Missing type hints",
        category=Category.QUALITY,
        severity=Severity.LOW,
        description="Untyped public functions lose editor assistance and static checking.",
        suggestion="Annotate parameters and the return value.",
        languages=("python",),
    ),
    Rule(
        id="QUA008",
        title="Shadows a builtin name",
        category=Category.QUALITY,
        severity=Severity.INFO,
        description="Rebinding a builtin (list, dict, id, type, ...) hides the builtin in this scope.",
        suggestion="Pick a different name, e.g. `items` instead of `list`.",
        languages=("python",),
    ),
    # --- documentation ----------------------------------------------------
    Rule(
        id="DOC001",
        title="Missing module docstring",
        category=Category.DOCUMENTATION,
        severity=Severity.LOW,
        description="The module has no docstring describing its purpose.",
        suggestion="Add a one-line module docstring at the top of the file.",
        languages=("python",),
    ),
    Rule(
        id="DOC002",
        title="Missing class docstring",
        category=Category.DOCUMENTATION,
        severity=Severity.LOW,
        description="The class has no docstring explaining its responsibility.",
        suggestion="Document the class, its invariants and usage.",
        languages=("python",),
    ),
    Rule(
        id="DOC003",
        title="Missing function docstring",
        category=Category.DOCUMENTATION,
        severity=Severity.MEDIUM,
        description="A public function has no docstring.",
        suggestion="Describe the purpose, arguments and return value.",
        languages=("python",),
    ),
    Rule(
        id="DOC004",
        title="Comment ratio too low",
        category=Category.DOCUMENTATION,
        severity=Severity.LOW,
        description="The file has little inline explanation relative to its size.",
        suggestion="Document non-obvious decisions and public interfaces.",
        languages=("python",),
        detector="metric",
    ),
]

register_all(PYTHON_RULES)

_RULES_BY_ID: Dict[str, Rule] = {rule.id: rule for rule in PYTHON_RULES}

_SECRET_NAME = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|auth[_-]?key|credential|client[_-]?secret)"
)
_PLACEHOLDER_HINTS = (
    "xxx",
    "changeme",
    "change-me",
    "example",
    "dummy",
    "placeholder",
    "your_",
    "your-",
    "<",
    "${",
    "***",
    "none",
)
_BUILTIN_NAMES = {
    "list",
    "dict",
    "set",
    "tuple",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "id",
    "type",
    "input",
    "filter",
    "map",
    "sum",
    "min",
    "max",
    "all",
    "any",
    "hash",
    "object",
    "next",
    "iter",
    "range",
    "vars",
    "format",
    "compile",
    "eval",
    "exec",
    "open",
    "print",
}
_SQL_KEYWORDS = re.compile(r"(?i)\b(select|insert|update|delete|drop|create|alter)\b")


def _attribute_chain(node: ast.AST) -> str:
    """Renders ``a.b.c`` (and ``a.b()``) for a call target."""
    parts: List[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    elif isinstance(current, ast.Call):
        parts.append(_attribute_chain(current.func) + "()")
    return ".".join(reversed(parts))


def _is_mutable_default(node: ast.AST) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"list", "dict", "set", "bytearray", "deque", "OrderedDict"}
    return False


def _looks_like_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def _is_world_writable(node: Optional[ast.AST]) -> bool:
    """True when a chmod mode grants permissions to other/world users."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return bool(node.value & 0o007)
    return False


class PythonRuleVisitor(ast.NodeVisitor):
    """Walks a Python AST and emits :class:`RuleFinding` objects."""

    def __init__(
        self,
        source: str,
        tree: ast.AST,
        long_function_threshold: int = 50,
        complexity_threshold: int = 10,
        max_parameters: int = 5,
        nesting_threshold: int = 4,
    ):
        self.source = source
        self.lines = source.splitlines()
        self.tree = tree
        self.long_function_threshold = long_function_threshold
        self.complexity_threshold = complexity_threshold
        self.max_parameters = max_parameters
        self.nesting_threshold = nesting_threshold
        self.findings: List[RuleFinding] = []
        self.parents: Dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[child] = parent
        self.import_bindings: Dict[str, ast.AST] = {}
        self.used_names: set = set()
        self.string_names: set = set()
        self._seen: set = set()

    # -- helpers -----------------------------------------------------------
    def _emit(self, rule_id: str, node: Optional[ast.AST], *, line: Optional[int] = None,
              end_line: Optional[int] = None, description: Optional[str] = None,
              confidence: Optional[float] = None) -> None:
        rule = _RULES_BY_ID.get(rule_id)
        if rule is None:  # pragma: no cover - defensive
            return
        start = line if line is not None else getattr(node, "lineno", None)
        end = end_line if end_line is not None else getattr(node, "end_lineno", start)
        key = (rule_id, start)
        if key in self._seen:
            return
        self._seen.add(key)
        finding = finding_from_rule(
            rule,
            line_start=start,
            line_end=end,
            column_start=getattr(node, "col_offset", None),
            description=description or rule.description,
        )
        if confidence is not None:
            finding.confidence = confidence
        self.findings.append(finding)

    # -- imports and name usage -------------------------------------------
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            binding = alias.asname or alias.name.split(".")[0]
            self.import_bindings[binding] = node
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                self._emit("QUA005", node)
                continue
            binding = alias.asname or alias.name
            self.import_bindings[binding] = node
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.used_names.add(node.id)
        elif isinstance(node.ctx, ast.Store) and node.id in _BUILTIN_NAMES:
            self._emit("QUA008", node, description=f"`{node.id}` is a builtin name.")
        self.generic_visit(node)

    # -- exception handling ------------------------------------------------
    def visit_Try(self, node: ast.Try) -> None:
        for handler in node.handlers:
            if handler.type is None:
                self._emit("BUG001", handler)
                continue
            type_name = _attribute_chain(handler.type) if isinstance(handler.type, (ast.Name, ast.Attribute)) else ""
            if type_name in {"Exception", "BaseException"} and len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                self._emit("BUG005", handler, description=f"`except {type_name}: pass` hides the failure.")
        for statement in node.finalbody:
            for child in ast.walk(statement):
                if isinstance(child, ast.Return):
                    self._emit("BUG006", child)
        self.generic_visit(node)

    # -- functions ---------------------------------------------------------
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node) -> None:
        args = node.args
        for default in list(args.defaults) + [d for d in args.kw_defaults if d is not None]:
            if _is_mutable_default(default):
                self._emit("BUG002", node, description=f"`{node.name}` uses a mutable default argument.")

        total_params = (
            len(getattr(args, "posonlyargs", []))
            + len(args.args)
            + len(args.kwonlyargs)
        )
        if total_params > self.max_parameters:
            self._emit(
                "QUA002",
                node,
                description=f"`{node.name}` takes {total_params} parameters (limit {self.max_parameters}).",
            )

        end = getattr(node, "end_lineno", node.lineno)
        length = max(end - node.lineno + 1, 1)
        if length > self.long_function_threshold:
            self._emit(
                "QUA001",
                node,
                end_line=end,
                description=f"`{node.name}` is {length} lines long (limit {self.long_function_threshold}).",
            )

        complexity = node_complexity(node)
        if complexity > self.complexity_threshold:
            self._emit(
                "QUA003",
                node,
                description=f"`{node.name}` has cyclomatic complexity {complexity} (limit {self.complexity_threshold}).",
            )

        nesting = _nesting_depth(node)
        if nesting >= self.nesting_threshold:
            self._emit(
                "QUA004",
                node,
                description=f"`{node.name}` nests control flow {nesting} levels deep.",
            )

        if not ast.get_docstring(node) and not node.name.startswith("_"):
            self._emit("DOC003", node, description=f"Public function `{node.name}` has no docstring.")

        annotated = [a for a in args.args if a.annotation is not None]
        if (
            not node.name.startswith("_")
            and node.returns is None
            and args.args
            and len(annotated) < len(args.args)
        ):
            self._emit("QUA007", node, description=f"`{node.name}` is missing parameter/return type hints.")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not ast.get_docstring(node):
            self._emit("DOC002", node, description=f"Class `{node.name}` has no docstring.")
        self.generic_visit(node)

    # -- expressions -------------------------------------------------------
    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant) and (
                comparator.value is None or isinstance(comparator.value, bool)
            ):
                self._emit("BUG003", node, description="Comparison to None/True/False uses `==`.")
            if isinstance(op, (ast.Is, ast.IsNot)) and isinstance(comparator, ast.Constant) and not (
                comparator.value is None or isinstance(comparator.value, bool)
            ):
                self._emit("BUG008", node, description="`is` is used to compare literal values.")
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._emit("BUG009", node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Name)
            and node.targets[0].id == node.value.id
        ):
            self._emit("BUG007", node, description=f"`{node.value.id}` is assigned to itself.")

        for target in node.targets:
            if isinstance(target, ast.Name):
                self._check_secret_assignment(target.id, node.value, node)
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    self.string_names.add(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            self._check_secret_assignment(node.target.id, node.value, node)
        self.generic_visit(node)

    def _check_secret_assignment(self, name: str, value: ast.AST, node: ast.AST) -> None:
        if not _SECRET_NAME.search(name):
            return
        if not isinstance(value, ast.Constant) or not isinstance(value.value, (str, bytes)):
            return
        literal = value.value.decode("utf-8", "ignore") if isinstance(value.value, bytes) else value.value
        if not literal or _looks_like_placeholder(literal):
            return
        confidence = 0.95 if len(literal) >= 8 else 0.6
        self._emit(
            "SEC006",
            node,
            description=f"`{name}` is hardcoded in source ({len(literal)} characters).",
            confidence=confidence,
        )

    def visit_Call(self, node: ast.Call) -> None:
        name = _attribute_chain(node.func)
        bare = name.split(".")[-1]

        if name in {"eval", "exec"}:
            self._emit("SEC001", node, description=f"`{name}()` is called.")
        elif name in {"os.system", "os.popen"}:
            self._emit("SEC003", node, description=f"`{name}()` runs a shell command.")
        elif name.startswith("subprocess.") and self._has_keyword(node, "shell", True):
            self._emit("SEC002", node, description=f"`{name}(shell=True)` is used.")
        elif name in {"pickle.loads", "pickle.load", "marshal.loads", "dill.loads"}:
            self._emit("SEC004", node, description=f"`{name}()` deserialises untrusted payloads.")
        elif name in {"yaml.load", "yaml.unsafe_load"} and not self._has_safe_loader(node):
            self._emit("SEC005", node, description=f"`{name}()` without a safe loader.")
        elif name in {"hashlib.md5", "hashlib.sha1"}:
            self._emit("SEC007", node, description=f"`{name}()` is cryptographically weak.")
        elif name == "tempfile.mktemp":
            self._emit("SEC009", node)
        elif bare in {"get", "post", "put", "patch", "delete", "request", "head"} and name.startswith(
            ("requests.", "httpx.", "session.")
        ) and self._has_keyword(node, "verify", False):
            self._emit("SEC010", node, description="HTTP call disables TLS verification.")
        elif name == "os.chmod" and node.args and _is_world_writable(node.args[1] if len(node.args) > 1 else None):
            self._emit("SEC011", node)
        elif bare in {"execute", "executemany", "executescript", "raw", "text"} and node.args:
            if self._is_dynamic_sql(node.args[0]):
                self._emit("SEC008", node, description="SQL statement is built with string interpolation.")
        elif name == "open":
            if not self._inside_with(node):
                self._emit("PERF001", node)
        elif name == "print":
            self._emit("QUA006", node)
        elif name == "range" and len(node.args) == 1 and isinstance(node.args[0], ast.Call):
            inner = node.args[0]
            if isinstance(inner.func, ast.Name) and inner.func.id == "len":
                self._emit("PERF003", node)

        for keyword in node.keywords:
            if keyword.arg and _SECRET_NAME.search(keyword.arg) and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                literal = keyword.value.value
                if literal and not _looks_like_placeholder(literal):
                    self._emit(
                        "SEC006",
                        node,
                        description=f"`{keyword.arg}=` is passed a hardcoded literal.",
                        confidence=0.9,
                    )

        self.generic_visit(node)

    def _inside_with(self, node: ast.AST) -> bool:
        """True when ``node`` is the context expression of a `with` statement."""
        parent = self.parents.get(node)
        withitem_cls = getattr(ast, "withitem", None)
        if withitem_cls is not None and isinstance(parent, withitem_cls):
            parent = self.parents.get(parent)
        return isinstance(parent, (ast.With, ast.AsyncWith))

    @staticmethod
    def _has_keyword(node: ast.Call, keyword: str, expected) -> bool:
        for kw in node.keywords:
            if kw.arg == keyword and isinstance(kw.value, ast.Constant) and kw.value.value is expected:
                return True
        return False

    @staticmethod
    def _has_safe_loader(node: ast.Call) -> bool:
        for kw in node.keywords:
            if kw.arg == "Loader" and "Safe" in _attribute_chain(kw.value):
                return True
        if len(node.args) > 1 and "Safe" in _attribute_chain(node.args[1]):
            return True
        return False

    @staticmethod
    def _is_dynamic_sql(node: ast.AST) -> bool:
        if isinstance(node, ast.JoinedStr):
            return True
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and _SQL_KEYWORDS.search(child.value):
                    return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and _SQL_KEYWORDS.search(child.value):
                    return True
        return False

    # -- loops -------------------------------------------------------------
    def visit_For(self, node: ast.For) -> None:
        self._check_loop(node)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._check_loop(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_loop(node)
        self.generic_visit(node)

    def _check_loop(self, node) -> None:
        for statement in node.body:
            if isinstance(statement, ast.AugAssign) and isinstance(statement.op, ast.Add):
                target = statement.target
                is_string_target = isinstance(target, ast.Name) and target.id in self.string_names
                is_string_literal = isinstance(statement.value, ast.Constant) and isinstance(
                    statement.value.value, str
                )
                if is_string_literal or is_string_target:
                    self._emit("PERF002", statement)
            elif isinstance(statement, ast.Assign) and isinstance(statement.value, ast.BinOp):
                value = statement.value
                if (
                    isinstance(value.op, ast.Add)
                    and isinstance(value.left, ast.Name)
                    and isinstance(value.right, ast.Constant)
                    and isinstance(value.right.value, str)
                    and any(isinstance(t, ast.Name) and t.id == value.left.id for t in statement.targets)
                ):
                    self._emit("PERF002", statement)

        depth = 1 + self._loop_depth(node)
        if depth >= 3 and not isinstance(self.parents.get(node), (ast.For, ast.AsyncFor, ast.While)):
            self._emit("PERF004", node, description=f"Loop nests {depth} levels deep.")

    def _loop_depth(self, node: ast.AST) -> int:
        best = 0
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.AsyncFor, ast.While)):
                best = max(best, 1 + self._loop_depth(child))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            else:
                best = max(best, self._loop_depth(child))
        return best

    # -- finalisation ------------------------------------------------------
    def finalize(self) -> List[RuleFinding]:
        for binding, node in self.import_bindings.items():
            if binding not in self.used_names:
                self._emit(
                    "BUG004",
                    node,
                    description=f"`{binding}` is imported but never used.",
                )
        return self.findings


def analyze_python(
    source: str,
    path: str = "<unknown>",
    long_function_threshold: int = 50,
    complexity_threshold: int = 10,
    max_parameters: int = 5,
    nesting_threshold: int = 4,
) -> List[RuleFinding]:
    """Runs the whole Python rule pack over ``source``.

    Raises :class:`SyntaxError` when the module cannot be parsed.
    """
    tree = ast.parse(source, filename=path)
    visitor = PythonRuleVisitor(
        source=source,
        tree=tree,
        long_function_threshold=long_function_threshold,
        complexity_threshold=complexity_threshold,
        max_parameters=max_parameters,
        nesting_threshold=nesting_threshold,
    )
    if not ast.get_docstring(tree):
        visitor._emit("DOC001", None, line=1, description="Module has no docstring.")

    visitor.visit(tree)
    findings = visitor.finalize()

    # Comment-ratio rule (DOC004) for sizeable modules.
    lines = source.splitlines()
    code_lines = [line for line in lines if line.strip()]
    comment_lines = [line for line in code_lines if line.strip().startswith("#")]
    if len(code_lines) >= 40 and (len(comment_lines) / max(len(code_lines), 1)) < 0.02:
        visitor._emit(
            "DOC004",
            None,
            line=1,
            description=f"Only {len(comment_lines)} comment lines for {len(code_lines)} code lines.",
        )
    return findings
