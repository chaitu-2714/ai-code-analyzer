import ast
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class PythonASTExtractor(ast.NodeVisitor):
    """AST visitor traversing nodes to catalog Python code structures."""
    def __init__(self):
        self.classes = []
        self.functions = []
        self.imports = []
        self.decorators = []

    def visit_ClassDef(self, node: ast.ClassDef):
        class_info = {
            "name": node.name,
            "line_number": node.lineno,
            "methods": [],
            "decorators": [self._get_decorator_name(dec) for dec in node.decorator_list]
        }

        # Traverse children to find methods inside class
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_info = {
                    "name": item.name,
                    "line_number": item.lineno,
                    "decorators": [self._get_decorator_name(dec) for dec in item.decorator_list]
                }
                class_info["methods"].append(method_info)

        self.classes.append(class_info)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        # We only treat as standalone function if it's not nested inside a class
        # (NodeVisitor traverses globally, so we filter nested methods using parent checks if needed,
        # but cataloging them in self.functions works too)
        func_info = {
            "name": node.name,
            "line_number": node.lineno,
            "decorators": [self._get_decorator_name(dec) for dec in node.decorator_list]
        }
        self.functions.append(func_info)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for name in node.names:
            self.imports.append(name.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            self.imports.append(node.module)
        self.generic_visit(node)

    def _get_decorator_name(self, node: Any) -> str:
        """Helper to get decorator string representation."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_decorator_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Call):
            return self._get_decorator_name(node.func)
        return "Unknown"

def extract_python_ast(content: str) -> Dict[str, List[Any]]:
    """Helper to parse Python source code and return its AST elements."""
    result = {
        "classes": [],
        "functions": [],
        "imports": [],
    }
    try:
        tree = ast.parse(content)
        extractor = PythonASTExtractor()
        extractor.visit(tree)

        # Filter functions that are actually class methods from the standalone list
        method_names = set()
        for cls in extractor.classes:
            for meth in cls["methods"]:
                method_names.add(meth["name"])

        standalone_functions = [
            f for f in extractor.functions if f["name"] not in method_names
        ]

        result["classes"] = extractor.classes
        result["functions"] = standalone_functions
        result["imports"] = list(set(extractor.imports))
    except SyntaxError as e:
        logger.warning(f"Syntax error during AST parsing: {e}")
    except Exception as e:
        logger.error(f"Failed to extract Python AST structures: {e}")

    return result
