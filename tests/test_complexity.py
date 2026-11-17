"""Complexity and maintainability metrics."""
import ast

from analyzer.complexity import (
    generic_metrics,
    halstead_volume,
    maintainability_index,
    node_complexity,
    python_function_metrics,
    python_metrics,
)


def test_simple_function_has_complexity_one():
    tree = ast.parse("def f(x):\n    return x\n")
    assert node_complexity(tree.body[0]) == 1


def test_branching_increases_complexity():
    source = (
        "def f(x):\n"
        "    if x > 1 and x < 10:\n"
        "        return 1\n"
        "    elif x == 0:\n"
        "        return 0\n"
        "    for i in range(x):\n"
        "        if i:\n"
        "            return i\n"
        "    return -1\n"
    )
    tree = ast.parse(source)
    assert node_complexity(tree.body[0]) >= 5


def test_python_metrics_report_functions_and_classes():
    source = (
        '"""Doc."""\n'
        "class A:\n"
        "    def method(self):\n"
        "        return 1\n"
        "def free():\n"
        "    return 2\n"
    )
    metrics = python_metrics(source)
    assert metrics["class_count"] == 1
    assert metrics["function_count"] == 2
    assert metrics["lines_of_code"] >= 5
    assert 0 <= metrics["maintainability_index"] <= 100


def test_function_metrics_include_nesting_and_length():
    source = "def f():\n    if True:\n        for i in range(3):\n            print(i)\n"
    functions = python_function_metrics(ast.parse(source))
    assert functions[0]["nesting"] >= 2
    assert functions[0]["length"] == 4


def test_halstead_volume_is_positive():
    assert halstead_volume("a = b + c * 2\n") > 0


def test_maintainability_index_bounds():
    assert maintainability_index(10, 2, 100) > maintainability_index(500, 60, 5000)
    assert 0 <= maintainability_index(1, 1, 1) <= 100


def test_generic_metrics_for_javascript():
    source = "function a() {\n  if (x) { return 1; }\n}\nfunction b() { return 2; }\n"
    metrics = generic_metrics(source, "JavaScript")
    assert metrics["function_count"] >= 2
    assert metrics["max_complexity"] >= 2
