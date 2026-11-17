import logging
import os

logger = logging.getLogger(__name__)

# Default limits
DEFAULT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024   # 10 MB
DEFAULT_MAX_ZIP_SIZE_BYTES = 100 * 1024 * 1024   # 100 MB
DEFAULT_MAX_FILES_COUNT = 5000

SUPPORTED_EXTENSIONS = {
    '.py', '.pyw', '.java', '.c', '.cpp', '.h', '.hpp', '.cc', '.cxx',
    '.js', '.jsx', '.ts', '.tsx', '.cs', '.go', '.php', '.rb',
    '.md', '.txt', '.json', '.xml', '.yaml', '.yml', '.html', '.css',
    '.ini', '.toml', '.sh', '.bat', '.ps1'
}

# Binary files extensions to explicitly reject
BINARY_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib', '.bin', '.pdf', '.zip', '.tar', '.gz',
    '.rar', '.7z', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.mp3',
    '.mp4', '.avi', '.mkv', '.class', '.pyc', '.o', '.obj', '.db', '.sqlite'
}

def get_file_size_limit() -> int:
    """Gets individual file size limit in bytes from env or default."""
    try:
        limit_mb = float(os.getenv("MAX_FILE_SIZE_MB", "10"))
        return int(limit_mb * 1024 * 1024)
    except Exception:
        return DEFAULT_MAX_FILE_SIZE_BYTES

def get_zip_size_limit() -> int:
    """Gets ZIP file size limit in bytes from env or default."""
    try:
        limit_mb = float(os.getenv("MAX_ZIP_SIZE_MB", "100"))
        return int(limit_mb * 1024 * 1024)
    except Exception:
        return DEFAULT_MAX_ZIP_SIZE_BYTES

def get_max_files_limit() -> int:
    """Gets max file count limit from env or default."""
    try:
        return int(os.getenv("MAX_FILE_COUNT", "5000"))
    except Exception:
        return DEFAULT_MAX_FILES_COUNT

def is_path_safe(path: str, base_directory: str) -> bool:
    """Prevents directory traversal (../) outside base_directory."""
    try:
        abs_base = os.path.abspath(base_directory)
        abs_path = os.path.abspath(path)
        # Check if the resolved path starts with base_directory
        return os.path.commonpath([abs_base]) == os.path.commonpath([abs_base, abs_path])
    except Exception:
        return False

def is_binary_content(file_path: str) -> bool:
    """Checks if a file has binary content by scanning for null bytes."""
    try:
        if not os.path.exists(file_path):
            return False
        # Read first 1024 bytes
        with open(file_path, 'rb') as f:
            chunk = f.read(1024)
            return b'\x00' in chunk
    except Exception:
        return True

def validate_source_file(file_path: str) -> tuple[bool, str]:
    """Validates if a source file is safe, correct size, and supported.
    
    Returns (is_valid, error_message).
    """
    try:
        if not os.path.exists(file_path):
            return False, "File does not exist."

        # Size check
        size = os.path.getsize(file_path)
        if size > get_file_size_limit():
            return False, f"File size ({size / (1024*1024):.1f} MB) exceeds maximum limit ({get_file_size_limit() / (1024*1024)} MB)."

        # Extension check
        _, ext = os.path.splitext(file_path.lower())
        if ext in BINARY_EXTENSIONS:
            return False, f"Binary file formats ({ext}) are not supported."
        if ext not in SUPPORTED_EXTENSIONS and ext != "":
            return False, f"Extension '{ext}' is not supported as a source text file."

        # Read permission check
        if not os.access(file_path, os.R_OK):
            return False, "No read permission on file."

        # Content binary check
        if is_binary_content(file_path):
            return False, "File contains binary content."

        # Encoding check (try reading UTF-8)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='strict') as f:
                f.read(1024)  # Test read first part
        except UnicodeDecodeError:
            # Fallback test with latin-1 or similar can be made, but strictly UTF-8/plain text is preferred
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    f.read(1024)
            except Exception:
                return False, "File encoding is not readable as text."

        return True, ""
    except Exception as e:
        logger.error(f"Error validating file {file_path}: {e}")
        return False, f"Validation system error: {e}"
