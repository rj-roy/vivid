"""ICC validation helpers used by the CLI, tests, and diagnostics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .icc_generator import (
    generate_profile_bytes,
    lcms_version,
    transform_error_report,
    validate_profile_bytes,
    validate_profile_file,
)

__all__ = [
    "generate_profile_bytes",
    "lcms_version",
    "transform_error_report",
    "validate_profile_bytes",
    "validate_profile_file",
]


def validate_profile_path(path: str | Path) -> dict[str, Any]:
    profile = Path(path)
    if not profile.is_file():
        return {"valid": False, "issues": [{"severity": "error", "message": "file not found"}]}
    return validate_profile_file(profile)
