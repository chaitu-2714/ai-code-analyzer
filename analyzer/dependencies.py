"""Dependency extraction and resolution: missing packages and circular imports."""
from __future__ import annotations

import ast
import importlib.util
import re
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from analyzer.rules.base import language_family

_STDLIB = set(getattr(sys, "stdlib_module_names", ())) or {
    "os",
    "sys",
    "re",
    "json",
    "math",
    "time",
    "datetime",
    "typing",
    "pathlib",
    "logging",
    "subprocess",
    "collections",
    "itertools",
    "functools",
    "hashlib",
    "random",
    "sqlite3",
    "unittest",
}

_JS_IMPORT = re.compile(r"""^\s*import\s+(?:[^'"]*?\s+from\s+)?['"]([^'"]+)['"]""", re.MULTILINE)
_JS_REQUIRE = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_GENERIC_IMPORT = re.compile(
    r"^\s*(?:import|use|require|include|from)\s+['\"<]?([A-Za-z_][\w./:]*)[ '\">]?", re.MULTILINE
)


@dataclass
class DependencyResult:
    file_id: int
    imported_module: str
    import_type: str  # stdlib, local, external, missing
    is_missing: bool = False
    is_circular: bool = False


@dataclass
class FileDependencyInfo:
    file_id: int
    relative_path: str
    language: str
    module_name: str
    imports: List[Tuple[str, str]]  # (module, kind) where kind in local/relative/external


def _module_name(relative_path: str) -> str:
    path = relative_path.replace("\\", "/").lstrip("./")
    path = path.removesuffix(".py")
    path = path.removesuffix("/__init__")
    return path.replace("/", ".")


def _python_imports(content: str) -> List[Tuple[str, str]]:
    """Returns (module, kind) pairs; kind is ``relative`` or ``external``."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        found: List[Tuple[str, str]] = []
        for line in content.splitlines():
            match = re.match(r"^\s*from\s+(\.*)([\w.]*)\s+import\s+", line)
            if match:
                kind = "relative" if match.group(1) else "external"
                if match.group(2):
                    found.append((match.group(2), kind))
                continue
            match = re.match(r"^\s*import\s+([\w.]+)", line)
            if match:
                found.append((match.group(1), "external"))
        return found

    imports: List[Tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, "external"))
        elif isinstance(node, ast.ImportFrom):
            kind = "relative" if node.level else "external"
            if node.module:
                imports.append((node.module, kind))
            else:
                for alias in node.names:
                    imports.append((alias.name, kind))
    return imports


def _js_imports(content: str) -> List[Tuple[str, str]]:
    imports: List[Tuple[str, str]] = []
    for match in _JS_IMPORT.finditer(content):
        module = match.group(1)
        imports.append((module, "relative" if module.startswith(".") else "external"))
    for match in _JS_REQUIRE.finditer(content):
        module = match.group(1)
        imports.append((module, "relative" if module.startswith(".") else "external"))
    return imports


def _generic_imports(content: str) -> List[Tuple[str, str]]:
    imports: List[Tuple[str, str]] = []
    for match in _GENERIC_IMPORT.finditer(content):
        module = match.group(1)
        imports.append((module, "relative" if module.startswith(".") else "external"))
    return imports


def extract_file_imports(content: str, language: Optional[str], relative_path: str = "") -> List[Tuple[str, str]]:
    family = language_family(language)
    if family == "python":
        return _python_imports(content)
    if family == "js":
        return _js_imports(content)
    if family in {"java", "go", "ruby", "php", "c", "cpp", "csharp"}:
        return _generic_imports(content)
    return []


def _is_installed(module: str) -> bool:
    """True when the top-level module can be imported in this environment."""
    top_level = module.split(".")[0].split(":")[0].split("/")[0]
    if not top_level or top_level.startswith("."):
        return True
    if top_level in _STDLIB:
        return True
    try:
        return importlib.util.find_spec(top_level) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def _is_known_local(module: str, module_index: Dict[str, int], local_packages: Set[str]) -> bool:
    """True when the exact module/package exists inside the project."""
    return module in module_index or module in local_packages


def analyze_dependencies(
    files: Sequence[Tuple[int, str, Optional[str], str]],
    check_installed: bool = True,
) -> List[DependencyResult]:
    """Resolves every import in ``files``.

    ``files`` is a sequence of ``(file_id, relative_path, language, content)``.
    """
    infos: List[FileDependencyInfo] = []
    module_index: Dict[str, int] = {}
    local_packages: Set[str] = set()
    top_level_names: Set[str] = set()

    for file_id, relative_path, language, content in files:
        module = _module_name(relative_path)
        infos.append(
            FileDependencyInfo(
                file_id=file_id,
                relative_path=relative_path,
                language=language or "",
                module_name=module,
                imports=extract_file_imports(content, language, relative_path),
            )
        )
        if module:
            module_index[module] = file_id
            top_level_names.add(module.split(".")[0])

    # Directories are namespace packages even when they have no __init__.py.
    for info in infos:
        parts = info.relative_path.replace("\\", "/").split("/")
        for depth in range(1, len(parts)):
            local_packages.add(".".join(parts[:depth]))
        if len(parts) > 1:
            top_level_names.add(parts[0])

    results: List[DependencyResult] = []
    local_edges: Dict[str, Set[str]] = {}

    for info in infos:
        seen: Set[Tuple[str, str]] = set()
        for module, kind in info.imports:
            if not module:
                continue
            key = (module, kind)
            if key in seen:
                continue
            seen.add(key)

            if kind == "relative" or module.split(".")[0] in top_level_names or module in local_packages:
                import_type = "local"
                is_missing = False
            elif module.split(".")[0] in _STDLIB:
                import_type = "stdlib"
                is_missing = False
            else:
                import_type = "external"
                is_missing = check_installed and not _is_installed(module)

            if import_type == "local":
                local_edges.setdefault(info.module_name, set()).add(module)
                if not _is_known_local(module, module_index, local_packages):
                    # Local-looking import that does not exist in the project.
                    is_missing = True
                    import_type = "missing"

            results.append(
                DependencyResult(
                    file_id=info.file_id,
                    imported_module=module,
                    import_type=import_type,
                    is_missing=is_missing,
                )
            )

    circular = _find_cycles(local_edges)
    if circular:
        for result in results:
            info = next((i for i in infos if i.file_id == result.file_id), None)
            if info is None:
                continue
            for cycle in circular:
                if info.module_name in cycle and result.imported_module in cycle:
                    result.is_circular = True
                    break

    return results


def _find_cycles(edges: Dict[str, Set[str]]) -> List[Set[str]]:
    """Tarjan-style SCC detection; returns components that form a cycle."""
    index_counter = [0]
    stack: List[str] = []
    lowlink: Dict[str, int] = {}
    index: Dict[str, int] = {}
    on_stack: Dict[str, bool] = {}
    components: List[Set[str]] = []

    def strongconnect(node: str) -> None:
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True

        for successor in edges.get(node, ()):  # only walk nodes we know about
            if successor not in edges:
                continue
            if successor not in index:
                strongconnect(successor)
                lowlink[node] = min(lowlink[node], lowlink[successor])
            elif on_stack.get(successor):
                lowlink[node] = min(lowlink[node], index[successor])

        if lowlink[node] == index[node]:
            component: Set[str] = set()
            while True:
                member = stack.pop()
                on_stack[member] = False
                component.add(member)
                if member == node:
                    break
            if len(component) > 1 or (len(component) == 1 and node in edges.get(node, ())):
                components.append(component)

    for node in list(edges):
        if node not in index:
            strongconnect(node)

    return components


def dependency_findings(results: Iterable[DependencyResult], path_by_file: Dict[int, str]) -> List[Dict[str, object]]:
    """Converts dependency results into finding payloads."""
    findings: List[Dict[str, object]] = []
    for result in results:
        if not (result.is_missing or result.is_circular):
            continue
        if result.is_circular:
            findings.append(
                {
                    "rule_id": "DEP002",
                    "category": "DEPENDENCY",
                    "severity": "HIGH",
                    "title": "Circular import",
                    "description": f"`{result.imported_module}` participates in an import cycle.",
                    "suggestion": "Break the cycle by moving shared code into a lower-level module.",
                    "file_id": result.file_id,
                    "file_path": path_by_file.get(result.file_id, ""),
                    "confidence": 0.8,
                    "detector": "dependency",
                }
            )
        elif result.is_missing:
            findings.append(
                {
                    "rule_id": "DEP001",
                    "category": "DEPENDENCY",
                    "severity": "MEDIUM",
                    "title": "Unresolved dependency",
                    "description": f"`{result.imported_module}` is imported but cannot be resolved.",
                    "suggestion": "Add the package to your dependency manifest or fix the import path.",
                    "file_id": result.file_id,
                    "file_path": path_by_file.get(result.file_id, ""),
                    "confidence": 0.7,
                    "detector": "dependency",
                }
            )
    return findings
