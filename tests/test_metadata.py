import os
import tempfile

from utils.metadata_extractor import extract_file_metrics
from utils.project_scanner import calculate_sha256


def test_file_metrics_extraction():
    """Verify that file metrics (lines, comments, blank lines) are calculated correctly."""
    code_content = """# Python mock code file
def greet():
    # Print welcome greeting
    print("Welcome!")

    # End
"""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as f:
        f.write(code_content)
        temp_path = f.name

    try:
        metrics = extract_file_metrics(temp_path, "Python")

        # Verify counts
        assert metrics["line_count"] == 6
        assert metrics["blank_lines"] == 1
        assert metrics["comment_lines"] == 3
        assert metrics["non_empty_lines"] == 5
        assert metrics["char_count"] == len(code_content)
        assert metrics["token_estimate"] == int(len(code_content) / 4)
    finally:
        os.remove(temp_path)

def test_hashing_identity():
    """Verify SHA-256 hash yields matching outcomes for equivalent code contents."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as f1:
        f1.write("print('hello')")
        path1 = f1.name

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as f2:
        f2.write("print('hello')")
        path2 = f2.name

    try:
        hash1 = calculate_sha256(path1)
        hash2 = calculate_sha256(path2)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest length
    finally:
        os.remove(path1)
        os.remove(path2)
