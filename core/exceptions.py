class ApplicationError(Exception):
    """Base exception for the AI Code Reviewer platform."""

class ConfigurationError(ApplicationError):
    """Raised when there is a configuration error."""

class DatabaseError(ApplicationError):
    """Raised when database connection or operations fail."""

class ProjectError(ApplicationError):
    """Raised when project CRUD operations fail."""

class AnalysisError(ApplicationError):
    """Raised when code analysis operations fail."""

class LLMError(ApplicationError):
    """Raised when LLM calls or parsing fails."""

class RepairError(ApplicationError):
    """Raised when automated code repair fails."""

class VerificationError(ApplicationError):
    """Raised when verifying a repair fails."""
