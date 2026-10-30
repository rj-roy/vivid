"""KWin per-output ICC backend driven by KScreen.

KScreen accepts an ICC profile, a colour profile source, and a colour power
preference per output.  KWin only runs its ICC shader (including 3D CLUT
profiles) when the output prefers colour accuracy, so Vivid sets that
preference while an adjustment is active and restores the recorded original
when it is removed.

Every operation is verified by re-reading the compositor state.  A successful
``kscreen-doctor`` exit status alone is not accepted as evidence.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from ..color.icc_generator import (
    IccError,
    cleanup_for_display,
    write_profile,
)
from ..display.discovery import (
    CommandResult,
    DiscoveryError,
    DiscoveryResult,
    Runner,
    SubprocessRunner,
    discover,
)
from ..models import (
    ApplyResult,
    BackendError,
    CapabilityReport,
    DisplayInfo,
    DisplayStatus,
    OriginalState,
    format_percent,
    validate_percent,
)
from ..recovery.state_manager import RecoveryStateManager
from .base import Backend

FAILURE_MARKERS = (
    "failed",
    "invalid",
    "does not exist",
    "unknown output",
    "unknown option",
    "could not",
    "cannot",
    "error",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalise_source(source: str, profile_path: str) -> str:
    upper = source.strip().upper()
    if "ICC" in upper:
        return "ICC"
    if "SRGB" in upper:
        return "SRGB"
    if "EDID" in upper:
        return "EDID"
    return "ICC" if profile_path else "EDID"


def _normalise_power(power: str) -> str:
    lowered = power.strip().lower()
    if "accuracy" in lowered:
        return "PreferAccuracy"
    if "efficiency" in lowered:
        return "PreferEfficiency"
    return ""


def _power_argument(power: str) -> str:
    if power == "PreferEfficiency":
        return "preferEfficiency"
    return "preferAccuracy"


def _profile_argument(output_name: str, path: str) -> str:
    if path:
        return f"output.{output_name}.iccprofile.{path}"
    return f"output.{output_name}.iccprofile."


class KWinIccBackend(Backend):
    name = "kwin-icc"

    def __init__(
        self,
        capabilities: CapabilityReport,
        state_manager: RecoveryStateManager,
        icc_directory: Path,
        runner: Runner | None = None,
        discovery_function: Callable[..., DiscoveryResult] | None = None,
        verify_timeout: float = 3.0,
        verify_interval: float = 0.2,
    ) -> None:
        self._capabilities = capabilities
        self.state_manager = state_manager
        self.icc_directory = Path(icc_directory)
        self.runner: Runner = runner or SubprocessRunner()
        self._discover = discovery_function or discover
        self.verify_timeout = verify_timeout
        self.verify_interval = verify_interval

    @property
    def capabilities(self) -> CapabilityReport:
        return self._capabilities

    def _refresh(self) -> DiscoveryResult:
        return self._discover(runner=self.runner)

    def _fresh(self, display: DisplayInfo, require_enabled: bool = True) -> DisplayInfo:
        result = self._refresh()
        target: DisplayInfo | None = None
        for candidate in result.connected:
            if candidate.stable_id == display.stable_id:
                target = candidate
                break
        if target is None or not target.connected:
            raise BackendError(
                f"display {display.output_name} is no longer connected with its recorded "
                "hardware identity"
            )
        if require_enabled and not target.enabled:
            raise BackendError(f"display {target.output_name} is disabled")
        return target

    def _kscreen(self, arguments: list[str]) -> CommandResult:
        result = self.runner(["kscreen-doctor", *arguments])
        message = (result.stderr or "").strip()
        lowered = message.lower()
        if result.returncode != 0:
            raise BackendError(message or f"kscreen-doctor exited with status {result.returncode}")
        if any(marker in lowered for marker in FAILURE_MARKERS):
            raise BackendError(message)
        return result

    def _snapshot(self, display: DisplayInfo) -> OriginalState:
        return OriginalState(
            stable_id=display.stable_id,
            output_name=display.output_name,
            icc_profile_path=display.icc_profile_path,
            color_profile_source=_normalise_source(
                display.color_profile_source, display.icc_profile_path
            ),
            color_power_tradeoff=_normalise_power(display.color_power_tradeoff),
            recorded_at=utc_now(),
            backend=self.name,
            backend_versions={
                "plasma": self._capabilities.plasma_version,
                "kwin": self._capabilities.kwin_version,
                "kscreen": self._capabilities.kscreen_version,
                "lcms": self._capabilities.lcms_version,
            },
        )

    def _verify(
        self,
        display: DisplayInfo,
        expected_path: str,
        expected_source: str,
        expected_power: str,
    ) -> tuple[bool, str, dict[str, bool]]:
        actual_path = display.icc_profile_path
        if expected_path:
            path_ok = (
                bool(actual_path) and Path(actual_path).resolve() == Path(expected_path).resolve()
            )
        else:
            path_ok = not actual_path
        source_ok = (
            not expected_source or display.color_profile_source.upper() == expected_source.upper()
        )
        power_ok = not expected_power or display.color_power_tradeoff == expected_power
        checks = {"profile": path_ok, "source": source_ok, "power": power_ok}
        if not path_ok:
            return (
                False,
                f"active profile is {actual_path or 'none'}, expected {expected_path or 'none'}",
                checks,
            )
        if not source_ok:
            return (
                False,
                f"colour profile source is {display.color_profile_source or 'unknown'}, "
                f"expected {expected_source}",
                checks,
            )
        if not power_ok:
            return (
                False,
                f"colour power preference is {display.color_power_tradeoff or 'unknown'}, "
                f"expected {expected_power}",
                checks,
            )
        return True, "compositor state verified", checks

    def _verify_with_retries(
        self,
        display: DisplayInfo,
        expected_path: str,
        expected_source: str,
        expected_power: str,
    ) -> tuple[bool, str, dict[str, bool], DisplayInfo | None]:
        deadline = time.monotonic() + self.verify_timeout
        last_message = "compositor state could not be read"
        last_checks: dict[str, bool] = {}
        fresh: DisplayInfo | None = None
        while True:
            try:
                fresh = self._fresh(display, require_enabled=False)
            except BackendError as exc:
                last_message = str(exc)
            else:
                verified, last_message, last_checks = self._verify(
                    fresh, expected_path, expected_source, expected_power
                )
                if verified:
                    return True, last_message, last_checks, fresh
            if time.monotonic() >= deadline:
                return False, last_message, last_checks, fresh
            time.sleep(self.verify_interval)

    def _restore(
        self, display: DisplayInfo, original: OriginalState
    ) -> tuple[bool, str, DisplayInfo | None]:
        source = original.color_profile_source or ("ICC" if original.icc_profile_path else "EDID")
        path = original.icc_profile_path if source == "ICC" else ""
        arguments = [
            _profile_argument(display.output_name, path),
            f"output.{display.output_name}.colorProfileSource.{source}",
        ]
        if original.color_power_tradeoff:
            arguments.append(
                f"output.{display.output_name}.colorPowerTradeoff."
                f"{_power_argument(original.color_power_tradeoff)}"
            )
        try:
            self._kscreen(arguments)
        except BackendError as exc:
            return False, str(exc), None
        verified, message, _checks, fresh = self._verify_with_retries(
            display, path, source, original.color_power_tradeoff
        )
        return verified, message, fresh

    def apply(self, display: DisplayInfo, percent: int) -> ApplyResult:
        percent = validate_percent(percent)
        if percent == 0:
            return self.reset(display)
        if not self._capabilities.supported:
            reason = "; ".join(self._capabilities.reasons) or "backend is unsupported"
            return ApplyResult(
                success=False,
                status=DisplayStatus.UNSUPPORTED,
                message=reason,
                requested_percent=percent,
                display=display,
            )
        try:
            fresh = self._fresh(display)
        except (BackendError, DiscoveryError) as exc:
            return ApplyResult(
                success=False,
                status=DisplayStatus.DISCONNECTED,
                message=str(exc),
                requested_percent=percent,
                display=display,
            )
        original = self.state_manager.get_original(fresh.stable_id)
        previous = self._snapshot(fresh)
        if original is None:
            original = self._snapshot(fresh)
            try:
                self.state_manager.record_original(original)
            except OSError as exc:
                return ApplyResult(
                    success=False,
                    status=DisplayStatus.FAILED,
                    message=(
                        "refusing to change the display because the original state "
                        f"could not be recorded: {exc}"
                    ),
                    requested_percent=percent,
                    display=fresh,
                )
        try:
            profile_path = write_profile(percent, fresh.stable_id, self.icc_directory)
        except (IccError, OSError) as exc:
            return ApplyResult(
                success=False,
                status=DisplayStatus.FAILED,
                message=f"could not generate the ICC profile: {exc}",
                requested_percent=percent,
                display=fresh,
            )
        arguments = [
            _profile_argument(fresh.output_name, str(profile_path)),
            f"output.{fresh.output_name}.colorProfileSource.ICC",
            f"output.{fresh.output_name}.colorPowerTradeoff.preferAccuracy",
        ]
        try:
            self._kscreen(arguments)
        except BackendError as exc:
            restored, restore_message, restored_display = self._restore(fresh, previous)
            message = f"KWin rejected the display profile: {exc}"
            if restored:
                message += "; the previous display state was restored"
            else:
                message += (
                    f"; the previous display state could not be restored ({restore_message}); "
                    "the recovery snapshot was preserved. Read docs/RECOVERY.md"
                )
            return ApplyResult(
                success=False,
                status=DisplayStatus.FAILED,
                message=message,
                requested_percent=percent,
                profile_path=str(profile_path),
                display=restored_display or fresh,
                details={"restored": restored, "stage": "apply"},
            )
        verified, message, checks, verified_display = self._verify_with_retries(
            fresh, str(profile_path), "ICC", "PreferAccuracy"
        )
        if not verified:
            restored, restore_message, _ = self._restore(fresh, previous)
            if restored:
                message = (
                    f"the compositor did not confirm the adjustment ({message}); "
                    "the previous display state was restored"
                )
            else:
                message = (
                    f"the compositor did not confirm the adjustment ({message}) and "
                    f"the previous display state could not be restored ({restore_message}); "
                    "the recovery snapshot was preserved. Run 'vivid doctor' and read "
                    "docs/RECOVERY.md"
                )
            return ApplyResult(
                success=False,
                status=DisplayStatus.FAILED,
                message=message,
                requested_percent=percent,
                profile_path=str(profile_path),
                display=verified_display or fresh,
                details={"checks": checks, "restored": restored},
            )
        cleanup_for_display(self.icc_directory, fresh.stable_id, profile_path)
        return ApplyResult(
            success=True,
            status=DisplayStatus.APPLIED,
            message=f"applied {format_percent(percent)} saturation to {fresh.output_name}",
            requested_percent=percent,
            applied_percent=percent,
            profile_path=str(profile_path),
            verified=True,
            display=verified_display or fresh,
            details={"checks": checks},
        )

    def reset(self, display: DisplayInfo) -> ApplyResult:
        try:
            fresh = self._fresh(display, require_enabled=False)
        except (BackendError, DiscoveryError) as exc:
            return ApplyResult(
                success=False,
                status=DisplayStatus.DISCONNECTED,
                message=str(exc),
                requested_percent=0,
                display=display,
            )
        original = self.state_manager.get_original(fresh.stable_id)
        if original is None:
            if fresh.profile_owned_by_vivid:
                return ApplyResult(
                    success=False,
                    status=DisplayStatus.FAILED,
                    message=(
                        "this display has a Vivid profile but no recovery snapshot; "
                        "refusing to guess. Read docs/RECOVERY.md or select the original "
                        "profile in System Settings."
                    ),
                    requested_percent=0,
                    display=fresh,
                )
            return ApplyResult(
                success=True,
                status=DisplayStatus.ACTIVE,
                message="no Vivid adjustment is recorded for this display",
                requested_percent=0,
                applied_percent=0,
                verified=True,
                display=fresh,
            )
        restored, message, restored_display = self._restore(fresh, original)
        if not restored:
            return ApplyResult(
                success=False,
                status=DisplayStatus.FAILED,
                message=(
                    f"could not restore the original display state ({message}); "
                    "the recovery snapshot has been preserved. Read docs/RECOVERY.md."
                ),
                requested_percent=0,
                display=restored_display or fresh,
                details={"restored": False},
            )
        with contextlib.suppress(OSError):
            self.state_manager.mark_restored(fresh.stable_id)
        cleanup_for_display(self.icc_directory, fresh.stable_id, None)
        return ApplyResult(
            success=True,
            status=DisplayStatus.ACTIVE,
            message=f"restored the original profile assignment for {fresh.output_name}",
            requested_percent=0,
            applied_percent=0,
            verified=True,
            display=restored_display or fresh,
            details={"restored": True},
        )

    def reset_all(self, displays: Iterable[DisplayInfo]) -> list[ApplyResult]:
        results: list[ApplyResult] = []
        seen: set[str] = set()
        for display in displays:
            if display.stable_id in seen:
                continue
            seen.add(display.stable_id)
            results.append(self.reset(display))
        return results

    def verify_saved(self, display: DisplayInfo, percent: int) -> tuple[bool, str]:
        percent = validate_percent(percent)
        if percent == 0:
            return not display.profile_owned_by_vivid, "no Vivid profile expected"
        try:
            profile_path = write_profile(percent, display.stable_id, self.icc_directory)
        except (IccError, OSError) as exc:
            return False, f"could not verify profile: {exc}"
        verified, message, _checks = self._verify(
            display, str(profile_path), "ICC", "PreferAccuracy"
        )
        return verified, message
