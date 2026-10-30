"""KDE autostart integration for login restoration."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

from .paths import autostart_path


def _command() -> str:
    executable = shutil.which("vivid")
    if executable:
        return f"{shlex.quote(executable)} restore --quiet"
    return f"{shlex.quote(sys.executable)} -m vivid restore --quiet"


def _desktop_contents() -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=Vivid",
            "Comment=Restore per-display saturation settings",
            f"Exec={_command()}",
            "Icon=io.github.vivid.DisplaySaturation",
            "Terminal=false",
            "NoDisplay=true",
            "X-GNOME-Autostart-enabled=true",
            "X-KDE-autostart-after=panel",
            "OnlyShowIn=KDE;",
            "",
        ]
    )


def is_enabled() -> bool:
    return autostart_path().is_file()


def enable() -> Path:
    path = autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(_desktop_contents(), encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)
    return path


def disable() -> bool:
    path = autostart_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def status() -> dict[str, object]:
    path = autostart_path()
    return {
        "enabled": path.is_file(),
        "path": str(path),
        "command": _command() if path.is_file() else "",
    }
