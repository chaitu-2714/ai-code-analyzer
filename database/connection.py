import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import scoped_session, sessionmaker

from core.exceptions import DatabaseError
from database.models import Base

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Manages SQLAlchemy engine, session lifecycle, and schema initialization."""
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = None
        self._session_factory = None
        self.ScopedSession = None

    def initialize(self):
        """Initializes database connection engine and creates tables."""
        try:
            logger.info("Initializing database with URL: %s", self.database_url)
            # Ensure check_same_thread=False for SQLite multithreaded operations in UI
            connect_args = {}
            if self.database_url.startswith("sqlite"):
                connect_args["check_same_thread"] = False

            self.engine = create_engine(self.database_url, connect_args=connect_args)

            # Verify connectivity
            with self.engine.connect():
                pass

            # Create session makers
            self._session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
            self.ScopedSession = scoped_session(self._session_factory)

            # Create tables
            Base.metadata.create_all(self.engine)

            # Upgrade databases created by earlier phases (new columns only).
            self._apply_lightweight_migrations()
            logger.info("Database initialized successfully. Database connection verified.")
        except Exception as e:
            msg = f"Failed to initialize database: {e}"
            logger.error(msg)
            raise DatabaseError(msg) from e

    def _apply_lightweight_migrations(self):
        """Adds columns that newer phases introduced on existing SQLite files.

        ``create_all`` never alters an existing table, so a database created by
        an earlier phase would be missing the new review/repair columns.  Only
        nullable additions are performed - anything destructive is left to a
        real migration tool.
        """
        if not self.database_url.startswith("sqlite"):
            return

        inspector = inspect(self.engine)
        existing_tables = set(inspector.get_table_names())
        applied = []

        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns or column.primary_key:
                    continue
                if not column.nullable:
                    continue
                column_type = column.type.compile(dialect=self.engine.dialect)
                statement = text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column_type}'
                )
                try:
                    with self.engine.begin() as connection:
                        connection.execute(statement)
                    applied.append(f"{table.name}.{column.name}")
                except Exception as error:  # pragma: no cover - defensive
                    logger.warning(
                        "Could not add column %s.%s: %s", table.name, column.name, error
                    )

        if applied:
            logger.info("Applied schema upgrades: %s", ", ".join(applied))

    def get_session(self):
        """Returns a new session."""
        if not self._session_factory:
            raise DatabaseError("Database manager not initialized. Call initialize() first.")
        return self._session_factory()

    def create_all(self):
        """Creates any missing tables (used by tests and the CLI)."""
        Base.metadata.create_all(self.engine)

    def remove_scoped_session(self):
        """Removes the thread-local scoped session if initialized."""
        if self.ScopedSession:
            self.ScopedSession.remove()
