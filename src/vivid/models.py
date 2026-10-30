"""Shared data models and validation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from . import MAX_SATURATION, MIN_SATURATION


class VividError(Exception):
    """Base class for user-facing Vivid errors."""


class ValidationError(VividError):
    """Raised when a value is outside the supported range or malformed."""


class CapabilityError(VividError):
    """Raised when the active session cannot support the requested operation."""


class DisplayLookupError(VividError):
    """Raised when a display selector is unknown or ambiguous."""


class BackendError(VividError):
    """Raised when a compositor operation fails."""


def format_percent(value: int) -> str:
    return "0%" if value == 0 else f"{value:+d}%"


class SessionType(str, Enum):
    WAYLAND = "wayland"
    X11 = "x11"
    UNKNOWN = "unknown"


class DisplayStatus(str, Enum):
    ACTIVE = "active"
    APPLYING = "applying"
    APPLIED = "applied"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    DISCONNECTED = "disconnected"
    CONFLICT = "conflict"
    NEEDS_CONFIRMATION = "needs_confirmation"


def validate_percent(value: Any) -> int:
    if isinstance(value, bool):
        raise ValidationError("saturation must be an integer between -100 and 100")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError("saturation must be a whole number between -100 and 100")
        value = int(value)
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        if not text:
            raise ValidationError("saturation must be an integer between -100 and 100")
        try:
            value = int(text, 10)
        except ValueError as exc:
            raise ValidationError("saturation must be an integer between -100 and 100") from exc
    if not isinstance(value, int):
        raise ValidationError("saturation must be an integer between -100 and 100")
    if value < MIN_SATURATION or value > MAX_SATURATION:
        raise ValidationError(f"saturation must be between {MIN_SATURATION} and {MAX_SATURATION}")
    return value


@dataclass(frozen=True)
class DisplayIdentity:
    stable_id: str
    source: str
    ambiguous: bool = False
    edid_hash: str = ""
    edid_identifier: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    uuid: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DisplayInfo:
    output_name: str
    uuid: str = ""
    edid_hash: str = ""
    edid_identifier: str = ""
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    connector_type: str = ""
    internal: bool = False
    connected: bool = False
    enabled: bool = False
    width: int = 0
    height: int = 0
    refresh_rate: float = 0.0
    scale: float = 1.0
    x: int = 0
    y: int = 0
    size_width_mm: int = 0
    size_height_mm: int = 0
    icc_profile_path: str = ""
    color_profile_source: str = ""
    color_power_tradeoff: str = ""
    identity: DisplayIdentity | None = None

    def __post_init__(self) -> None:
        if self.identity is None:
            self.identity = DisplayIdentity(
                stable_id=self.output_name,
                source="connector",
                edid_hash=self.edid_hash,
                edid_identifier=self.edid_identifier,
                manufacturer=self.manufacturer,
                model=self.model,
                serial=self.serial,
                uuid=self.uuid,
            )

    @property
    def stable_id(self) -> str:
        assert self.identity is not None
        return self.identity.stable_id

    @property
    def identity_ambiguous(self) -> bool:
        assert self.identity is not None
        return self.identity.ambiguous

    @property
    def friendly_name(self) -> str:
        label = "Built-in Display" if self.internal else "External Display"
        if self.model:
            return f"{label} ({self.model})"
        return label

    @property
    def display_name(self) -> str:
        return self.model or self.output_name

    @property
    def mode_label(self) -> str:
        if self.width and self.height:
            if self.refresh_rate:
                return f"{self.width}x{self.height} @ {self.refresh_rate:.2f} Hz"
            return f"{self.width}x{self.height}"
        return "unknown mode"

    @property
    def profile_owned_by_vivid(self) -> bool:
        name = self.icc_profile_path.rsplit("/", 1)[-1]
        return bool(name.startswith("vivid-") and name.endswith(".icc"))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["friendly_name"] = self.friendly_name
        data["display_name"] = self.display_name
        data["mode_label"] = self.mode_label
        data["stable_id"] = self.stable_id
        data["identity_ambiguous"] = self.identity_ambiguous
        data["profile_owned_by_vivid"] = self.profile_owned_by_vivid
        return data


@dataclass(frozen=True)
class CapabilityReport:
    session_type: SessionType
    compositor: str
    desktop: str
    plasma_version: str = ""
    kwin_version: str = ""
    kscreen_version: str = ""
    kscreen_doctor: bool = False
    kscreen_json: bool = False
    icc_profile_support: bool = False
    color_profile_source_support: bool = False
    output_count: int = 0
    lcms_version: str = ""
    distro: str = ""
    fedora_version: str = ""
    supported: bool = False
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    backend: str = "kwin-icc"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["session_type"] = self.session_type.value
        data["reasons"] = list(self.reasons)
        data["warnings"] = list(self.warnings)
        return data


@dataclass(frozen=True)
class OriginalState:
    stable_id: str
    output_name: str
    icc_profile_path: str
    color_profile_source: str
    color_power_tradeoff: str
    recorded_at: str
    backend: str = "kwin-icc"
    backend_versions: dict[str, str] = field(default_factory=dict)
    restored_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OriginalState:
        return cls(
            stable_id=str(data.get("stable_id", "")),
            output_name=str(data.get("output_name", "")),
            icc_profile_path=str(data.get("icc_profile_path", "")),
            color_profile_source=str(data.get("color_profile_source", "")),
            color_power_tradeoff=str(data.get("color_power_tradeoff", "")),
            recorded_at=str(data.get("recorded_at", "")),
            backend=str(data.get("backend", "kwin-icc")),
            backend_versions=dict(data.get("backend_versions", {})),
            restored_at=str(data.get("restored_at", "")),
        )


@dataclass
class ApplyResult:
    success: bool
    status: DisplayStatus
    message: str
    requested_percent: int
    applied_percent: int | None = None
    profile_path: str = ""
    verified: bool = False
    display: DisplayInfo | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        if self.display is not None:
            data["display"] = self.display.to_dict()
        return data


@dataclass
class DisplayView:
    display: DisplayInfo
    preferred_saturation: int = 0
    applied_saturation: int | None = None
    status: DisplayStatus = DisplayStatus.ACTIVE
    message: str = ""
    applied_profile_path: str = ""
    saved: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["display"] = self.display.to_dict()
        data["status"] = self.status.value
        return data


@dataclass
class DisplayPreference:
    preferred_saturation: int = 0
    last_output_name: str = ""
    last_profile_path: str = ""
    last_applied_at: str = ""
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DisplayPreference:
        percent = data.get("preferred_saturation", 0)
        try:
            percent = validate_percent(percent)
        except ValidationError:
            percent = 0
        return cls(
            preferred_saturation=percent,
            last_output_name=str(data.get("last_output_name", "")),
            last_profile_path=str(data.get("last_profile_path") or ""),
            last_applied_at=str(data.get("last_applied_at", "")),
            ambiguous=bool(data.get("ambiguous", False)),
        )


@dataclass
class SettingsData:
    schema_version: int = 1
    backend: str = "kwin-icc"
    displays: dict[str, DisplayPreference] = field(default_factory=dict)
    safe_mode: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "backend": self.backend,
            "safe_mode": self.safe_mode,
            "displays": {key: pref.to_dict() for key, pref in self.displays.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SettingsData:
        displays: dict[str, DisplayPreference] = {}
        raw_displays = data.get("displays", {})
        if isinstance(raw_displays, dict):
            for key, value in raw_displays.items():
                if isinstance(value, dict) and key:
                    displays[str(key)] = DisplayPreference.from_dict(value)
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            backend=str(data.get("backend", "kwin-icc")),
            displays=displays,
            safe_mode=bool(data.get("safe_mode", False)),
        )
