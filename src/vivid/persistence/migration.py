"""Versioned configuration migrations."""

from __future__ import annotations

from typing import Any

from .. import CONFIG_SCHEMA_VERSION
from ..models import SettingsData


class MigrationError(ValueError):
    pass


def migrate_settings(raw: dict[str, Any]) -> SettingsData:
    if not isinstance(raw, dict):
        raise MigrationError("configuration root must be a JSON object")
    version = raw.get("schema_version", 1)
    try:
        version = int(version)
    except (TypeError, ValueError) as exc:
        raise MigrationError("schema_version must be an integer") from exc
    if version < 0:
        raise MigrationError("schema_version cannot be negative")
    if version > CONFIG_SCHEMA_VERSION:
        raise MigrationError(
            f"configuration schema {version} is newer than this build supports "
            f"({CONFIG_SCHEMA_VERSION})"
        )
    migrated = dict(raw)
    if version < 1:
        migrated["schema_version"] = 1
        migrated.setdefault("backend", "kwin-icc")
        migrated.setdefault("displays", {})
        migrated.setdefault("safe_mode", False)
        version = 1
    if version != CONFIG_SCHEMA_VERSION:
        migrated["schema_version"] = CONFIG_SCHEMA_VERSION
    return SettingsData.from_dict(migrated)
