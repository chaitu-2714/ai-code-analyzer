import logging
import os
from logging.handlers import RotatingFileHandler

from core.constants import DEFAULT_LOG_FILE, DEFAULT_LOG_LEVEL


def setup_logger(log_level: str = DEFAULT_LOG_LEVEL, log_file: str = DEFAULT_LOG_FILE):
    """Sets up the rotating file handler and console logging."""
    logger = logging.getLogger()
    # If logger is already configured, clear handlers to avoid duplication
    if logger.handlers:
        logger.handlers.clear()

    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler
    try:
        # Create directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        logger.error(f"Failed to initialize rotating file logger: {e}")

    logger.info("Logging system initialized successfully.")
    return logger
