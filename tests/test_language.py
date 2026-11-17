import os
import tempfile

from utils.language_detector import detect_language


def test_language_detection_by_extension():
    """Verify that file extension maps correctly to language names."""
    assert detect_language("main.py") == "Python"
    assert detect_language("app.js") == "JavaScript"
    assert detect_language("app.ts") == "TypeScript"
    assert detect_language("main.cpp") == "C++"
    assert detect_language("index.php") == "PHP"
    assert detect_language("main.go") == "Go"
    assert detect_language("Main.java") == "Java"
    assert detect_language("Program.cs") == "C#"
    assert detect_language("docs.md") == "Markdown"
    assert detect_language("file.unknown") == "Unknown"

def test_language_detection_shebang():
    """Verify extensionless files can be detected by their shebang header."""
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
        f.write("#!/usr/bin/env python\nprint('hello')")
        temp_path = f.name

    try:
        assert detect_language(temp_path) == "Python"
    finally:
        os.remove(temp_path)
