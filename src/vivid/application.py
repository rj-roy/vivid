"""Application service: discovery, validation, state, and backend orchestration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import APP_VERSION
from .autostart import status as autostart_status
from .backend import KWinIccBackend, UnsupportedBackend, detect_capabilities
from .backend.base import Backend
from .color.icc_generator import (
    IccError,
    lcms_version,
    profile_prefix,
    prune_cache,
    validate_profile_file,
)
from .display.discovery import (
    DiscoveryError,
    DiscoveryResult,
    Runner,
    SubprocessRunner,
    discover,
    find_display,
)
from .logging_utils import get_logger, tail_log
from .models import (
    ApplyResult,
    CapabilityReport,
    DisplayIdentity,
    DisplayInfo,
    DisplayPreference,
    DisplayStatus,
    DisplayView,
    OriginalState,
    SettingsData,
    format_percent,
    validate_percent,
)
from .paths import autostart_path, config_path, data_dir, icc_dir, log_path, state_dir
from .persistence.settings import SettingsStore
from .recovery.state_manager import RecoveryStateManager, default_state_path

PROFILE_NAME = re.compile(r"^([+-]?\d{3})-([0-9a-f]{12})\.icc$")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class RestoreReport:
    safe_mode: bool = False
    actions: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return sum(1 for action in self.actions if action.get("success"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe_mode": self.safe_mode,
            "changed": self.changed,
            "actions": self.actions,
            "skipped": self.skipped,
            "errors": self.errors,
        }


def _resolved(value: str) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return value


class VividService:
    def __init__(
        self,
        settings_path: Path | None = None,
        state_path: Path | None = None,
        icc_directory: Path | None = None,
        runner: Runner | None = None,
        capabilities: CapabilityReport | None = None,
        discovery_function=None,
    ) -> None:
        self.log = get_logger("service")
        self.runner = runner or SubprocessRunner()
        self.settings_store = SettingsStore(settings_path or config_path())
        self.settings = self.settings_store.load()
        self.state_manager = RecoveryStateManager(state_path or default_state_path())
        self.icc_directory = Path(icc_directory or icc_dir())
        self.capabilities = capabilities or detect_capabilities(self.runner)
        self._discovery_function = discovery_function or discover
        if self.capabilities.supported:
            self.backend: Backend = KWinIccBackend(
                self.capabilities,
                self.state_manager,
                self.icc_directory,
                runner=self.runner,
                discovery_function=self._discovery_function,
            )
        else:
            self.backend = UnsupportedBackend(self.capabilities)
        self.last_errors: list[dict[str, str]] = []
        if self.settings_store.last_warning:
            self._record_error("settings", self.settings_store.last_warning)
        if self.state_manager.last_warning:
            self._record_error("recovery-state", self.state_manager.last_warning)

    def _record_error(self, category: str, message: str) -> None:
        self.last_errors.append({"at": utc_now(), "category": category, "message": message})
        self.last_errors = self.last_errors[-20:]
        self.log.error("%s: %s", category, message)

    def discover(self) -> DiscoveryResult:
        return self._discovery_function(runner=self.runner)

    def _preference(self, display: DisplayInfo) -> DisplayPreference | None:
        return self.settings.displays.get(display.stable_id)

    def _profile_percent(self, display: DisplayInfo) -> int | None:
        name = os.path.basename(display.icc_profile_path)
        prefix = profile_prefix(display.stable_id)
        if not name.startswith(prefix):
            return -1 if display.profile_owned_by_vivid else None
        match = PROFILE_NAME.match(name[len(prefix) :])
        if not match:
            return -1 if display.profile_owned_by_vivid else None
        return int(match.group(1))

    def _same_as_original(self, display: DisplayInfo, original: OriginalState | None) -> bool:
        if original is None:
            return not display.icc_profile_path
        return _resolved(display.icc_profile_path) == _resolved(original.icc_profile_path)

    def _view_for(self, display: DisplayInfo) -> DisplayView:
        preference = self._preference(display)
        percent = preference.preferred_saturation if preference else 0
        actual = self._profile_percent(display)
        vivid_active = display.profile_owned_by_vivid
        source_is_icc = display.color_profile_source.upper() == "ICC"
        power_ok = display.color_power_tradeoff == "PreferAccuracy"
        original = self.state_manager.get_original(display.stable_id)
        applied_saturation: int | None = 0
        status = DisplayStatus.ACTIVE
        message = ""
        if not self.capabilities.supported:
            status = DisplayStatus.UNSUPPORTED
            message = "; ".join(self.capabilities.reasons)
            applied_saturation = None
        elif not display.enabled:
            status = DisplayStatus.UNSUPPORTED
            message = "output is disabled in the display configuration"
            applied_saturation = None
        elif percent != 0:
            if display.identity_ambiguous:
                status = DisplayStatus.NEEDS_CONFIRMATION
                message = (
                    "this monitor's hardware identity is ambiguous; Vivid will not "
                    "restore it automatically. Select it explicitly to apply a change."
                )
            elif actual == percent and source_is_icc and power_ok:
                status = DisplayStatus.APPLIED
                message = f"{format_percent(percent)} saturation is active"
                applied_saturation = actual
            elif actual == percent and source_is_icc and not power_ok:
                status = DisplayStatus.CONFLICT
                message = (
                    "the Vivid profile is selected but the colour power preference is "
                    f"{display.color_power_tradeoff or 'unknown'}; KWin only applies the "
                    "3D table in accuracy mode"
                )
                applied_saturation = 0
            elif actual == percent and not source_is_icc:
                status = DisplayStatus.ACTIVE
                message = (
                    f"the Vivid profile is staged but the colour source is "
                    f"{display.color_profile_source or 'unknown'}, not ICC"
                )
                applied_saturation = 0
            elif vivid_active and actual not in (None, -1):
                status = DisplayStatus.CONFLICT
                message = (
                    f"a Vivid profile for {format_percent(actual)} is active but the "
                    f"saved value is {format_percent(percent)}; use Restore saved "
                    "settings or set the value again"
                )
                applied_saturation = actual
            elif vivid_active and actual == -1:
                status = DisplayStatus.CONFLICT
                message = "an unrecognised Vivid profile is active for this output"
                applied_saturation = None
            elif display.icc_profile_path and not self._same_as_original(display, original):
                status = DisplayStatus.CONFLICT
                message = (
                    "the active colour profile was changed outside Vivid; "
                    f"saved {format_percent(percent)} has not been applied"
                )
                applied_saturation = 0
            else:
                status = DisplayStatus.ACTIVE
                message = f"saved {format_percent(percent)} is not currently applied"
                applied_saturation = 0
        else:
            if vivid_active:
                status = DisplayStatus.CONFLICT
                message = (
                    "a Vivid profile is active for this output but the saved value is 0%; "
                    "use Reset to restore the original profile"
                )
                applied_saturation = actual if actual not in (None, 0) else None
            else:
                status = DisplayStatus.ACTIVE
                message = "normal profile assignment"
                applied_saturation = 0
        return DisplayView(
            display=display,
            preferred_saturation=percent,
            applied_saturation=applied_saturation,
            status=status,
            message=message,
            applied_profile_path=display.icc_profile_path,
            saved=preference is not None,
        )

    def views(self, discovery: DiscoveryResult | None = None) -> list[DisplayView]:
        result = discovery or self.discover()
        return [self._view_for(display) for display in result.connected]

    def inactive_views(self, discovery: DiscoveryResult | None = None) -> list[DisplayView]:
        result = discovery or self.discover()
        connected_ids = {display.stable_id for display in result.connected}
        views: list[DisplayView] = []
        for stable_id, preference in self.settings.displays.items():
            if stable_id in connected_ids or preference.preferred_saturation == 0:
                continue
            display = DisplayInfo(
                output_name=preference.last_output_name or stable_id,
                connected=False,
                enabled=False,
            )
            display.identity = DisplayIdentity(
                stable_id=stable_id,
                source="saved",
                ambiguous=preference.ambiguous,
            )
            views.append(
                DisplayView(
                    display=display,
                    preferred_saturation=preference.preferred_saturation,
                    status=DisplayStatus.DISCONNECTED,
                    message="saved display is not connected",
                    saved=True,
                )
            )
        return views

    def _save_settings(self) -> None:
        self.settings_store.save(self.settings)

    def _prune_cache(self, discovery: DiscoveryResult | None = None) -> None:
        keep: set[str] = set()
        for preference in self.settings.displays.values():
            if preference.last_profile_path:
                keep.add(preference.last_profile_path)
        try:
            result = discovery or self.discover()
            for display in result.connected:
                if display.icc_profile_path:
                    keep.add(display.icc_profile_path)
        except DiscoveryError:
            pass
        try:
            prune_cache(self.icc_directory, keep, max_age_seconds=30 * 24 * 3600)
        except OSError as exc:
            self.log.warning("could not prune profile cache: %s", exc)

    def _apply_preference(self, display: DisplayInfo, percent: int) -> ApplyResult:
        result = self.backend.apply(display, percent)
        if not result.success:
            self._record_error("apply", result.message)
            return result
        current = self.settings.displays.get(display.stable_id)
        preference = current or DisplayPreference()
        preference.preferred_saturation = percent
        preference.last_output_name = display.output_name
        preference.last_profile_path = result.profile_path if percent != 0 else ""
        preference.last_applied_at = utc_now()
        preference.ambiguous = display.identity_ambiguous
        self.settings.displays[display.stable_id] = preference
        try:
            self._save_settings()
        except OSError as exc:
            self._record_error("settings", f"could not save settings: {exc}")
            rollback = self.backend.reset(display)
            message = (
                f"the display was changed but settings could not be saved ({exc}); "
                "the previous profile was restored"
                if rollback.success
                else (
                    f"the display was changed but settings could not be saved ({exc}) "
                    f"and the previous profile could not be restored ({rollback.message}); "
                    "read docs/RECOVERY.md"
                )
            )
            return ApplyResult(
                success=False,
                status=DisplayStatus.FAILED,
                message=message,
                requested_percent=percent,
                display=result.display,
                details={"applied": True, "rollback": rollback.to_dict()},
            )
        self._prune_cache()
        self.log.info("applied %s%% to %s (%s)", percent, display.output_name, display.stable_id)
        return result

    def set_saturation(
        self,
        selector: str,
        percent: int,
        confirm_ambiguous: bool = False,
    ) -> ApplyResult:
        percent = validate_percent(percent)
        discovery = self.discover()
        display = find_display(discovery.connected, selector)
        if not display.connected:
            return ApplyResult(
                success=False,
                status=DisplayStatus.DISCONNECTED,
                message=f"{display.output_name} is not connected",
                requested_percent=percent,
                display=display,
            )
        if percent != 0 and not display.enabled:
            return ApplyResult(
                success=False,
                status=DisplayStatus.UNSUPPORTED,
                message=f"{display.output_name} is disabled",
                requested_percent=percent,
                display=display,
            )
        if percent != 0 and display.identity_ambiguous and not confirm_ambiguous:
            return ApplyResult(
                success=False,
                status=DisplayStatus.NEEDS_CONFIRMATION,
                message=(
                    "this monitor's hardware identity is ambiguous; confirm that "
                    f"{display.output_name} is the intended display"
                ),
                requested_percent=percent,
                display=display,
            )
        return self._apply_preference(display, percent)

    def reset_display(self, selector: str) -> ApplyResult:
        return self.set_saturation(selector, 0, confirm_ambiguous=True)

    def reset_all(self) -> list[ApplyResult]:
        discovery = self.discover()
        targets: list[DisplayInfo] = []
        for display in discovery.connected:
            preference = self._preference(display)
            has_original = self.state_manager.get_original(display.stable_id) is not None
            if (
                (preference and preference.preferred_saturation != 0)
                or has_original
                or display.profile_owned_by_vivid
            ):
                targets.append(display)
        results = self.backend.reset_all(targets)
        for result in results:
            if result.success and result.display is not None:
                preference = self.settings.displays.get(result.display.stable_id)
                if preference is not None:
                    preference.preferred_saturation = 0
                    preference.last_profile_path = ""
                    preference.last_applied_at = utc_now()
            elif not result.success:
                self._record_error("reset", result.message)
        try:
            self._save_settings()
        except OSError as exc:
            self._record_error("settings", f"could not save settings: {exc}")
        self._prune_cache(discovery)
        return results

    def restore_saved(self, quiet: bool = False) -> RestoreReport:
        report = RestoreReport(safe_mode=self.settings.safe_mode)
        discovery = self.discover()
        changed = False
        if self.settings.safe_mode:
            report.skipped.append(
                {
                    "display": "*",
                    "reason": "safe mode is enabled; no automatic changes were made",
                }
            )
            return report
        if not self.capabilities.supported:
            report.errors.append({"display": "*", "message": "; ".join(self.capabilities.reasons)})
            return report
        for display in discovery.connected:
            preference = self._preference(display)
            if preference is None:
                continue
            percent = preference.preferred_saturation
            if percent != 0:
                if display.identity_ambiguous:
                    report.skipped.append(
                        {
                            "display": display.output_name,
                            "reason": "ambiguous hardware identity; explicit confirmation required",
                        }
                    )
                    continue
                view = self._view_for(display)
                if view.status == DisplayStatus.APPLIED:
                    report.skipped.append(
                        {"display": display.output_name, "reason": "already applied"}
                    )
                    continue
                original = self.state_manager.get_original(display.stable_id)
                if (
                    display.icc_profile_path
                    and not display.profile_owned_by_vivid
                    and not self._same_as_original(display, original)
                ):
                    report.skipped.append(
                        {
                            "display": display.output_name,
                            "reason": (
                                "the active colour profile was changed outside Vivid; "
                                "not overwriting it automatically"
                            ),
                        }
                    )
                    self._record_error(
                        "restore",
                        f"{display.output_name}: skipped because its profile was changed outside Vivid",
                    )
                    continue
                result = self._apply_preference(display, percent)
                if result.success:
                    changed = True
                    report.actions.append(
                        {
                            "display": display.output_name,
                            "action": f"apply {format_percent(percent)}",
                            "success": True,
                            "message": result.message,
                        }
                    )
                else:
                    report.errors.append(
                        {"display": display.output_name, "message": result.message}
                    )
            elif display.profile_owned_by_vivid:
                result = self.backend.reset(display)
                if result.success:
                    changed = True
                    if display.stable_id in self.settings.displays:
                        self.settings.displays[display.stable_id].preferred_saturation = 0
                        self.settings.displays[display.stable_id].last_profile_path = ""
                    report.actions.append(
                        {
                            "display": display.output_name,
                            "action": "restore original profile",
                            "success": True,
                            "message": result.message,
                        }
                    )
                else:
                    report.errors.append(
                        {"display": display.output_name, "message": result.message}
                    )
                    self._record_error("restore", result.message)
        if changed:
            try:
                self._save_settings()
            except OSError as exc:
                report.errors.append(
                    {"display": "*", "message": f"could not save restored settings: {exc}"}
                )
                self._record_error("settings", str(exc))
            self._prune_cache(discovery)
        if not quiet:
            self.log.info(
                "restore scan: %s changed, %s skipped, %s errors",
                report.changed,
                len(report.skipped),
                len(report.errors),
            )
        return report

    def identify(self, selector: str) -> DisplayInfo:
        discovery = self.discover()
        return find_display(discovery.connected, selector)

    def export_settings(self, path: Path) -> Path:
        return self.settings_store.export_to(path)

    def import_settings(self, path: Path) -> SettingsData:
        settings = self.settings_store.restore_from(path)
        self.settings = settings
        return settings

    def set_safe_mode(self, enabled: bool) -> None:
        self.settings.safe_mode = enabled
        self._save_settings()

    def doctor(self) -> dict[str, Any]:
        discovery_error = ""
        try:
            discovery = self.discover()
        except DiscoveryError as exc:
            discovery = DiscoveryResult()
            discovery_error = str(exc)
        try:
            views = self.views(discovery)
            inactive = self.inactive_views(discovery)
        except DiscoveryError as exc:
            views = []
            inactive = []
            discovery_error = discovery_error or str(exc)
        cache_files: list[dict[str, Any]] = []
        if self.icc_directory.exists():
            for path in sorted(self.icc_directory.glob("vivid-*.icc")):
                try:
                    validation = validate_profile_file(path)
                    cache_files.append(
                        {
                            "name": path.name,
                            "size": path.stat().st_size,
                            "valid": validation["valid"],
                            "description": validation.get("description", ""),
                            "sha256": validation.get("sha256", ""),
                        }
                    )
                except (OSError, IccError) as exc:
                    cache_files.append({"name": path.name, "valid": False, "error": str(exc)})
        return {
            "schema_version": 1,
            "generated_at": utc_now(),
            "app": {"version": APP_VERSION},
            "capabilities": self.capabilities.to_dict(),
            "backend": self.backend.name,
            "discovery_error": discovery_error,
            "displays": [view.to_dict() for view in views],
            "inactive_displays": [view.to_dict() for view in inactive],
            "warnings": discovery.warnings,
            "settings": {
                "path": str(self.settings_store.path),
                "warning": self.settings_store.last_warning,
                "data": self.settings.to_dict(),
            },
            "recovery": {
                "path": str(self.state_manager.path),
                "warning": self.state_manager.last_warning,
                "originals": {
                    key: original.to_dict()
                    for key, original in self.state_manager.all_originals().items()
                },
            },
            "profile_cache": {
                "directory": str(self.icc_directory),
                "files": cache_files,
            },
            "autostart": autostart_status(),
            "paths": {
                "config": str(config_path()),
                "data": str(data_dir()),
                "icc": str(self.icc_directory),
                "state": str(state_dir()),
                "log": str(log_path()),
                "autostart": str(autostart_path()),
            },
            "errors": self.last_errors,
            "log_tail": tail_log(120),
            "lcms_version": lcms_version(),
        }


def load_service(**kwargs: Any) -> VividService:
    return VividService(**kwargs)
