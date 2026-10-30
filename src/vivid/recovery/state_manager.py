"""Persistent original-state snapshots.

A snapshot is written before Vivid changes any display and is never overwritten
by a later Vivid-generated profile.  This file is the information required to
recover if the application is removed or a profile is rejected.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from ..models import OriginalState
from ..persistence.settings import atomic_write_json


def default_state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")))
    return base / "vivid" / "state.json"


class RecoveryStateManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_state_path()
        self.last_warning = ""
        self._originals: dict[str, OriginalState] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            originals = raw.get("originals", {})
            if not isinstance(originals, dict):
                raise ValueError("originals must be an object")
            for key, value in originals.items():
                if isinstance(value, dict):
                    self._originals[str(key)] = OriginalState.from_dict(value)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.last_warning = self._quarantine(exc)
            backup = self.path.with_name(self.path.name + ".bak")
            if backup.exists():
                try:
                    raw = json.loads(backup.read_text(encoding="utf-8"))
                    originals = raw.get("originals", {})
                    if isinstance(originals, dict):
                        for key, value in originals.items():
                            if isinstance(value, dict):
                                self._originals[str(key)] = OriginalState.from_dict(value)
                        self.last_warning += f"; recovered previous state from {backup}"
                except (OSError, json.JSONDecodeError, ValueError):
                    pass

    def _quarantine(self, exc: Exception) -> str:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        quarantine = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}")
        try:
            os.replace(self.path, quarantine)
            return f"recovery state was malformed ({exc}); preserved at {quarantine}"
        except OSError:
            return f"recovery state was malformed ({exc}) and could not be moved aside"

    def _save(self) -> None:
        payload = {
            "schema_version": 1,
            "originals": {
                key: original.to_dict() for key, original in sorted(self._originals.items())
            },
        }
        atomic_write_json(self.path, payload)

    def get_original(self, stable_id: str) -> OriginalState | None:
        self._load()
        return self._originals.get(stable_id)

    def all_originals(self) -> dict[str, OriginalState]:
        self._load()
        return dict(self._originals)

    def record_original(self, original: OriginalState) -> bool:
        self._load()
        if original.stable_id in self._originals:
            return False
        self._originals[original.stable_id] = original
        try:
            self._save()
        except OSError:
            self._originals.pop(original.stable_id, None)
            raise
        return True

    def mark_restored(self, stable_id: str) -> None:
        self._load()
        original = self._originals.get(stable_id)
        if original is None:
            return
        self._originals[stable_id] = OriginalState.from_dict(
            {
                **original.to_dict(),
                "restored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        self._save()

    def clear(self, stable_id: str) -> None:
        self._load()
        if stable_id in self._originals:
            self._originals.pop(stable_id)
            self._save()

    def snapshot(self) -> dict[str, Any]:
        self._load()
        return {
            "path": str(self.path),
            "warning": self.last_warning,
            "originals": {key: original.to_dict() for key, original in self._originals.items()},
        }
