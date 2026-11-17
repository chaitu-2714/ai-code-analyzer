"""Code understanding and static analysis package (Phases 2 and 3)."""
from analyzer.ast_parser import extract_python_ast  # noqa: F401
from analyzer.complexity import (  # noqa: F401
    generic_metrics,
    maintainability_index,
    python_metrics,
)
from analyzer.dependencies import analyze_dependencies  # noqa: F401
from analyzer.duplicates import detect_duplicates  # noqa: F401
from analyzer.engine import (  # noqa: F401
    FileAnalysis,
    FileInput,
    ProjectAnalysis,
    StaticAnalysisEngine,
)
from analyzer.import_parser import extract_imports  # noqa: F401

__all__ = [
    "FileAnalysis",
    "FileInput",
    "ProjectAnalysis",
    "StaticAnalysisEngine",
    "analyze_dependencies",
    "detect_duplicates",
    "extract_imports",
    "extract_python_ast",
    "generic_metrics",
    "maintainability_index",
    "python_metrics",
]
