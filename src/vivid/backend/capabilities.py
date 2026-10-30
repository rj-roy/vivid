"""Detection of the live session's colour-management capabilities."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ..color.icc_generator import lcms_version
from ..display.discovery import CommandResult, Runner, SubprocessRunner, parse_kscreen_json
from ..models import CapabilityReport, SessionType


def _read_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return values


def _first_line(result: CommandResult) -> str:
    text = (result.stdout or result.stderr).strip()
    return text.splitlines()[0] if text else ""


def _version_from_command(runner: Runner, command: list[str]) -> str:
    result = runner(command)
    if result.returncode != 0:
        return ""
    line = _first_line(result)
    match = re.search(r"(\d+(?:\.\d+)+)", line)
    return match.group(1) if match else line


def _rpm_version(package: str) -> str:
    try:
        completed = subprocess.run(
            ["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}", package],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def detect_session_type() -> SessionType:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return SessionType.WAYLAND
    if session == "x11" or os.environ.get("DISPLAY"):
        return SessionType.X11
    return SessionType.UNKNOWN


def detect_capabilities(runner: Runner | None = None) -> CapabilityReport:
    command_runner = runner or SubprocessRunner()
    reasons: list[str] = []
    warnings: list[str] = []
    os_release = _read_os_release()
    session = detect_session_type()
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    plasma_version = _version_from_command(command_runner, ["plasmashell", "--version"])
    kwin_version = _version_from_command(command_runner, ["kwin_wayland", "--version"])
    kscreen_version = _rpm_version("kscreen")
    compositor = (
        "KWin" if ("KDE" in desktop.upper() or plasma_version or kwin_version) else "unknown"
    )
    kscreen_doctor = command_runner(["kscreen-doctor", "--help"]).returncode == 0
    help_result = command_runner(["kscreen-doctor", "--help"])
    help_text = (help_result.stdout or "") + (help_result.stderr or "")
    icc_support = "iccprofile" in help_text.lower()
    source_support = "colorprofilesource" in help_text.lower()
    json_result = command_runner(["kscreen-doctor", "-j"])
    json_ok = json_result.returncode == 0 and bool(json_result.stdout.strip())
    output_count = 0
    if json_ok:
        try:
            output_count = len(parse_kscreen_json(json_result.stdout))
        except Exception:
            json_ok = False
    try:
        lcms = lcms_version()
    except Exception:
        lcms = ""
        reasons.append("Little CMS 2 (liblcms2) is not available")
    if session is not SessionType.WAYLAND:
        reasons.append(
            "a native Wayland session is required; X11 and unknown sessions are unsupported"
        )
    if compositor != "KWin" or "KDE" not in desktop.upper():
        if compositor == "KWin":
            warnings.append("XDG_CURRENT_DESKTOP does not identify KDE Plasma")
        else:
            reasons.append("KWin on KDE Plasma is the only supported compositor")
    if not kscreen_doctor:
        reasons.append("kscreen-doctor is not installed or not executable")
    elif not icc_support:
        reasons.append("the installed kscreen-doctor does not expose per-output ICC profile paths")
    elif not source_support:
        reasons.append(
            "the installed kscreen-doctor does not expose the colour profile source setting"
        )
    if not json_ok:
        reasons.append("kscreen-doctor could not enumerate outputs as JSON")
    if output_count == 0:
        reasons.append("no outputs were reported by kscreen-doctor")
    supported = not reasons
    if supported and plasma_version and not plasma_version.startswith("6.7."):
        warnings.append(
            f"Plasma {plasma_version} is not in the verified set (6.7.x); "
            "the required interfaces were detected but this version has not been hardware-tested"
        )
    if session is SessionType.WAYLAND and output_count == 1:
        warnings.append(
            "only one display is present; independent two-display behaviour cannot be tested"
        )
    distro = os_release.get("NAME", "")
    fedora_version = os_release.get("VERSION_ID", "") if os_release.get("ID") == "fedora" else ""
    if distro and not fedora_version:
        warnings.append(
            f"{distro} is not a Fedora release; packaging and testing target Fedora KDE"
        )
    return CapabilityReport(
        session_type=session,
        compositor=compositor,
        desktop=desktop,
        plasma_version=plasma_version,
        kwin_version=kwin_version,
        kscreen_version=kscreen_version,
        kscreen_doctor=kscreen_doctor,
        kscreen_json=json_ok,
        icc_profile_support=icc_support,
        color_profile_source_support=source_support,
        output_count=output_count,
        lcms_version=lcms,
        distro=distro,
        fedora_version=fedora_version,
        supported=supported,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def capability_summary(capabilities: CapabilityReport) -> dict[str, Any]:
    return capabilities.to_dict()
