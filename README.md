# Vivid

Independent per-display saturation control for Fedora KDE Plasma Wayland.

Vivid lets you adjust one monitor without changing the appearance of another. It
generates a synthetic ICC profile for the selected output, assigns it through
KScreen, and verifies that KWin actually reports the new profile before claiming
success.

## Status

Vivid is a 1.0 beta. This minimal source release includes the application,
installers, packaging, and user documentation. Development and automated test
materials are kept separate from this release. Physical-display behavior still
requires validation on the target hardware; software checks alone cannot prove
that a particular GPU, monitor, or Plasma release applies a profile correctly.

No change is reported as successful merely because a slider moved or a command
exited with status 0. Vivid re-reads the compositor's per-output colour state and
requires the expected profile path, colour source, and power preference.

## What Vivid does

- Discovers connected outputs and identifies each physical display using EDID,
  UUID, and connector information where available.
- Stores a separate saturation preference for every display.
- Applies changes immediately, with debounced slider updates.
- Restores saved preferences after login, reboot, or monitor reconnection.
- Preserves the original profile assignment and colour power preference.
- Restores the original state on reset or uninstall.
- Provides a GUI, CLI, diagnostics, safe mode, and KDE autostart integration.
- Refuses to guess when a display identity is ambiguous or a Vivid profile has
  no recovery snapshot.

The adjustment scale is `-100` to `+100`:

- `-100` is grayscale (zero saturation).
- `0` is the normal baseline and does not use a Vivid profile.
- `-50` halves the baseline saturation.
- `+50` means approximately 1.5 times the baseline saturation.
- `+100` means approximately twice the baseline saturation.

This is an adjustment scale, not a colorimeter-calibrated percentage of
perceived saturation. Values are clipped to the displayable RGB range.

## Why independent saturation is hard on Wayland

X11 tools such as `xrandr` and vendor control panels often rely on global GPU
colour settings or compositor-specific hooks. Those mechanisms are unavailable
or unsafe under native Wayland, and a global saturation change affects every
output.

KWin supports per-output ICC profiles. Vivid builds an ICC v2 profile whose
B2A transform applies a saturation matrix in gamma-encoded sRGB space. KWin only
runs the ICC shader, including the 3D CLUT used by this profile, when the output
prefers colour accuracy. Vivid therefore sets that preference while an
adjustment is active and restores the recorded original afterwards.

## Features

- Per-output saturation from `-100` to `+100`.
- Stable display identity with duplicate-EDID detection.
- Debounced live preview and explicit revert.
- Presets for common values.
- Display identification overlay.
- Direct per-display sliders in the system tray menu.
- Native KDE Plasma panel widget with per-display sliders.
- Atomic, versioned JSON settings with backup recovery.
- Original-state snapshots written before the first change.
- Content-addressed ICC cache with safe cleanup.
- Backend capability detection and truthful unsupported reporting.
- JSON output and stable exit codes for automation.
- KDE autostart management and safe uninstall flow.
- Fedora RPM spec and source installer.

## Supported systems

Verified in the development environment:

| Component | Version |
| --- | --- |
| Fedora Linux | 44 |
| KDE Plasma | 6.7.5 |
| KWin | 6.7.5 |
| KScreen | 6.7.5 |
| Python | 3.14.8 |
| PySide6 | 6.11.2 |
| Little CMS | 2.16 |

Expected to work on Plasma 6.8 and newer when the required KScreen interfaces
are present, but those releases have not been hardware-tested here. X11, GNOME,
COSMIC, HDR output, and compositors other than KWin are unsupported. See
[COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Installation

### Fedora RPM

Build the RPM from a checkout:

```bash
./scripts/build-rpm.sh
sudo dnf install rpmbuild/RPMS/noarch/vivid-1.0.0-1.fc44.noarch.rpm
```

The spec file is in `packaging/vivid.spec`. The build requires the Fedora
packaging toolchain and Python development packages:

```bash
sudo dnf install rpm-build rpmdevtools python3-devel python3-setuptools python3-wheel
```

The RPM is not stored in this repository. Build and install it locally using the
commands above.

### Source installation for the current user

The source installer creates a private virtual environment under
`~/.local/share/vivid/venv`, reuses the system PySide6 package, and installs
launchers into `~/.local/bin`. It does not use `sudo`.

```bash
./scripts/install.sh
```

Required Fedora packages:

```bash
sudo dnf install python3 python3-pyside6 libkscreen kwin plasma-workspace lcms2
```

Make sure `~/.local/bin` is on `PATH`, then run:

```bash
vivid-gui
```

The source installer also installs the **Vivid Saturation Controls** Plasma
widget. Add it to a panel from KDE's **Edit Mode → Add Widgets**, then search
for "Vivid". The widget and system-tray sliders control each display directly;
changes still use the same validated Vivid CLI/backend path.

To remove the application:

```bash
./scripts/uninstall.sh
```

The uninstaller asks Vivid to restore every display it changed before removing
application files. If restoration fails, it stops and preserves recovery data.
Use `./scripts/uninstall.sh --purge` only when you also want to delete settings,
recovery state, and cached profiles. See [INSTALLATION.md](docs/INSTALLATION.md).

## Quick start

```bash
vivid backend
vivid list
vivid set DP-1 30
vivid get DP-1
vivid reset DP-1
```

`DP-1` is an example output name. Use the names printed by `vivid list`, or a
unique model name, UUID prefix, or stable ID prefix.

### GUI

1. Start `vivid-gui` or select Vivid from the application launcher.
2. Select a display card.
3. Drag the saturation slider or choose a preset.
4. Use **Apply now** to commit immediately, or let the debounced preview commit.
5. Use **Identify** if you are unsure which card belongs to which monitor.
6. Use **Reset this display** or **Reset all** to restore the original profile.

The system tray menu and the optional Plasma panel widget also expose a
debounced slider for every connected display, so values can be changed without
opening the main window.

The window reports the verified compositor state, not just the requested value.
If KWin does not confirm the profile, the original state is restored where
possible and the error is shown.

### CLI examples

See [CLI.md](docs/CLI.md) for the complete command and JSON schema reference.

```bash
vivid list --json
vivid status
vivid backend --json
vivid set "Studio Display" 25 --yes
vivid set DP-1 -35
vivid get HDMI-A-1
vivid reset --all
vivid doctor --write /tmp/vivid-diagnostics.json
vivid safe-mode on
vivid autostart enable
vivid restore --quiet
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | Operation failed |
| `2` | Invalid usage or value |
| `3` | Backend or session unsupported |
| `4` | Display selector unknown or ambiguous |
| `130` | Interrupted |

All JSON output includes `schema_version`.

## Reset and recovery

Reset one display:

```bash
vivid reset DP-1
```

Reset every display Vivid changed:

```bash
vivid reset --all
```

If automatic restore is causing trouble, disable it first:

```bash
vivid safe-mode on
```

If the GUI cannot start, use the CLI or restore the profile manually in KDE
System Settings. The recovery snapshot is stored at
`~/.local/state/vivid/state.json`. The complete procedure is in
[RECOVERY.md](docs/RECOVERY.md).

## Uninstallation

For an RPM installation:

```bash
vivid uninstall
sudo dnf remove vivid
```

For a source installation:

```bash
./scripts/uninstall.sh
```

`vivid uninstall` restores changed displays, disables Vivid autostart, and removes
Vivid-owned generated profiles. It preserves settings and recovery state unless
`--purge` is given. If restoration fails, it stops without deleting the recovery
information.

## Troubleshooting

Start with diagnostics:

```bash
vivid backend
vivid doctor
```

Common issues and fixes are covered in
[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). The most common cause of a profile
that is selected but not applied is a colour power preference other than
**Prefer colour accuracy**. Vivid sets this automatically and verifies it.

Logs are written to `~/.local/state/vivid/vivid.log`.

## Limitations

- Native Wayland with KWin is required. X11 is unsupported.
- HDR output is not supported.
- The profile relies on KWin's ICC shader and colour accuracy preference.
- Some applications with their own colour-management pipeline may not show the
  same result.
- A monitor with a duplicated EDID and no usable UUID may require explicit
  confirmation.
- The adjustment is a saturation matrix, not a calibrated gamut mapping.
- Physical display acceptance testing requires two active displays.
- RPM packaging targets Fedora; compatibility with third-party repositories or
  non-Fedora RPM environments is not claimed.

## License

MIT. See [LICENSE](LICENSE).

The ICC B2A construction follows the method documented by the MIT-licensed
[plasma-vibrance](https://github.com/Celiz/plasma-vibrance) project. Vivid is an
independent implementation and is not affiliated with KDE or plasma-vibrance.
