from app.application import AIReviewerApplication


def test_application_initialization(tmp_path):
    """Verify that the AIReviewerApplication initializes configuration, logger, and DB correctly."""
    # Write a test env file
    db_file = tmp_path / "test_app.db"
    log_file = tmp_path / "test_app.log"
    env_file = tmp_path / ".env"

    env_content = f"""
APP_NAME=Test Application
APP_VERSION=1.2.3
DATABASE_URL=sqlite:///{db_file.as_posix()}
LOG_LEVEL=DEBUG
LOG_FILE={log_file.as_posix()}
DEBUG_MODE=True
"""
    env_file.write_text(env_content)

    app = AIReviewerApplication(env_path=str(env_file))

    # Initialize app boot sequence
    initialized = app.initialize()

    # Ensure it initialized successfully
    assert initialized is True
    assert app.config.app_name == "Test Application"
    assert app.config.app_version == "1.2.3"
    assert app.db_manager is not None
    assert app.app is not None

    # Clean up QApplication instance after test to prevent interference with other tests
    app.db_manager.remove_scoped_session()
