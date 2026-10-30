"""Command-line interface for Vivid."""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import APP_ID, APP_NAME, APP_VERSION
from .application import VividService
from .autostart import disable as disable_autostart
from .autostart import enable as enable_autostart
from .autostart import status as autostart_status
from .display.discovery import DiscoveryError, find_display
from .logging_utils import setup_logging
from .models import (
    ApplyResult,
    CapabilityError,
    DisplayLookupError,
    DisplayStatus,
    ValidationError,
    format_percent,
    validate_percent,
)

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3
EXIT_LOOKUP = 4
JSON_SCHEMA_VERSION = 1


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_FAILURE) -> None:
        super().__init__(message)
        self.code = code


def _json_output(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _error_payload(message: str, code: int) -> dict[str, Any]:
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "ok": False,
        "error": {"code": code, "message": message},
    }


def _print_result(result: ApplyResult, as_json: bool) -> int:
    if as_json:
        payload = {
            "schema_version": JSON_SCHEMA_VERSION,
            "ok": result.success,
            "result": result.to_dict(),
        }
        if not result.success:
            payload["error"] = {"code": EXIT_FAILURE, "message": result.message}
        _json_output(payload)
    else:
        prefix = "OK" if result.success else "ERROR"
        print(f"{prefix}: {result.message}")
        if result.profile_path and result.success:
            print(f"profile: {result.profile_path}")
    if result.success:
        return EXIT_OK
    if result.status == DisplayStatus.UNSUPPORTED:
        return EXIT_UNSUPPORTED
    return EXIT_FAILURE


def _status_code(status: DisplayStatus) -> str:
    return status.value.replace("_", " ")


def _format_displays(views: list) -> str:
    if not views:
        return "No connected displays reported."
    lines = []
    for view in views:
        display = view.display
        kind = "internal" if display.internal else "external"
        applied = (
            format_percent(view.applied_saturation)
            if view.applied_saturation is not None
            else "unknown"
        )
        lines.append(
            f"{display.output_name:<12} {display.friendly_name:<32} {kind:<8} "
            f"saved {format_percent(view.preferred_saturation):>6}  applied {applied:<9} "
            f"[{_status_code(view.status)}]"
        )
        if view.message:
            lines.append(f"  {view.message}")
    return "\n".join(lines)


def _service(args: argparse.Namespace) -> VividService:
    return VividService()


def _capability_payload(service: VividService) -> dict[str, Any]:
    return service.capabilities.to_dict()


def _cmd_list(args: argparse.Namespace) -> int:
    service = _service(args)
    discovery = service.discover()
    views = service.views(discovery)
    inactive = service.inactive_views(discovery) if args.all else []
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": True,
                "backend": service.backend.name,
                "supported": service.capabilities.supported,
                "displays": [view.to_dict() for view in views],
                "inactive": [view.to_dict() for view in inactive],
            }
        )
        return EXIT_OK
    print(_format_displays(views))
    if inactive:
        print("\nSaved but disconnected:")
        for view in inactive:
            print(
                f"{view.display.output_name:<12} saved "
                f"{format_percent(view.preferred_saturation)} "
                f"[{_status_code(view.status)}]"
            )
    if not service.capabilities.supported:
        print("\nBackend unsupported:")
        for reason in service.capabilities.reasons:
            print(f"  - {reason}")
    return EXIT_OK


def _cmd_status(args: argparse.Namespace) -> int:
    service = _service(args)
    discovery = service.discover()
    views = service.views(discovery)
    inactive = service.inactive_views(discovery)
    payload = {
        "schema_version": JSON_SCHEMA_VERSION,
        "ok": True,
        "backend": service.backend.name,
        "capabilities": _capability_payload(service),
        "displays": [view.to_dict() for view in views],
        "inactive": [view.to_dict() for view in inactive],
        "warnings": discovery.warnings,
        "autostart": autostart_status(),
        "safe_mode": service.settings.safe_mode,
    }
    if args.json:
        _json_output(payload)
        return EXIT_OK
    print(f"{APP_NAME} {APP_VERSION} ({APP_ID})")
    print(
        f"Backend: {service.backend.name} ({'supported' if service.capabilities.supported else 'unsupported'})"
    )
    if service.capabilities.supported:
        print(
            f"Session: {service.capabilities.session_type.value}, "
            f"Plasma {service.capabilities.plasma_version or 'unknown'}, "
            f"KWin {service.capabilities.kwin_version or 'unknown'}"
        )
    else:
        for reason in service.capabilities.reasons:
            print(f"  - {reason}")
    print()
    print(_format_displays(views))
    if inactive:
        print("\nSaved but disconnected:")
        for view in inactive:
            print(            f"{view.display.output_name:<12} saved "
            f"{format_percent(view.preferred_saturation)}")
    print(f"\nAutostart: {'enabled' if autostart_status()['enabled'] else 'disabled'}")
    print(f"Safe mode: {'on' if service.settings.safe_mode else 'off'}")
    return EXIT_OK


def _cmd_get(args: argparse.Namespace) -> int:
    service = _service(args)
    discovery = service.discover()
    display = find_display(discovery.connected, args.display)
    view = service.views(discovery)
    selected = next((item for item in view if item.display.stable_id == display.stable_id), None)
    if selected is None:
        raise CliError("display state could not be determined", EXIT_FAILURE)
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": True,
                "display": selected.to_dict(),
            }
        )
        return EXIT_OK
    print(f"{display.output_name}: {format_percent(selected.preferred_saturation)} saved")
    if selected.applied_saturation is not None:
        print(f"applied: {format_percent(selected.applied_saturation)}")
    print(f"status: {_status_code(selected.status)}")
    if selected.message:
        print(selected.message)
    return EXIT_OK


def _cmd_set(args: argparse.Namespace) -> int:
    percent = validate_percent(args.value)
    service = _service(args)
    result = service.set_saturation(args.display, percent, confirm_ambiguous=bool(args.yes))
    return _print_result(result, args.json)


def _cmd_reset(args: argparse.Namespace) -> int:
    service = _service(args)
    if args.all:
        results = service.reset_all()
        if args.json:
            _json_output(
                {
                    "schema_version": JSON_SCHEMA_VERSION,
                    "ok": all(result.success for result in results),
                    "results": [result.to_dict() for result in results],
                }
            )
        else:
            if not results:
                print("OK: no displays needed a reset")
            for result in results:
                _print_result(result, False)
        return EXIT_OK if all(result.success for result in results) else EXIT_FAILURE
    assert args.display
    result = service.reset_display(args.display)
    return _print_result(result, args.json)


def _cmd_capabilities(args: argparse.Namespace) -> int:
    service = _service(args)
    payload = _capability_payload(service)
    if args.json:
        _json_output({"schema_version": JSON_SCHEMA_VERSION, "ok": True, "backend": payload})
        return EXIT_OK
    print(f"Backend: {payload['backend']}")
    print(f"Supported: {'yes' if payload['supported'] else 'no'}")
    print(f"Session: {payload['session_type']}")
    print(f"Desktop: {payload['desktop'] or 'unknown'}")
    print(f"Plasma: {payload['plasma_version'] or 'unknown'}")
    print(f"KWin: {payload['kwin_version'] or 'unknown'}")
    print(f"KScreen: {payload['kscreen_version'] or 'unknown'}")
    print(f"Little CMS: {payload['lcms_version'] or 'unknown'}")
    print(f"ICC profile support: {'yes' if payload['icc_profile_support'] else 'no'}")
    print(f"Outputs: {payload['output_count']}")
    for reason in payload["reasons"]:
        print(f"reason: {reason}")
    for warning in payload["warnings"]:
        print(f"warning: {warning}")
    return EXIT_OK if payload["supported"] else EXIT_UNSUPPORTED


def _cmd_doctor(args: argparse.Namespace) -> int:
    service = _service(args)
    report = service.doctor()
    if args.write:
        target = Path(args.write).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not args.json:
            print(f"diagnostics written to {target}")
    if args.json:
        _json_output({"schema_version": JSON_SCHEMA_VERSION, "ok": True, "doctor": report})
        return EXIT_OK
    capabilities = report["capabilities"]
    print(f"{APP_NAME} diagnostics")
    print(
        f"Backend: {report['backend']} ({'supported' if capabilities['supported'] else 'unsupported'})"
    )
    print(f"Session: {capabilities['session_type']} / {capabilities['desktop'] or 'unknown'}")
    print(
        f"Versions: Plasma {capabilities['plasma_version'] or '?'}, "
        f"KWin {capabilities['kwin_version'] or '?'}, "
        f"KScreen {capabilities['kscreen_version'] or '?'}, "
        f"lcms {report['lcms_version'] or '?'}"
    )
    if report["discovery_error"]:
        print(f"Discovery error: {report['discovery_error']}")
    for reason in capabilities["reasons"]:
        print(f"reason: {reason}")
    for warning in capabilities["warnings"]:
        print(f"warning: {warning}")
    print()
    print("Displays:")
    for view in report["displays"]:
        display = view["display"]
        print(
            f"  {display['output_name']}: {display['friendly_name']} "
            f"[{view['status']}] saved {format_percent(view['preferred_saturation'])}"
        )
        print(f"    identity: {display['stable_id']} ({display['identity']['source']})")
        print(
            f"    profile: {display['icc_profile_path'] or 'none'}; "
            f"source: {display['color_profile_source'] or 'unknown'}; "
            f"power: {display['color_power_tradeoff'] or 'unknown'}"
        )
        if view["message"]:
            print(f"    {view['message']}")
    print()
    print(f"Settings: {report['settings']['path']}")
    print(f"Recovery state: {report['recovery']['path']}")
    print(f"Profile cache: {report['profile_cache']['directory']}")
    print(f"Log: {report['paths']['log']}")
    if report["errors"]:
        print("\nRecent errors:")
        for error in report["errors"][-5:]:
            print(f"  [{error['category']}] {error['message']}")
    return EXIT_OK


def _cmd_export_settings(args: argparse.Namespace) -> int:
    service = _service(args)
    target = service.export_settings(Path(args.file))
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": True,
                "exported_to": str(target),
            }
        )
    else:
        print(f"exported settings to {target}")
    return EXIT_OK


def _cmd_restore_settings(args: argparse.Namespace) -> int:
    service = _service(args)
    settings = service.import_settings(Path(args.file))
    message = f"restored settings for {len(settings.displays)} display(s)"
    if not args.no_apply:
        report = service.restore_saved(quiet=True)
        message += f"; {report.changed} display(s) updated"
        if report.errors:
            message += f"; {len(report.errors)} error(s)"
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": True,
                "message": message,
                "settings": settings.to_dict(),
            }
        )
    else:
        print(message)
    return EXIT_OK


def _cmd_restore(args: argparse.Namespace) -> int:
    service = _service(args)
    report = service.restore_saved(quiet=args.quiet)
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": not report.errors,
                "report": report.to_dict(),
            }
        )
    elif not args.quiet:
        print(
            f"restore: {report.changed} changed, {len(report.skipped)} skipped, "
            f"{len(report.errors)} errors"
        )
        for action in report.actions:
            print(f"  {action['display']}: {action['action']} ({action['message']})")
        for skipped in report.skipped:
            print(f"  skipped {skipped['display']}: {skipped['reason']}")
        for error in report.errors:
            print(f"  error {error['display']}: {error['message']}")
    return EXIT_OK if not report.errors else EXIT_FAILURE


def _cmd_autostart(args: argparse.Namespace) -> int:
    if args.action == "enable":
        path = enable_autostart()
        payload = {"enabled": True, "path": str(path)}
        code = EXIT_OK
    elif args.action == "disable":
        removed = disable_autostart()
        payload = {"enabled": False, "removed": removed}
        code = EXIT_OK
    else:
        payload = autostart_status()
        code = EXIT_OK
    if args.json:
        _json_output({"schema_version": JSON_SCHEMA_VERSION, "ok": True, **payload})
    else:
        if payload.get("enabled"):
            print(f"autostart enabled: {payload.get('path', autostart_status()['path'])}")
        else:
            print("autostart disabled")
    return code


def _cmd_safe_mode(args: argparse.Namespace) -> int:
    service = _service(args)
    if args.action == "on":
        service.set_safe_mode(True)
    elif args.action == "off":
        service.set_safe_mode(False)
    enabled = service.settings.safe_mode
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": True,
                "safe_mode": enabled,
            }
        )
    else:
        print(f"safe mode is {'on' if enabled else 'off'}")
    return EXIT_OK


def _cmd_identify(args: argparse.Namespace) -> int:
    service = _service(args)
    display = service.identify(args.display)
    if args.json:
        _json_output(
            {
                "schema_version": JSON_SCHEMA_VERSION,
                "ok": True,
                "display": display.to_dict(),
            }
        )
    else:
        print(
            f"{display.output_name}: {display.friendly_name} "
            f"({'internal' if display.internal else 'external'})"
        )
    try:
        from .ui.identify import show_identify

        show_identify([display], duration_ms=2500)
    except Exception:
        pass
    return EXIT_OK


def _cmd_uninstall(args: argparse.Namespace) -> int:
    service = _service(args)
    try:
        discovery = service.discover()
    except DiscoveryError as exc:
        raise CliError(
            f"cannot verify restoration without display discovery: {exc}",
            EXIT_FAILURE,
        ) from exc
    originals = service.state_manager.all_originals()
    connected_ids = {display.stable_id for display in discovery.connected}
    pending_disconnected = [
        original for stable_id, original in originals.items() if stable_id not in connected_ids
    ]
    targets = [
        display
        for display in discovery.connected
        if display.stable_id in originals or display.profile_owned_by_vivid
    ]
    results = service.backend.reset_all(targets)
    failures = [result for result in results if not result.success]
    if failures:
        for result in failures:
            print(
                f"ERROR: {result.display.output_name if result.display else '?'}: {result.message}"
            )
        print(
            "Uninstallation stopped: restoration failed. Recovery information was preserved. "
            "Read docs/RECOVERY.md."
        )
        return EXIT_FAILURE
    disable_autostart()
    if pending_disconnected:
        print("ERROR: some saved displays are not connected and could not be restored:")
        for original in pending_disconnected:
            print(f"  {original.output_name} ({original.stable_id})")
        print(
            "Reconnect them and run 'vivid uninstall' again. Recovery information and "
            "generated profiles have been kept."
        )
        return EXIT_FAILURE
    removed = 0
    if service.icc_directory.exists():
        for path in service.icc_directory.glob("vivid-*.icc"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    if args.purge:
        import shutil

        for path in (
            service.settings_store.path.parent,
            service.state_manager.path.parent,
            service.icc_directory,
        ):
            with contextlib.suppress(OSError):
                shutil.rmtree(path)
    payload = {
        "restored": len(results),
        "profiles_removed": removed,
        "autostart_disabled": True,
        "purged": bool(args.purge),
    }
    if args.json:
        _json_output({"schema_version": JSON_SCHEMA_VERSION, "ok": True, **payload})
    else:
        print(
            f"restored {len(results)} display(s), removed {removed} generated profile(s), "
            "disabled autostart"
        )
        if args.purge:
            print("user settings, recovery state, and profile cache removed")
        else:
            print("user settings and recovery state were preserved")
    return EXIT_OK


def _cmd_gui(args: argparse.Namespace) -> int:
    if args.detach:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "vivid.ui.main_window"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise CliError(f"could not launch the Vivid GUI: {exc}") from exc
        if args.json:
            _json_output({"schema_version": JSON_SCHEMA_VERSION, "ok": True, "launched": True})
        else:
            print("launched Vivid GUI")
        return EXIT_OK
    from .ui.main_window import main as gui_main

    arguments: list[str] = []
    if getattr(args, "identify", None):
        arguments.extend(["--identify", args.identify])
    return gui_main(arguments)


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    common.add_argument("--verbose", action="store_true", help="enable debug logging")
    parser = argparse.ArgumentParser(
        prog="vivid",
        description="Independent per-display saturation control for KDE Plasma Wayland",
        parents=[common],
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {APP_VERSION}")
    subparsers = parser.add_subparsers(dest="command")

    list_parser = subparsers.add_parser("list", parents=[common], help="list displays")
    list_parser.add_argument(
        "--all", action="store_true", help="include saved disconnected displays"
    )
    list_parser.set_defaults(func=_cmd_list)

    status_parser = subparsers.add_parser(
        "status", parents=[common], help="show backend and display status"
    )
    status_parser.set_defaults(func=_cmd_status)

    get_parser = subparsers.add_parser(
        "get", parents=[common], help="show one display's saved value"
    )
    get_parser.add_argument("display")
    get_parser.set_defaults(func=_cmd_get)

    set_parser = subparsers.add_parser("set", parents=[common], help="set a display's saturation")
    set_parser.add_argument("display")
    set_parser.add_argument("value")
    set_parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm changes to a display with an ambiguous hardware identity",
    )
    set_parser.set_defaults(func=_cmd_set)

    reset_parser = subparsers.add_parser(
        "reset", parents=[common], help="reset one or all displays"
    )
    reset_parser.add_argument("display", nargs="?")
    reset_parser.add_argument(
        "--all", action="store_true", help="restore every display Vivid changed"
    )
    reset_parser.set_defaults(func=_cmd_reset)

    capabilities_parser = subparsers.add_parser(
        "capabilities",
        aliases=["backend"],
        parents=[common],
        help="check display support and detected KWin/KScreen capabilities",
    )
    capabilities_parser.set_defaults(func=_cmd_capabilities)

    doctor_parser = subparsers.add_parser(
        "doctor", parents=[common], help="collect diagnostics without changing settings"
    )
    doctor_parser.add_argument("--write", metavar="FILE", help="write the JSON report to FILE")
    doctor_parser.set_defaults(func=_cmd_doctor)

    export_parser = subparsers.add_parser(
        "export-settings", parents=[common], help="export configuration"
    )
    export_parser.add_argument("file")
    export_parser.set_defaults(func=_cmd_export_settings)

    import_parser = subparsers.add_parser(
        "restore-settings", parents=[common], help="import configuration"
    )
    import_parser.add_argument("file")
    import_parser.add_argument("--no-apply", action="store_true", help="only import, do not apply")
    import_parser.set_defaults(func=_cmd_restore_settings)

    restore_parser = subparsers.add_parser(
        "restore", parents=[common], help="apply saved settings (used at login)"
    )
    restore_parser.add_argument("--quiet", action="store_true")
    restore_parser.set_defaults(func=_cmd_restore)

    autostart_parser = subparsers.add_parser(
        "autostart", parents=[common], help="manage KDE autostart"
    )
    autostart_parser.add_argument("action", choices=["enable", "disable", "status"])
    autostart_parser.set_defaults(func=_cmd_autostart)

    safe_parser = subparsers.add_parser(
        "safe-mode", parents=[common], help="disable automatic restoration"
    )
    safe_parser.add_argument("action", choices=["on", "off", "status"])
    safe_parser.set_defaults(func=_cmd_safe_mode)

    identify_parser = subparsers.add_parser(
        "identify", parents=[common], help="identify a display on screen"
    )
    identify_parser.add_argument("display")
    identify_parser.set_defaults(func=_cmd_identify)

    uninstall_parser = subparsers.add_parser(
        "uninstall", parents=[common], help="safely restore displays before package removal"
    )
    uninstall_parser.add_argument(
        "--purge", action="store_true", help="also remove settings and recovery state"
    )
    uninstall_parser.set_defaults(func=_cmd_uninstall)

    gui_parser = subparsers.add_parser(
        "gui", parents=[common], help="launch the graphical interface"
    )
    gui_parser.add_argument("--identify", metavar="DISPLAY")
    gui_parser.add_argument(
        "--detach",
        action="store_true",
        help="launch the graphical interface and return immediately",
    )
    gui_parser.set_defaults(func=_cmd_gui)

    return parser


def _write_error(message: str, code: int, as_json: bool) -> None:
    if as_json:
        _json_output(_error_payload(message, code))
    else:
        print(f"ERROR: {message}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["gui"]
    try:
        args = parser.parse_args(arguments)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
    if not hasattr(args, "func"):
        parser.print_help()
        return EXIT_USAGE
    setup_logging(getattr(args, "verbose", False))
    try:
        return int(args.func(args))
    except ValidationError as exc:
        _write_error(str(exc), EXIT_USAGE, getattr(args, "json", False))
        return EXIT_USAGE
    except DisplayLookupError as exc:
        _write_error(str(exc), EXIT_LOOKUP, getattr(args, "json", False))
        return EXIT_LOOKUP
    except CapabilityError as exc:
        _write_error(str(exc), EXIT_UNSUPPORTED, getattr(args, "json", False))
        return EXIT_UNSUPPORTED
    except (DiscoveryError, CliError) as exc:
        code = getattr(exc, "code", EXIT_FAILURE)
        _write_error(str(exc), code, getattr(args, "json", False))
        return code
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _write_error(f"unexpected failure: {exc}", EXIT_FAILURE, getattr(args, "json", False))
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
