"""Display discovery through KScreen and KWin's output configuration."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import DisplayInfo, DisplayLookupError
from .identity import assign_identities

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")
PNP_NAMES = {
    "ACR": "Acer",
    "AOC": "AOC",
    "ASU": "ASUS",
    "AUO": "AU Optronics",
    "BNQ": "BenQ",
    "BOE": "BOE",
    "CMN": "Chimei Innolux",
    "DEL": "Dell",
    "EIZ": "EIZO",
    "GSM": "LG",
    "HWP": "HP",
    "HSD": "HannStar",
    "IVM": "Iiyama",
    "LEN": "Lenovo",
    "LGD": "LG Display",
    "MSI": "MSI",
    "PHL": "Philips",
    "PCP": "Packard Bell",
    "SAM": "Samsung",
    "SDC": "Samsung Display",
    "SHP": "Sharp",
    "SNY": "Sony",
    "VSC": "ViewSonic",
}

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")


class DiscoveryError(Exception):
    """Raised when the KScreen output service cannot be queried."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class DiscoveryResult:
    displays: list[DisplayInfo] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def active(self) -> list[DisplayInfo]:
        return [display for display in self.displays if display.connected and display.enabled]

    @property
    def connected(self) -> list[DisplayInfo]:
        return [display for display in self.displays if display.connected]

    def by_name(self, output_name: str) -> DisplayInfo | None:
        for display in self.displays:
            if display.output_name == output_name:
                return display
        return None


Runner = Callable[[Sequence[str]], CommandResult]


class SubprocessRunner:
    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout

    def __call__(self, command: Sequence[str]) -> CommandResult:
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        env.setdefault("LANG", "C")
        for key in (
            "QT_QPA_PLATFORM",
            "QT_QPA_PLATFORMTHEME",
            "QT_SCALE_FACTOR",
            "QT_SCREEN_SCALE_FACTORS",
            "QT_STYLE_OVERRIDE",
        ):
            env.pop(key, None)
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                env=env,
            )
        except FileNotFoundError as exc:
            return CommandResult(127, "", str(exc))
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", "command timed out")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _decode_pnp(value: int) -> str:
    return "".join(chr(64 + ((value >> shift) & 0x1F)) for shift in (10, 5, 0))


def parse_edid(data: bytes) -> dict[str, Any]:
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return {}
    if sum(data[:128]) % 256 != 0:
        return {}
    pnp = _decode_pnp((data[8] << 8) | data[9])
    product_code = data[10] | (data[11] << 8)
    serial_number = int.from_bytes(data[12:16], "little")
    week = data[16]
    year = 1990 + data[17]
    descriptors: dict[int, str] = {}
    for offset in range(54, 126, 18):
        descriptor = data[offset : offset + 18]
        if len(descriptor) < 18:
            continue
        if descriptor[0:2] != b"\x00\x00" or descriptor[2] != 0:
            continue
        tag = descriptor[3]
        if tag not in (0xFC, 0xFE, 0xFF):
            continue
        raw = descriptor[5:18].split(b"\x0a", 1)[0]
        text = raw.decode("ascii", "replace").replace("\x00", "").strip()
        text = "".join(character for character in text if character.isprintable())
        if text and tag not in descriptors:
            descriptors[tag] = text
    manufacturer = PNP_NAMES.get(pnp, pnp)
    serial = descriptors.get(0xFF, "")
    if not serial and serial_number:
        serial = str(serial_number)
    return {
        "pnp": pnp,
        "manufacturer": manufacturer,
        "product_code": f"0x{product_code:04x}",
        "serial_number": serial_number,
        "serial": serial,
        "week": week,
        "year": year,
        "model": descriptors.get(0xFC, ""),
        "monitor_name": descriptors.get(0xFC, ""),
        "text": descriptors.get(0xFE, ""),
        "edid_identifier": f"{pnp} {product_code:04x} {serial_number} {week} {year}",
        "sha256": hashlib.sha256(data).hexdigest()[:32],
    }


def read_edid(
    connector: str,
    sysfs_root: Path = Path("/sys/class/drm"),
) -> dict[str, Any]:
    for path in sorted(sysfs_root.glob(f"card*-{connector}/edid")):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if data:
            parsed = parse_edid(data)
            if parsed:
                return parsed
    return {}


def parse_kwin_output_config(path: Path) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_read_text(path))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, list):
        return {}
    outputs: dict[str, dict[str, Any]] = {}
    for section in data:
        if not isinstance(section, dict) or section.get("name") != "outputs":
            continue
        entries = section.get("data", [])
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            connector = str(entry.get("connectorName", ""))
            if connector:
                outputs[connector] = entry
    return outputs


def _connector_type(output_name: str) -> str:
    if output_name.startswith("eDP"):
        return "eDP"
    if output_name.startswith("LVDS"):
        return "LVDS"
    if output_name.startswith("DSI"):
        return "DSI"
    if output_name.startswith("HDMI"):
        return "HDMI"
    if output_name.startswith("DP"):
        return "DisplayPort"
    if output_name.startswith("DVI"):
        return "DVI"
    if output_name.startswith("VGA"):
        return "VGA"
    return output_name.split("-", 1)[0] or "unknown"


def _is_internal(output_name: str, output_type: int) -> bool:
    return output_name.startswith(INTERNAL_PREFIXES) or output_type == 7


def _current_mode(output: dict[str, Any]) -> dict[str, Any]:
    current = str(output.get("currentModeId", ""))
    modes = output.get("modes", [])
    if isinstance(modes, list):
        for mode in modes:
            if isinstance(mode, dict) and str(mode.get("id")) == current:
                return mode
    return {}


def parse_kscreen_json(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DiscoveryError(f"could not parse kscreen-doctor JSON: {exc}") from exc
    outputs = data.get("outputs") if isinstance(data, dict) else None
    if not isinstance(outputs, list):
        raise DiscoveryError("kscreen-doctor JSON did not contain an outputs list")
    return [output for output in outputs if isinstance(output, dict)]


def parse_kscreen_text_state(text: str) -> dict[str, dict[str, str]]:
    state: dict[str, dict[str, str]] = {}
    current = ""
    for raw_line in text.splitlines():
        line = ANSI_ESCAPE.sub("", raw_line).rstrip()
        match = re.match(r"^Output:\s+\d+\s+(\S+)", line)
        if match:
            current = match.group(1)
            state[current] = {}
            continue
        if not current:
            continue
        stripped = line.strip()
        key, separator, value = stripped.partition(":")
        if not separator:
            continue
        key = key.strip().lower()
        value = value.strip()
        if key == "icc profile":
            state[current]["icc_profile_path"] = "" if value.lower() in ("", "none") else value
        elif key == "color profile source":
            state[current]["color_profile_source"] = value.upper()
        elif key == "color power preference":
            lowered = value.lower()
            if "accuracy" in lowered:
                state[current]["color_power_tradeoff"] = "PreferAccuracy"
            elif "efficiency" in lowered:
                state[current]["color_power_tradeoff"] = "PreferEfficiency"
            elif value:
                state[current]["color_power_tradeoff"] = value
    return state


def _raw_outputs(
    outputs: list[dict[str, Any]],
    text_state: dict[str, dict[str, str]],
    kwin_config: dict[str, dict[str, Any]],
    sysfs_root: Path,
) -> list[DisplayInfo]:
    displays: list[DisplayInfo] = []
    for output in outputs:
        output_name = str(output.get("name", ""))
        if not output_name:
            continue
        mode = _current_mode(output)
        size = mode.get("size", {}) if isinstance(mode, dict) else {}
        position = output.get("pos", {})
        if not isinstance(position, dict):
            position = {}
        config = kwin_config.get(output_name, {})
        edid = read_edid(output_name, sysfs_root)
        text = text_state.get(output_name, {})
        icc_profile_path = str(
            output.get("iccProfilePath")
            or config.get("iccProfilePath")
            or text.get("icc_profile_path")
            or ""
        )
        color_profile_source = str(
            text.get("color_profile_source") or config.get("colorProfileSource") or ""
        )
        color_power_tradeoff = str(
            text.get("color_power_tradeoff") or config.get("colorPowerTradeoff") or ""
        )
        manufacturer = str(edid.get("manufacturer", ""))
        model = str(edid.get("model", ""))
        serial = str(edid.get("serial", ""))
        edid_hash = str(config.get("edidHash", "") or edid.get("sha256", ""))
        edid_identifier = str(config.get("edidIdentifier", "") or edid.get("edid_identifier", ""))
        size_mm = output.get("sizeMM", {})
        if not isinstance(size_mm, dict):
            size_mm = {}
        displays.append(
            DisplayInfo(
                output_name=output_name,
                uuid=str(config.get("uuid", "")),
                edid_hash=edid_hash,
                edid_identifier=edid_identifier,
                manufacturer=manufacturer,
                model=model,
                serial=serial,
                connector_type=_connector_type(output_name),
                internal=_is_internal(output_name, int(output.get("type", 0) or 0)),
                connected=bool(output.get("connected", False)),
                enabled=bool(output.get("enabled", False)),
                width=int(size.get("width", 0) or 0),
                height=int(size.get("height", 0) or 0),
                refresh_rate=float(mode.get("refreshRate", 0.0) or 0.0),
                scale=float(output.get("scale", 1.0) or 1.0),
                x=int(position.get("x", 0) or 0),
                y=int(position.get("y", 0) or 0),
                size_width_mm=int(size_mm.get("width", 0) or 0),
                size_height_mm=int(size_mm.get("height", 0) or 0),
                icc_profile_path=icc_profile_path,
                color_profile_source=color_profile_source,
                color_power_tradeoff=color_power_tradeoff,
            )
        )
    return displays


def discover(
    runner: Runner | None = None,
    kwin_config_path: Path | None = None,
    sysfs_root: Path = Path("/sys/class/drm"),
) -> DiscoveryResult:
    command_runner = runner or SubprocessRunner()
    json_result = command_runner(["kscreen-doctor", "-j"])
    if json_result.returncode != 0 or not json_result.stdout.strip():
        detail = json_result.stderr.strip() or "kscreen-doctor is unavailable"
        raise DiscoveryError(f"could not query displays: {detail}")
    outputs = parse_kscreen_json(json_result.stdout)
    text_result = command_runner(["kscreen-doctor", "-o"])
    text_state = parse_kscreen_text_state(text_result.stdout) if text_result.returncode == 0 else {}
    if kwin_config_path is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        kwin_config_path = config_home / "kwinoutputconfig.json"
    kwin_config = parse_kwin_output_config(kwin_config_path)
    displays = _raw_outputs(outputs, text_state, kwin_config, sysfs_root)
    assign_identities(displays)
    warnings: list[str] = []
    if text_result.returncode != 0:
        warnings.append("could not read colour state from kscreen-doctor -o")
    for display in displays:
        if display.connected and display.identity and display.identity.ambiguous:
            warnings.append(
                f"{display.output_name} has an ambiguous hardware identity; "
                "automatic restoration is disabled for it"
            )
    return DiscoveryResult(displays=displays, warnings=warnings)


def _candidate_labels(displays: Iterable[DisplayInfo]) -> str:
    labels = [
        f"{display.output_name} ({display.friendly_name}, {display.stable_id})"
        for display in displays
    ]
    return ", ".join(labels) if labels else "none"


def find_display(displays: Iterable[DisplayInfo], selector: str) -> DisplayInfo:
    items = list(displays)
    needle = str(selector).strip()
    if not needle:
        raise DisplayLookupError("display selector is empty")
    checks = [
        lambda display: display.output_name,
        lambda display: display.uuid,
        lambda display: display.stable_id,
    ]
    for check in checks:
        matches = [display for display in items if check(display) == needle]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DisplayLookupError(
                f"display selector {selector!r} is ambiguous: {_candidate_labels(matches)}"
            )
    lowered = needle.lower()
    for getter in (
        lambda display: display.output_name.lower(),
        lambda display: display.uuid.lower(),
        lambda display: display.stable_id.lower(),
        lambda display: display.friendly_name.lower(),
        lambda display: display.display_name.lower(),
    ):
        matches = [display for display in items if getter(display) == lowered]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DisplayLookupError(
                f"display selector {selector!r} is ambiguous: {_candidate_labels(matches)}"
            )
    if needle.startswith("uuid-") or needle.startswith("edid-"):
        matches = [display for display in items if display.stable_id.lower().startswith(lowered)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise DisplayLookupError(
                f"display selector {selector!r} is ambiguous: {_candidate_labels(matches)}"
            )
    raise DisplayLookupError(
        f"no connected display matches {selector!r}; available: {_candidate_labels(items)}"
    )
