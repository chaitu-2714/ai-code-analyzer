import os
import tempfile

from utils.file_validator import is_path_safe, validate_source_file


def test_valid_source_file():
    """Verify that a standard text source file validates successfully."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as f:
        f.write("def hello():\n    print('world')\n")
        temp_path = f.name

    try:
        is_valid, err = validate_source_file(temp_path)
        assert is_valid is True
        assert err == ""
    finally:
        os.remove(temp_path)

def test_unsupported_extension():
    """Verify that unsupported extensions are rejected."""
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".exe", delete=False) as f:
        f.write("mock binary exe content")
        temp_path = f.name

    try:
        is_valid, err = validate_source_file(temp_path)
        assert is_valid is False
        assert "Binary file formats" in err
    finally:
        os.remove(temp_path)

def test_oversized_file(monkeypatch):
    """Verify that files exceeding the size limit are rejected."""
    # Force size limit to 10 bytes for test
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "0.00001") # ~10 bytes

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".py", delete=False) as f:
        f.write("this is way longer than ten bytes")
        temp_path = f.name

    try:
        is_valid, err = validate_source_file(temp_path)
        assert is_valid is False
        assert "exceeds maximum limit" in err
    finally:
        os.remove(temp_path)

def test_binary_file():
    """Verify that files with null bytes are rejected as binary content."""
    with tempfile.NamedTemporaryFile(mode="wb+", suffix=".py", delete=False) as f:
        f.write(b"def hello():\n\x00\x01\x02")
        temp_path = f.name

    try:
        is_valid, err = validate_source_file(temp_path)
        assert is_valid is False
        assert "contains binary content" in err
    finally:
        os.remove(temp_path)

def test_is_path_safe():
    """Verify path safety bounds helper prevents directory traversal."""
    base_dir = "/app/workspace"
    assert is_path_safe("/app/workspace/src/main.py", base_dir) is True
    assert is_path_safe("/app/workspace/main.py", base_dir) is True
    assert is_path_safe("/app/workspace/../../etc/passwd", base_dir) is False
    assert is_path_safe("/etc/passwd", base_dir) is False
