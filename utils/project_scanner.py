import fnmatch
import hashlib
import os
from typing import Dict, List, Set

# Default ignore directories
DEFAULT_IGNORE_DIRS = {
    '.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache',
    '.idea', '.vscode', 'dist', 'build', 'target', 'env', '.env'
}

# Default ignore file patterns
DEFAULT_IGNORE_FILES = {
    '*.pyc', '*.class', '*.o', '*.obj', '*.sqlite', '*.db', '*.log',
    '.DS_Store', 'Thumbs.db'
}

def calculate_sha256(file_path: str) -> str:
    """Calculates SHA-256 checksum for a file without overloading RAM."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha256.update(chunk)
        return sha256.hexdigest()
    except Exception:
        return ""

def should_ignore(path: str, root_dir: str,
                  ignore_dirs: Set[str] = DEFAULT_IGNORE_DIRS,
                  ignore_files: Set[str] = DEFAULT_IGNORE_FILES) -> bool:
    """Checks if a directory or file should be ignored during indexing."""
    rel_path = os.path.relpath(path, root_dir)
    parts = rel_path.split(os.sep)

    # Check if any parent folder is in the ignored list
    for part in parts:
        if part in ignore_dirs:
            return True

    # Check filename patterns
    filename = os.path.basename(path)
    if filename in ignore_dirs:
        return True

    for pattern in ignore_files:
        if fnmatch.fnmatch(filename, pattern):
            return True

    return False

def is_test_file(file_path: str) -> bool:
    """Heuristic check to determine if a file is a unit/integration test."""
    name = os.path.basename(file_path).lower()
    # Python: test_*.py, *_test.py
    # JS/TS: *.test.js, *.spec.js, *.test.ts
    # Java/C#: *Test.java, *Tests.cs
    # Go: *_test.go
    if (name.startswith("test_") or
        name.endswith("_test.py") or
        name.endswith("_test.go") or
        ".test." in name or
        ".spec." in name or
        "test" in os.path.splitext(name)[0]):
        return True
    return False

def is_source_file(file_path: str) -> bool:
    """Determines if the file contains original source code vs config/docs."""
    _, ext = os.path.splitext(file_path.lower())
    source_exts = {
        '.py', '.java', '.c', '.cpp', '.h', '.hpp', '.cc', '.cxx',
        '.js', '.jsx', '.ts', '.tsx', '.cs', '.go', '.php', '.rb',
        '.html', '.css', '.sh', '.bat', '.ps1'
    }
    return ext in source_exts

def scan_project_directory(root_dir: str,
                           ignore_dirs: Set[str] = None,
                           ignore_files: Set[str] = None) -> List[Dict]:
    """Scans project folder recursively and returns list of file descriptors."""
    if ignore_dirs is None:
        ignore_dirs = DEFAULT_IGNORE_DIRS
    if ignore_files is None:
        ignore_files = DEFAULT_IGNORE_FILES

    scanned_files = []
    root_abs = os.path.abspath(root_dir)

    for dirpath, dirnames, filenames in os.walk(root_abs):
        # Prune ignored directories in place to prevent os.walk from entering them
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not should_ignore(os.path.join(dirpath, d), root_abs, ignore_dirs, ignore_files)]

        for filename in filenames:
            file_abs_path = os.path.join(dirpath, filename)
            if should_ignore(file_abs_path, root_abs, ignore_dirs, ignore_files):
                continue

            rel_path = os.path.relpath(file_abs_path, root_abs)
            _, ext = os.path.splitext(filename.lower())

            scanned_files.append({
                "absolute_path": file_abs_path,
                "relative_path": rel_path,
                "file_name": filename,
                "extension": ext,
                "is_source": is_source_file(file_abs_path),
                "is_test": is_test_file(file_abs_path),
                "file_size": os.path.getsize(file_abs_path),
                "content_hash": calculate_sha256(file_abs_path)
            })

    return scanned_files
