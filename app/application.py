import logging
import sys
from typing import Optional

from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import Config
from core.exceptions import ConfigurationError, DatabaseError
from core.logger import setup_logger
from database.connection import DatabaseManager
from database.repository import ProjectRepository, ReviewSessionRepository
from ui.main_window import MainWindow

logger = logging.getLogger(__name__)

class AIReviewerApplication:
    """Orchestrates app boot process, configuration loading, database connection, and GUI initialization."""
    def __init__(self, env_path: Optional[str] = None):
        self.env_path = env_path
        self.config = None
        self.db_manager = None
        self.app = None
        self.main_window = None

    def initialize(self) -> bool:
        """Runs the sequential startup sequence."""
        try:
            # 1. Load Configuration
            self.config = Config(self.env_path)

            # 2. Setup Logger
            setup_logger(self.config.log_level, self.config.log_file)
            logger.info("Application starting up...")
            logger.info(f"Loaded config: App Name={self.config.app_name}, Version={self.config.app_version}")

            # 3. Create the QApplication context first so UI dialogs work if DB fails
            self.app = QApplication(sys.argv)
            self.app.setApplicationName(self.config.app_name)
            self.app.setApplicationVersion(self.config.app_version)

            # 4. Initialize Database
            self.db_manager = DatabaseManager(self.config.database_url)
            self.db_manager.initialize()
            logger.info("Database connection established and verified.")
            return True

        except ConfigurationError as e:
            print(f"Configuration Critical Error: {e}")
            return False
        except DatabaseError as e:
            logger.critical(f"Database initialization failed: {e}")
            # Show Qt graphical dialog since QApplication is active
            if QApplication.instance():
                QMessageBox.critical(
                    None,
                    "Database Error",
                    f"Unable to open application database.\n\nDetails: {e}\n\nPlease check configuration and try again."
                )
            else:
                print(f"Database Critical Error: {e}")
            return False
        except Exception as e:
            logger.critical(f"Unexpected startup error: {e}", exc_info=True)
            print(f"Unexpected Critical Error: {e}")
            return False

    def run(self) -> int:
        """Executes UI event loop."""
        try:
            # Create Repositories
            project_repo = ProjectRepository(self.db_manager.ScopedSession)
            session_repo = ReviewSessionRepository(self.db_manager.ScopedSession)

            # Create and show Main Window
            self.main_window = MainWindow(
                project_repo=project_repo,
                session_repo=session_repo,
                app_name=self.config.app_name,
                app_version=self.config.app_version,
                config=self.config,
            )
            self.main_window.show()
            logger.info("Main window successfully loaded.")

            # Start event loop
            exit_code = self.app.exec()
            logger.info("Application shutting down.")

            # Close session
            self.db_manager.remove_scoped_session()
            return exit_code
        except Exception as e:
            logger.critical(f"Runtime error: {e}", exc_info=True)
            return 1
