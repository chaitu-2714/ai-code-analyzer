"""Time helpers.

The database stores timezone-naive UTC timestamps (SQLite friendly).  Using a
single helper keeps ``datetime.utcnow()`` deprecation warnings out of the code.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (matches the DB column type)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
