import os
import tempfile

import pytest

from core.config import Config
from core.exceptions import ConfigurationError


def test_config_defaults():
    """Verify that configuration loads default values when no env variables are specified."""
    # Temporarily clear environment variables to test defaults
    old_env = dict(os.environ)
    for key in ["APP_NAME", "APP_VERSION", "DATABASE_URL", "LOG_LEVEL", "LOG_FILE", "DEBUG_MODE"]:
        os.environ.pop(key, None)

    try:
        config = Config(env_path="nonexistent_file_path.env")
        assert config.app_name == "AI Code Reviewer"
        from core.constants import DEFAULT_APP_VERSION

        assert config.app_version == DEFAULT_APP_VERSION
        assert "code_reviewer.db" in config.database_url
        assert config.log_level == "INFO"
    finally:
        os.environ.update(old_env)


def test_config_env_file():
    """Verify that configuration parses env file correctly."""
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
        f.write("APP_NAME=Custom App Name\n")
        f.write("APP_VERSION=2.0.0\n")
        f.write("DATABASE_URL=sqlite:///:memory:\n")
        f.write("LOG_LEVEL=DEBUG\n")
        f.write("LOG_FILE=logs/test.log\n")
        f.write("DEBUG_MODE=False\n")
        temp_path = f.name

    try:
        config = Config(env_path=temp_path)
        assert config.app_name == "Custom App Name"
        assert config.app_version == "2.0.0"
        assert config.database_url == "sqlite:///:memory:"
        assert config.log_level == "DEBUG"
        assert config.debug_mode is False
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_invalid_config_name():
    """Verify that validation raises ConfigurationError if app name is empty."""
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
        f.write("APP_NAME=\n")
        temp_path = f.name
    try:
        with pytest.raises(ConfigurationError):
            Config(env_path=temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
