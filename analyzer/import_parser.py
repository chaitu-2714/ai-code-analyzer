import re
from typing import List, Set

# Regex patterns for import extractions
PYTHON_IMPORT_REGEX = re.compile(r'^\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)', re.MULTILINE)
JS_IMPORT_REGEX = re.compile(r'^\s*import\s+.*?\s+from\s+[\'"]([@a-zA-Z0-9_\-\.\/]+)[\'"]', re.MULTILINE)
JS_REQUIRE_REGEX = re.compile(r'\brequire\s*\(\s*[\'"]([@a-zA-Z0-9_\-\.\/]+)[\'"]\s*\)')

def extract_python_imports(content: str) -> Set[str]:
    """Extracts top-level module names from Python source."""
    imports = set()
    for line in content.splitlines():
        match = PYTHON_IMPORT_REGEX.match(line)
        if match:
            # Extract first module name before any dot (e.g. from os.path import ... -> os)
            module = match.group(1).split('.')[0]
            if module != 'import' and module != 'from':
                imports.add(module)
    return imports

def extract_js_ts_imports(content: str) -> Set[str]:
    """Extracts npm modules or relative paths from JS/TS source."""
    imports = set()
    # ES6 imports
    for match in JS_IMPORT_REGEX.finditer(content):
        # Extract base package name (e.g. @angular/core -> @angular/core or react/jsx-runtime -> react)
        pkg = match.group(1)
        if not pkg.startswith('.'):  # Ignore local relative imports for dependency lists
            imports.add(pkg)

    # CommonJS requires
    for match in JS_REQUIRE_REGEX.finditer(content):
        pkg = match.group(1)
        if not pkg.startswith('.'):
            imports.add(pkg)

    return imports

def extract_imports(content: str, language: str) -> List[str]:
    """Extracts library dependencies from a source file based on language."""
    lang_lower = language.lower()
    if "python" in lang_lower:
        return list(extract_python_imports(content))
    elif any(x in lang_lower for x in ["javascript", "typescript"]):
        return list(extract_js_ts_imports(content))
    return []
