"""
Shared utility functions for the Phylax backend.
"""

import time
from datetime import datetime


def format_duration(seconds: float) -> str:
    """
    Convert a duration in seconds to a human-readable string.
    Examples: '1:23', '15:04', '1:02:30'
    """
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"


def format_timestamp(seconds: float) -> str:
    """
    Convert a timestamp in seconds to MM:SS or HH:MM:SS format.
    Same as format_duration but semantically for a point in time.
    """
    return format_duration(seconds)


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.utcnow().isoformat() + "Z"
