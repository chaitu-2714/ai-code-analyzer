import os
import tempfile
import zipfile

from database.connection import DatabaseManager
from services.ingestion import IngestionService
from utils.project_scanner import is_source_file, is_test_file, scan_project_directory


def test_recursive_scan_and_ignores():
    """Verify recursive scanning and ignore rules omit VCS and build artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create folder structures
        src_dir = os.path.join(tmpdir, "src")
        venv_dir = os.path.join(tmpdir, ".venv")
        git_dir = os.path.join(tmpdir, ".git")

        os.makedirs(src_dir)
        os.makedirs(venv_dir)
        os.makedirs(git_dir)

        # Create mock files
        with open(os.path.join(src_dir, "main.py"), "w") as f:
            f.write("print('hello')")
        with open(os.path.join(src_dir, "test_main.py"), "w") as f:
            f.write("def test_hello(): pass")
        with open(os.path.join(venv_dir, "lib.py"), "w") as f:
            f.write("ignored")
        with open(os.path.join(tmpdir, "README.md"), "w") as f:
            f.write("# Project")

        files = scan_project_directory(tmpdir)

        rel_paths = {f["relative_path"] for f in files}

        assert os.path.join("src", "main.py") in rel_paths
        assert os.path.join("src", "test_main.py") in rel_paths
        assert "README.md" in rel_paths

        # Verify ignored paths are not returned
        assert os.path.join(".venv", "lib.py") not in rel_paths

def test_is_test_file():
    """Verify test file heuristic detections."""
    assert is_test_file("test_main.py") is True
    assert is_test_file("main_test.go") is True
    assert is_test_file("app.test.js") is True
    assert is_test_file("main.py") is False

def test_is_source_file():
    """Verify source extension detection."""
    assert is_source_file("main.py") is True
    assert is_source_file("index.css") is True
    assert is_source_file("README.md") is False

def test_zip_safety_traversal():
    """Verify that bad paths in a zip do not bypass the sandboxed directory."""
    db_manager = DatabaseManager("sqlite:///:memory:")
    db_manager.initialize()
    ingestion = IngestionService(db_manager.get_session)
    from database.repository import ProjectRepository
    repo = ProjectRepository(db_manager.get_session)
    repo.create("Safety Project")

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "test.zip")

        # Build a zip file manually containing traversals
        with zipfile.ZipFile(zip_path, 'w') as zip_file:
            zip_file.writestr("good.py", "print('good')")
            # Write a bad path traversal entry
            zip_file.writestr("../traversal.py", "print('bad')")

        # Try extracting/importing
        # Project ID 1
        ingestion.import_zip_archive(1, zip_path)

        workspace_dir = ingestion.get_workspace_path(1)
        assert os.path.exists(os.path.join(workspace_dir, "good.py")) is True
        # Traversal file must be rejected and not written outside workspace
        assert os.path.exists(os.path.join(os.path.dirname(workspace_dir), "traversal.py")) is False
