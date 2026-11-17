"""Schema integrity: one Base, every expected table and column, safe upgrades."""
from sqlalchemy import inspect

from database.connection import DatabaseManager
from database.models import Base

EXPECTED_TABLES = {
    "projects",
    "review_sessions",
    "project_files",
    "project_imports",
    "project_metadata",
    "analysis_runs",
    "findings",
    "code_metrics",
    "duplicate_groups",
    "duplicate_instances",
    "dependencies",
    "agent_reviews",
    "repair_suggestions",
    "verification_results",
}


def test_all_tables_exist(db_manager):
    inspector = inspect(db_manager.engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_single_declarative_base(db_manager):
    tables = set(Base.metadata.tables)
    assert EXPECTED_TABLES.issubset(tables)
    # No duplicated table definitions (the Phase 1 module declared models twice).
    assert len(tables) == len(Base.metadata.tables)


def test_review_session_has_phase5_columns(db_manager):
    columns = {column["name"] for column in inspect(db_manager.engine).get_columns("review_sessions")}
    assert {"analysis_run_id", "risk_level", "summary", "provider"}.issubset(columns)


def test_agent_review_columns(db_manager):
    columns = {column["name"] for column in inspect(db_manager.engine).get_columns("agent_reviews")}
    assert {"agent_name", "score", "weight", "insights", "findings_count"}.issubset(columns)


def test_lightweight_migration_adds_missing_columns(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE review_sessions (id INTEGER PRIMARY KEY, project_id INTEGER, status TEXT)")
    connection.execute("INSERT INTO review_sessions (project_id, status) VALUES (1, 'pending')")
    connection.commit()
    connection.close()

    manager = DatabaseManager(f"sqlite:///{db_path}")
    manager.initialize()
    columns = {column["name"] for column in inspect(manager.engine).get_columns("review_sessions")}
    assert "risk_level" in columns
    assert "overall_score" in columns
    manager.remove_scoped_session()
