"""Complexity, nesting and maintainability metrics.

Python is measured precisely from the AST; other languages fall back to
token/keyword heuristics which are good enough for trend tracking.
"""
from __future__ import annotations

import ast
import io
import math
import re
import tokenize
from typing import Dict, List, Optional

# Nodes that each add one independent path through a function.
_DECISION_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.Assert,
    ast.IfExp,
    ast.comprehension,
)

_KEYWORD_COMPLEXITY = re.compile(
    r"\b(if|else\s+if|elif|for|while|case|catch|except|when|\?\?|&&|\|\||\?)\b"
)
_FUNC_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?def\s+\w+", re.MULTILINE),          # Python
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+\w+", re.MULTILINE),  # JS
    re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+\w+\s*=\s*(?:async\s*)?\(", re.MULTILINE),
    re.compile(r"^\s*(?:public|private|protected|static|final|\s)*[\w<>\[\]]+\s+\w+\s*\([^;]*\)\s*\{", re.MULTILINE),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?\w+", re.MULTILINE),      # Go
    re.compile(r"^\s*(?:def|fun)\s+\w+", re.MULTILINE),               # Ruby / Kotlin
)
_CLASS_PATTERN = re.compile(r"^\s*(?:export\s+)?(?:public\s+|private\s+)?(?:class|struct|interface)\s+\w+", re.MULTILINE)
_COMMENT_PATTERN = re.compile(r"^\s*(#|//|/\*|\*|--|;)")


def _nesting_depth(node: ast.AST) -> int:
    """Maximum control-flow nesting inside ``node``."""
    depth = 0

    def walk(current: ast.AST, level: int) -> None:
        nonlocal depth
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)):
                depth = max(depth, level + 1)
                walk(child, level + 1)
            else:
                walk(child, level)

    walk(node, 0)
    return depth


def node_complexity(node: ast.AST) -> int:
    """Cyclomatic complexity of a function/method node (minimum 1)."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, ast.BoolOp):
            complexity += max(len(child.values) - 1, 1)
        elif isinstance(child, _DECISION_NODES):
            complexity += 1
        elif hasattr(ast, "Match") and isinstance(child, ast.Match):  # pragma: no cover
            complexity += max(len(child.cases) - 1, 1)
    return complexity


def python_function_metrics(tree: ast.AST) -> List[Dict[str, object]]:
    """Complexity, size and nesting for every function/method in the module."""
    results: List[Dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        results.append(
            {
                "name": node.name,
                "line": node.lineno,
                "line_end": end,
                "length": max(end - node.lineno + 1, 1),
                "complexity": node_complexity(node),
                "nesting": _nesting_depth(node),
                "parameters": len(getattr(node.args, "posonlyargs", []))
                + len(node.args.args)
                + len(node.args.kwonlyargs),
            }
        )
    return results


def halstead_volume(source: str) -> float:
    """Approximate Halstead volume from Python tokens (operators vs operands)."""
    operators, operands = set(), set()
    op_count = operand_count = 0
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.OP:
                operators.add(token.string)
                op_count += 1
            elif token.type in (tokenize.NAME, tokenize.NUMBER, tokenize.STRING):
                operands.add(token.string)
                operand_count += 1
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return max(len(source) / 4.0, 1.0)

    vocabulary = len(operators) + len(operands)
    total = op_count + operand_count
    if vocabulary <= 1 or total <= 0:
        return 1.0
    return float(total * math.log2(vocabulary))


def maintainability_index(loc: int, complexity: int, volume: float) -> float:
    """Standard (SEI) maintainability index clamped to 0-100."""
    loc = max(loc, 1)
    complexity = max(complexity, 1)
    volume = max(volume, 1.0)
    raw = 171 - 5.2 * math.log(volume) - 0.23 * complexity - 16.2 * math.log(loc)
    return round(max(0.0, min(100.0, raw * 100 / 171)), 2)


def generic_function_count(source: str, language: Optional[str] = None) -> int:
    """Heuristic function count for non-Python sources."""
    return sum(len(pattern.findall(source)) for pattern in _FUNC_PATTERNS)


def generic_metrics(source: str, language: Optional[str] = None) -> Dict[str, object]:
    """Metrics for languages without a full parser."""
    lines = source.splitlines()
    loc = sum(1 for line in lines if line.strip() and not _COMMENT_PATTERN.match(line))
    comments = sum(1 for line in lines if _COMMENT_PATTERN.match(line))
    blanks = sum(1 for line in lines if not line.strip())
    complexity = 1 + len(_KEYWORD_COMPLEXITY.findall(source))
    functions = generic_function_count(source, language)
    classes = len(_CLASS_PATTERN.findall(source))
    return {
        "lines_of_code": loc,
        "comment_lines": comments,
        "blank_lines": blanks,
        "function_count": functions,
        "class_count": classes,
        "functions": [],
        "average_complexity": round(complexity / functions, 2) if functions else float(complexity),
        "max_complexity": complexity,
        "maintainability_index": maintainability_index(loc, complexity, max(loc * 4.0, 1.0)),
    }


def python_metrics(source: str, tree: Optional[ast.AST] = None) -> Dict[str, object]:
    """Full metric set for a Python module."""
    tree = tree if tree is not None else ast.parse(source)
    lines = source.splitlines()
    loc = sum(1 for line in lines if line.strip() and not line.strip().startswith("#"))
    comments = sum(1 for line in lines if line.strip().startswith("#"))
    blanks = sum(1 for line in lines if not line.strip())
    functions = python_function_metrics(tree)
    classes = sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    complexities = [int(f["complexity"]) for f in functions]
    total_complexity = sum(complexities) + 1
    return {
        "lines_of_code": loc,
        "comment_lines": comments,
        "blank_lines": blanks,
        "function_count": len(functions),
        "class_count": classes,
        "functions": functions,
        "average_complexity": round(sum(complexities) / len(complexities), 2) if complexities else 1.0,
        "max_complexity": max(complexities) if complexities else 1,
        "total_complexity": total_complexity,
        "maintainability_index": maintainability_index(loc, total_complexity, halstead_volume(source)),
    }
