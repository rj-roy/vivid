# CLI reference

The `vivid` command controls saturation for one display at a time. Every command
that changes a display reads the compositor state again before reporting success.

Running `vivid` with no subcommand starts the GUI. `vivid --help` lists all
commands, and every subcommand accepts `--help`, `--json`, and `--verbose`.

## Commands

| Command | Purpose |
| --- | --- |
| `vivid list [--all]` | List connected displays and saved values |
| `vivid status` | Show backend, capabilities, displays, autostart, and safe mode |
| `vivid get <display>` | Show one display's saved and applied value |
| `vivid set <display> <-100..100> [--yes]` | Apply a saturation adjustment |
| `vivid reset <display>` | Restore one display's original state |
| `vivid reset --all` | Restore every display changed by Vivid |
| `vivid capabilities` | Check display support and detected KWin/KScreen capabilities |
| `vivid doctor [--write FILE]` | Collect diagnostics without changing state |
| `vivid export-settings FILE` | Export display preferences as versioned JSON |
| `vivid restore-settings FILE [--no-apply]` | Import preferences and optionally apply them |
| `vivid restore [--quiet]` | Apply saved settings; used at login |
| `vivid autostart enable\|disable\|status` | Manage the KDE autostart entry |
| `vivid safe-mode on\|off\|status` | Disable or enable automatic restoration |
| `vivid identify <display>` | Flash an on-screen label for one display |
| `vivid uninstall [--purge]` | Restore displays before package removal |
| `vivid gui [--identify <display>]` | Start the graphical interface |

### Display selectors

`<display>` accepts, in order of preference:

1. The connector name, for example `DP-1`, `HDMI-A-1`, or `eDP-1`.
2. The stable Vivid identity, usually derived from the monitor UUID.
3. A unique EDID identifier or model name.

A selector that matches more than one connected display is rejected. Use
`vivid list --json` to obtain connector names and stable IDs. `--yes` is required
only for a display whose hardware identity is ambiguous.

### Saturation values

The value is an integer from `-100` to `+100`:

- `-100` means grayscale (zero saturation).
- `0` means the display's unmodified baseline.
- `-50` means half the baseline saturation.
- `+50` means approximately 1.5 times the baseline saturation.
- `+100` means approximately twice the baseline saturation.
- Values are adjustment scales, not calibrated saturation percentages.

The transform clips out-of-range RGB values. See the implementation overview in
the project README.

## Safety behaviour

- No sudo or root access is used.
- A command applies to one output unless `--all` is explicit.
- Original profile, colour source, and power preference are recorded before the
  first change to a display.
- `reset` restores the recorded originals. It does not force sRGB.
- `uninstall` refuses to remove generated profiles while a saved display is
  disconnected or restoration fails.
- `safe-mode on` stops automatic restoration without undoing the current profile.
- HDR outputs and non-KWin sessions are reported as unsupported.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success; the compositor confirmed the requested state |
| `1` | Runtime failure, verification failure, or incomplete restoration |
| `2` | Usage error, invalid saturation value, or bad arguments |
| `3` | Backend or capability unsupported |
| `4` | Display selector unknown or ambiguous |
| `130` | Interrupted with Ctrl+C |

Errors are printed to stderr in text mode. In JSON mode, an error object is
printed to stdout with the same exit code.

## JSON output

All JSON output has `schema_version: 1`. The schema is additive within major
version 1; consumers must ignore unknown fields. Successful responses include
`"ok": true`; failures include `"ok": false` and an error object:

```json
{
  "schema_version": 1,
  "ok": false,
  "error": {
    "code": 4,
    "message": "no display matches 'DP-9'"
  }
}
```

### `list` and `status`

```json
{
  "schema_version": 1,
  "ok": true,
  "backend": "kwin-icc",
  "supported": true,
  "displays": [
    {
      "display": {
        "output_name": "HDMI-A-1",
        "friendly_name": "External Display (PCGM-King 22)",
        "display_name": "PCGM-King 22",
        "internal": false,
        "connected": true,
        "enabled": true,
        "width": 1920,
        "height": 1080,
        "refresh_rate": 60.0,
        "scale": 1.0,
        "icc_profile_path": "/home/user/.local/share/vivid/icc/vivid-abc123.icc",
        "color_profile_source": "ICC",
        "color_power_tradeoff": "PreferAccuracy",
        "stable_id": "edid-...",
        "identity": {
          "stable_id": "edid-...",
          "source": "edid",
          "ambiguous": false
        },
        "identity_ambiguous": false,
        "profile_owned_by_vivid": true
      },
      "preferred_saturation": 30,
      "applied_saturation": 30,
      "status": "applied",
      "message": "applied +30% saturation to HDMI-A-1",
      "applied_profile_path": "/home/user/.local/share/vivid/icc/vivid-abc123.icc",
      "saved": true
    }
  ],
  "inactive": []
}
```

`status` additionally includes `capabilities`, `warnings`, `autostart`, and
`safe_mode`. `list --all` populates `inactive` with saved disconnected displays.

Display status values: `active`, `applying`, `applied`, `unsupported`, `failed`,
`disconnected`, `conflict`, `needs_confirmation`.

The Plasma panel widget and tray sliders call the same CLI operations and
therefore share the same validation, identity checks, and backend verification.

### `get`

```json
{
  "schema_version": 1,
  "ok": true,
  "display": {
    "display": {"output_name": "DP-1", "stable_id": "edid-..."},
    "preferred_saturation": 25,
    "applied_saturation": 25,
    "status": "applied",
    "message": "",
    "saved": true
  }
}
```

The nested `display` object contains the same fields as in `list`.

### `set` and `reset`

```json
{
  "schema_version": 1,
  "ok": true,
  "result": {
    "success": true,
    "status": "applied",
    "message": "applied +30% saturation to HDMI-A-1",
    "requested_percent": 30,
    "applied_percent": 30,
    "profile_path": "/home/user/.local/share/vivid/icc/vivid-abc123.icc",
    "verified": true,
    "display": {"output_name": "HDMI-A-1", "stable_id": "edid-..."},
    "details": {}
  }
}
```

`reset --all` returns `results` instead of `result`, and `ok` is true only when
every result succeeded. A result with status `unsupported` exits with code 3.

### `backend`

```json
{
  "schema_version": 1,
  "ok": true,
  "backend": {
    "backend": "kwin-icc",
    "supported": true,
    "session_type": "wayland",
    "desktop": "KDE",
    "plasma_version": "6.7.5",
    "kwin_version": "6.7.5",
    "kscreen_version": "6.7.5",
    "kscreen_doctor": true,
    "kscreen_json": true,
    "icc_profile_support": true,
    "color_profile_source_support": true,
    "output_count": 2,
    "lcms_version": "2.16.0",
    "distro": "fedora",
    "fedora_version": "44",
    "reasons": [],
    "warnings": []
  }
}
```

`vivid capabilities` exits with code 3 when `supported` is false. The older
`vivid backend` spelling remains available as an alias.

### `doctor`

```json
{
  "schema_version": 1,
  "ok": true,
  "doctor": {
    "backend": "kwin-icc",
    "capabilities": {},
    "discovery_error": null,
    "displays": [],
    "inactive": [],
    "lcms_version": "2.16.0",
    "settings": {"path": "/home/user/.config/vivid/config.json"},
    "recovery": {"path": "/home/user/.local/state/vivid/state.json"},
    "profile_cache": {"directory": "/home/user/.local/share/vivid/icc"},
    "paths": {"config": "...", "state": "...", "log": "..."},
    "errors": []
  }
}
```

`doctor --write FILE` writes the same `doctor` object to `FILE` without the
`schema_version` and `ok` wrapper. `doctor` is read-only.

### Settings commands

`export-settings` writes a document with `schema_version`, `backend`,
`safe_mode`, and `displays`; `restore-settings` returns the imported settings and
a summary message. Use `--no-apply` to import without changing displays.

### `autostart`, `safe-mode`, and `uninstall`

These return a small object with `ok`, plus fields such as `enabled`, `path`,
`safe_mode`, `restored`, `profiles_removed`, `autostart_disabled`, and `purged`.

## Examples

```bash
vivid list
vivid list --json | jq '.displays[].display.output_name'
vivid set DP-1 30
vivid set HDMI-A-1 0
vivid get eDP-1 --json
vivid reset DP-1
vivid reset --all
vivid capabilities --json
vivid doctor --write /tmp/vivid-diagnostics.json
vivid autostart enable
vivid safe-mode on
vivid uninstall
```

For recovery procedures, see [RECOVERY.md](RECOVERY.md). For version support,
see [COMPATIBILITY.md](COMPATIBILITY.md).
