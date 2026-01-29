"""Version management for GastroPilot Backend.

Reads version from VERSION file or falls back to environment variable.
"""

import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def get_version() -> str:
    """Get the current version of the application.

    Priority:
    1. VERSION file in project root
    2. APP_VERSION environment variable
    3. Fallback to "0.0.0-dev"
    """
    # Try VERSION file first (in project root, one level up from app/)
    version_file = Path(__file__).parent.parent / "VERSION"
    if version_file.exists():
        version = version_file.read_text().strip()
        if version:
            return version

    # Try environment variable
    env_version = os.getenv("APP_VERSION")
    if env_version:
        return env_version

    # Fallback
    return "0.0.0-dev"


# Export version string
VERSION = get_version()
