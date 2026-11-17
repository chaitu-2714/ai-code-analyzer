import os
from typing import Optional

from dotenv import load_dotenv

from core.constants import (
    DEFAULT_APP_NAME,
    DEFAULT_APP_VERSION,
    DEFAULT_DATABASE_URL,
    DEFAULT_DEBUG_MODE,
    DEFAULT_LOG_FILE,
    DEFAULT_LOG_LEVEL,
)
from core.exceptions import ConfigurationError


def _as_int(value, default: int) -> int:
    """Best-effort integer parsing for optional environment values."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clean_model(value, default: str = "gemini-3.8-flash") -> str:
    """Rejects placeholder model names such as ``YOUR_SUPPORTED_GEMINI_MODEL``."""
    text = str(value or "").strip().strip('"').strip("'")
    text = text.removeprefix("models/")
    lowered = text.lower()
    if not text or any(token in lowered for token in ("your_", "placeholder", "model_name", "xxx")):
        return default
    return text


def _as_float(value, default: float) -> float:
    """Best-effort float parsing for optional environment values."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


class Config:
    """Application configuration management."""
    def __init__(self, env_path: Optional[str] = None):
        # Load environment variables
        if env_path:
            load_dotenv(dotenv_path=env_path, override=True)
        else:
            load_dotenv(override=True)

        self.app_name = os.getenv("APP_NAME", DEFAULT_APP_NAME)
        self.app_version = os.getenv("APP_VERSION", DEFAULT_APP_VERSION)
        self.database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
        self.log_level = os.getenv("LOG_LEVEL", DEFAULT_LOG_LEVEL)
        self.log_file = os.getenv("LOG_FILE", DEFAULT_LOG_FILE)

        # Parse debug mode
        debug_mode_str = os.getenv("DEBUG_MODE", str(DEFAULT_DEBUG_MODE)).lower()
        self.debug_mode = debug_mode_str in ("true", "1", "yes", "on")

        # --- Phase 3: analysis settings -------------------------------
        self.max_file_size_bytes = _as_int(os.getenv("MAX_FILE_SIZE_BYTES"), 1_000_000)
        self.max_files_per_project = _as_int(os.getenv("MAX_FILES_PER_PROJECT"), 5_000)
        self.duplicate_window_lines = _as_int(os.getenv("DUPLICATE_WINDOW_LINES"), 6)
        self.long_function_threshold = _as_int(os.getenv("LONG_FUNCTION_THRESHOLD"), 50)
        self.complexity_threshold = _as_int(os.getenv("COMPLEXITY_THRESHOLD"), 10)

        # --- Phase 4: LLM settings ------------------------------------
        # provider: auto | local | gemini.  "auto" uses Gemini when a key is
        # present and falls back to the offline heuristic provider on any error.
        self.llm_provider = os.getenv("LLM_PROVIDER", "auto").strip().lower()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model = _clean_model(os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
        self.gemini_timeout = _as_float(os.getenv("GEMINI_TIMEOUT"), 15.0)
        self.gemini_max_retries = _as_int(os.getenv("GEMINI_MAX_RETRIES"), 1)

        # --- Phase 5: agents ------------------------------------------
        self.agents_enabled = os.getenv("AGENTS_ENABLED", "true").strip().lower() in (
            "true",
            "1",
            "yes",
            "on",
        )

        # --- Phase 7: verification ------------------------------------
        self.verify_timeout_seconds = _as_int(os.getenv("VERIFY_TIMEOUT_SECONDS"), 120)

        # Validation
        self._validate()

    def _validate(self):
        """Validates configuration values."""
        if not self.app_name.strip():
            raise ConfigurationError("APP_NAME environment variable cannot be empty.")

        if self.llm_provider not in ("auto", "local", "gemini"):
            raise ConfigurationError(
                f"LLM_PROVIDER must be one of auto, local, gemini (got '{self.llm_provider}')."
            )

        if self.llm_provider == "gemini" and not self.gemini_api_key:
            # Not fatal: the LLM factory degrades to the offline provider.
            self.llm_provider = "auto"

        # SQLite URL path check: ensure we can resolve or write relative to app directory
        if self.database_url.startswith("sqlite:///"):
            db_path = self.database_url.replace("sqlite:///", "")
            # Ensure DB directory exists
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                try:
                    os.makedirs(db_dir, exist_ok=True)
                except Exception as e:
                    raise ConfigurationError(f"Cannot create database folder '{db_dir}': {e}") from e

        # Log directory check
        log_dir = os.path.dirname(self.log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as e:
                raise ConfigurationError(f"Cannot create logs directory '{log_dir}': {e}") from e

    def get_database_path(self) -> str:
        """Helper to get actual path of sqlite database if using sqlite."""
        if self.database_url.startswith("sqlite:///"):
            return self.database_url.replace("sqlite:///", "")
        return ""
