"""Shared fixtures for the analysis, review, repair and reporting tests."""
import os
import sys

import pytest

# Qt must run headless in CI / sandboxes without a display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connection import DatabaseManager  # noqa: E402
from database.repository import ProjectRepository  # noqa: E402

BUGGY_SOURCE = '''import os
import sys
import pickle

API_KEY = "sk_live_9f8a7b6c5d4e3f2a1b"

def run_user_code(payload, cache=[]):
    result = eval(payload)
    cache.append(result)
    return result

def read_config(path):
    f = open(path)
    data = f.read()
    return data

def process(items):
    out = ""
    for item in items:
        out += str(item)
    for i in range(len(items)):
        print(items[i])
    return out

def risky(query):
    conn = None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE name = '%s'" % query)
    except:
        pass
    finally:
        return cursor
'''

SECOND_SOURCE = '''import subprocess
import yaml

def deploy(cmd):
    os.system(cmd)

def load(data):
    return yaml.load(data)
'''

CLEAN_SOURCE = '''"""A tidy module used to verify that clean code scores well."""

MAX_RETRIES = 3


def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right


class Calculator:
    """Tiny calculator."""

    def __init__(self) -> None:
        """Initialise the accumulator."""
        self.total = 0

    def accumulate(self, value: int) -> int:
        """Add ``value`` to the running total."""
        self.total += value
        return self.total
'''

DUPLICATE_BLOCK = '''def compute_alpha(values):
    total = 0
    count = 0
    for value in values:
        if value is not None:
            total += value
            count += 1
    average = total / count if count else 0
    return average
'''


@pytest.fixture
def db_manager(tmp_path):
    manager = DatabaseManager(f"sqlite:///{tmp_path / 'test.db'}")
    manager.initialize()
    yield manager
    manager.remove_scoped_session()


@pytest.fixture
def session_factory(db_manager):
    return db_manager.get_session


@pytest.fixture
def project_repo(session_factory):
    return ProjectRepository(session_factory)


@pytest.fixture
def sample_dir(tmp_path):
    """A small project with deliberate defects."""
    root = tmp_path / "sample"
    root.mkdir()
    (root / "bad_app.py").write_text(BUGGY_SOURCE)
    (root / "bad_app2.py").write_text(SECOND_SOURCE)
    (root / "clean_app.py").write_text(CLEAN_SOURCE)
    return root


@pytest.fixture
def indexed_project(session_factory, project_repo, sample_dir):
    """A project imported and indexed from :func:`sample_dir`."""
    from services.ingestion import IngestionService

    project = project_repo.create(name="Sample", language="Python")
    ingestion = IngestionService(session_factory, workspace_base_dir=str(sample_dir.parent / "ws"))
    ingestion.import_local_folder(project.id, str(sample_dir))
    ingestion.index_project_workspace(project.id, ingestion.get_workspace_path(project.id))
    return project
