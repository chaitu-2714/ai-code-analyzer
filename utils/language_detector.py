import os

EXTENSION_MAP = {
    '.py': 'Python',
    '.pyw': 'Python',
    '.java': 'Java',
    '.c': 'C',
    '.h': 'C/C++ Header',
    '.cpp': 'C++',
    '.cc': 'C++',
    '.cxx': 'C++',
    '.hpp': 'C++ Header',
    '.js': 'JavaScript',
    '.jsx': 'JavaScript (JSX)',
    '.ts': 'TypeScript',
    '.tsx': 'TypeScript (TSX)',
    '.cs': 'C#',
    '.go': 'Go',
    '.php': 'PHP',
    '.rb': 'Ruby',
    '.md': 'Markdown',
    '.txt': 'Text',
    '.json': 'JSON',
    '.xml': 'XML',
    '.yaml': 'YAML',
    '.yml': 'YAML',
    '.toml': 'TOML',
    '.sh': 'Shell',
    '.bat': 'Batch',
    '.ps1': 'PowerShell',
    '.html': 'HTML',
    '.css': 'CSS'
}

def detect_language(file_path: str) -> str:
    """Detects programming language from extension or file shebang header."""
    _, ext = os.path.splitext(file_path.lower())

    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]

    # Heuristics for shebang lines in extensionless files
    if ext == "" and os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                first_line = f.readline()
                if first_line.startswith("#!"):
                    if "python" in first_line:
                        return "Python"
                    elif "node" in first_line or "sh" in first_line or "bash" in first_line:
                        if "node" in first_line:
                            return "JavaScript"
                        return "Shell"
        except Exception:
            pass

    return "Unknown"
