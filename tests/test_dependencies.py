"""Dependency resolution: stdlib, local, missing and circular imports."""
from analyzer.dependencies import (
    analyze_dependencies,
    dependency_findings,
    extract_file_imports,
)


def results_for(files, **kwargs):
    return analyze_dependencies(files, **kwargs)


def test_stdlib_and_local_imports_are_resolved():
    files = [
        (1, "app/main.py", "Python", "import os\nfrom app.core import helper\n"),
        (2, "app/core.py", "Python", "import json\n"),
    ]
    results = results_for(files, check_installed=False)
    kinds = {r.imported_module: r.import_type for r in results}
    assert kinds["os"] == "stdlib"
    assert kinds["app.core"] == "local"
    assert kinds["json"] == "stdlib"
    assert all(not r.is_missing for r in results)


def test_missing_external_package_is_flagged():
    files = [(1, "a.py", "Python", "import definitely_not_a_real_module_xyz\n")]
    results = results_for(files, check_installed=True)
    assert results[0].is_missing
    assert results[0].import_type in {"external", "missing"}


def test_missing_local_module_is_flagged():
    files = [(1, "pkg/main.py", "Python", "from pkg.gone import thing\n")]
    results = results_for(files, check_installed=False)
    flagged = [r for r in results if r.is_missing]
    assert flagged and flagged[0].imported_module == "pkg.gone"


def test_circular_imports_are_detected():
    files = [
        (1, "a.py", "Python", "import b\n"),
        (2, "b.py", "Python", "import a\n"),
    ]
    results = results_for(files, check_installed=False)
    circular = [r for r in results if r.is_circular]
    assert circular, "expected at least one circular import"


def test_javascript_imports_are_parsed():
    imports = extract_file_imports(
        "import React from 'react';\nconst fs = require('fs');\nimport x from './local';\n",
        "JavaScript",
    )
    modules = {module for module, _kind in imports}
    assert {"react", "fs", "./local"}.issubset(modules)
    kinds = dict(imports)
    assert kinds["./local"] == "relative"


def test_dependency_findings_shape():
    files = [(1, "a.py", "Python", "import definitely_not_a_real_module_xyz\n")]
    results = results_for(files, check_installed=True)
    findings = dependency_findings(results, {1: "a.py"})
    assert findings and findings[0]["rule_id"] == "DEP001"
    assert findings[0]["file_path"] == "a.py"
