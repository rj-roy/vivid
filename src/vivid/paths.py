"""XDG paths used by Vivid."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def _xdg(env: str, fallback: str) -> Path:
    return Path(os.environ.get(env, str(Path.home() / fallback)))


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "vivid"


def icc_dir() -> Path:
    return data_dir() / "icc"


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state") / "vivid"


def log_path() -> Path:
    return state_dir() / "vivid.log"


def config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "vivid" / "config.json"


def autostart_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "autostart" / "vivid.desktop"


def ensure_runtime_dirs() -> None:
    for path in (data_dir(), icc_dir(), state_dir()):
        path.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o700)
