import os
import tempfile

import pytest

from database.connection import DatabaseManager
from database.models import ProjectFile, ProjectImport, ProjectMetadata
from database.repository import ProjectRepository
from services.ingestion import IngestionService


@pytest.fixture
def db_manager():
    manager = DatabaseManager("sqlite:///:memory:")
    manager.initialize()
    return manager

@pytest.fixture
def project_repo(db_manager):
    return ProjectRepository(db_manager.get_session)

@pytest.fixture
def ingestion_service(db_manager):
    # Set workspace directory inside temp directory
    return IngestionService(db_manager.get_session, workspace_base_dir=tempfile.mkdtemp())

def test_database_relations_indexing(project_repo, ingestion_service, db_manager):
    """Verify that importing a project workspace persists relational tables in SQLite."""
    # Create project
    proj = project_repo.create("DB Test Project")

    # Create a mock code workspace
    with tempfile.TemporaryDirectory() as code_dir:
        with open(os.path.join(code_dir, "app.py"), "w", encoding="utf-8") as f:
            f.write("import json\nimport os\nprint('db test')")

        # Run Ingestion
        success = ingestion_service.import_local_folder(proj.id, code_dir)
        assert success is True

        # Check DB Records
        with db_manager.get_session() as session:
            # Files Check
            db_files = session.query(ProjectFile).filter_by(project_id=proj.id).all()
            assert len(db_files) == 1
            app_file = db_files[0]
            assert app_file.file_name == "app.py"
            assert app_file.language == "Python"

            # Imports Check
            db_imports = session.query(ProjectImport).filter_by(project_file_id=app_file.id).all()
            assert len(db_imports) == 2
            import_names = {imp.import_name for imp in db_imports}
            assert "json" in import_names
            assert "os" in import_names

            # Metadata Check
            meta = session.query(ProjectMetadata).filter_by(project_id=proj.id).first()
            assert meta is not None
            assert meta.total_files == 1
            assert meta.source_files == 1
            assert meta.total_lines == 3
