"""Atomic, versioned JSON settings storage."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from .. import CONFIG_SCHEMA_VERSION
from ..models import SettingsData
from .migration import MigrationError, migrate_settings


def default_config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "vivid" / "config.json"


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path, payload: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(path.parent, 0o700)
    serialised = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    json.loads(serialised)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialised)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            with contextlib.suppress(OSError):
                shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()
        self.last_warning = ""

    def load(self) -> SettingsData:
        self.last_warning = ""
        if not self.path.exists():
            return SettingsData(schema_version=CONFIG_SCHEMA_VERSION)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return migrate_settings(raw)
        except (OSError, json.JSONDecodeError, MigrationError, TypeError, ValueError) as exc:
            self.last_warning = self._quarantine(exc)
            backup = self.path.with_name(self.path.name + ".bak")
            if backup.exists():
                try:
                    raw = json.loads(backup.read_text(encoding="utf-8"))
                    restored = migrate_settings(raw)
                    self.last_warning += f"; recovered previous configuration from {backup}"
                    return restored
                except (OSError, json.JSONDecodeError, MigrationError, TypeError, ValueError):
                    pass
            return SettingsData(schema_version=CONFIG_SCHEMA_VERSION)

    def _quarantine(self, exc: Exception) -> str:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        quarantine = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
        try:
            os.replace(self.path, quarantine)
            return f"configuration was malformed ({exc}); preserved at {quarantine}"
        except OSError:
            return f"configuration was malformed ({exc}) and could not be moved aside"

    def save(self, settings: SettingsData) -> None:
        settings.schema_version = CONFIG_SCHEMA_VERSION
        payload = settings.to_dict()
        SettingsData.from_dict(json.loads(json.dumps(payload)))
        atomic_write_json(self.path, payload)

    def export_to(self, path: Path) -> Path:
        settings = self.load()
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(target, settings.to_dict(), mode=0o600)
        return target

    def restore_from(self, path: Path) -> SettingsData:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        settings = migrate_settings(raw)
        self.save(settings)
        return settings

    def update(self, settings: SettingsData) -> None:
        self.save(settings)
