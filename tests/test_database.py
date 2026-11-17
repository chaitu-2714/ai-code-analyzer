import pytest

from database.connection import DatabaseManager
from database.repository import ProjectRepository, ReviewSessionRepository


@pytest.fixture
def db_manager():
    """Initializes in-memory SQLite database for testing."""
    manager = DatabaseManager("sqlite:///:memory:")
    manager.initialize()
    return manager

@pytest.fixture
def project_repo(db_manager):
    return ProjectRepository(db_manager.get_session)

@pytest.fixture
def session_repo(db_manager):
    return ReviewSessionRepository(db_manager.get_session)

def test_database_initialization(db_manager):
    """Verify engine and session factory are setup correctly."""
    assert db_manager.engine is not None
    assert db_manager.get_session() is not None

def test_project_crud(project_repo):
    """Test creating, listing, and deleting a project record."""
    # Create project
    proj = project_repo.create(
        name="Test Project",
        description="Test Desc",
        language="Python",
        source_path="/home/test"
    )
    assert proj.id is not None
    assert proj.name == "Test Project"

    # List all
    all_projects = project_repo.list_all()
    assert len(all_projects) == 1
    assert all_projects[0].name == "Test Project"

    # Retrieve by ID
    retrieved = project_repo.get_by_id(proj.id)
    assert retrieved is not None
    assert retrieved.name == "Test Project"

    # Delete project
    deleted = project_repo.delete(proj.id)
    assert deleted is True

    # Confirm it's gone
    assert project_repo.get_by_id(proj.id) is None
    assert len(project_repo.list_all()) == 0

def test_cascade_delete(db_manager, project_repo, session_repo):
    """Verify that deleting a project cascades and deletes linked review sessions."""
    # Create project
    proj = project_repo.create("Cascade Project")

    # Create review session linked to this project
    session = session_repo.create(project_id=proj.id, status="completed", overall_score=85.5)
    assert session.id is not None

    # Check session count is 1
    assert session_repo.count() == 1
    assert session_repo.get_average_score() == 85.5

    # Delete project
    project_repo.delete(proj.id)

    # Check session is also deleted due to CASCADE relation
    assert session_repo.count() == 0
    assert session_repo.get_average_score() is None
