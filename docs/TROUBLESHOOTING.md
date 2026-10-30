# Troubleshooting

Start with the read-only checks:

```bash
vivid backend
vivid list
vivid status
vivid doctor --write /tmp/vivid-diagnostics.json
```

`vivid backend` explains why the active session is unsupported. The log is at
`~/.local/state/vivid/vivid.log`. Run a command with `--verbose` for debug
logging. Never run Vivid as root.

## Vivid reports the backend as unsupported

Run `vivid backend` and match the reason:

### "a native Wayland session is required; X11 and unknown sessions are unsupported"

Log out and choose **Plasma (Wayland)** at the login screen. There is no X11
backend, and Vivid does not use `xrandr`.

### "KWin on KDE Plasma is the only supported compositor"

Vivid requires KWin. GNOME, Sway, COSMIC, and custom compositors are unsupported.
The command checks `XDG_CURRENT_DESKTOP`; if it is empty, start Vivid from a
normal Plasma session rather than from a bare TTY.

### "kscreen-doctor is not installed or not executable"

```bash
sudo dnf install libkscreen
kscreen-doctor --help
```

### "the installed kscreen-doctor does not expose per-output ICC profile paths"

The KScreen version is too old or is not the KDE build. Check:

```bash
rpm -q kscreen
kscreen-doctor --help | grep -E 'iccprofile|colorProfileSource'
```

Upgrade the Fedora KDE/Plasma packages. Vivid will not fall back to a global
colour change.

### "the installed kscreen-doctor does not expose the colour profile source setting"

The ICC path argument exists but the source control does not. The backend cannot
distinguish EDID, sRGB, and file sources safely, so it refuses to change a
display.

### "kscreen-doctor could not enumerate outputs as JSON" or "no outputs were reported"

Run:

```bash
kscreen-doctor -j
```

If this fails, the display service is broken. Check the Plasma session and
`journalctl --user -u plasma-kscreen.service`. Restarting the session is safer
than restarting KWin while a Vivid profile is active.

### "Little CMS 2 (liblcms2) is not available"

```bash
sudo dnf install lcms2
```

Without Little CMS, Vivid cannot generate or inspect ICC profiles.

## The GUI does not start

Use the CLI:

```bash
vivid status
vivid reset --all
```

If `vivid-gui` exits with a Qt plugin error, make sure the session is Wayland and
that `python3-pyside6` is installed. Run `vivid-gui` from a terminal to see the
error. The GUI is optional; every operation is available through the CLI.

## A display shows "conflict" or "needs confirmation"

Vivid found a `vivid-*.icc` profile but no saved original state, or two displays
share an identity it cannot disambiguate.

- Without a snapshot, restore the previous profile manually in System Settings,
  then remove the orphaned generated profile. See [RECOVERY.md](RECOVERY.md).
- With duplicate identities, use explicit `vivid reset <selector>` and inspect
  the selected output. Automatic restore is intentionally disabled until the
  user confirms.

Do not add `--yes` merely to silence the warning; confirm the correct physical
monitor first.

## A profile is selected but the display looks unchanged

KWin runs the ICC shader, including the 3D CLUT, only in colour-accuracy mode.

```bash
vivid status
vivid doctor
```

Check that `color_power_tradeoff` is `PreferAccuracy` and that the applied profile
path is the generated `vivid-*.icc`. Vivid sets accuracy mode while an adjustment
is active, but a later manual change in System Settings can override it.

Also check:

- The saturation value is not `0`.
- The application's own colour management is not overriding the output.
- The display is not in HDR mode; HDR is unsupported.
- You are looking at the intended physical output. Use `vivid identify DP-1`.

## "KWin rejected the display profile"

The compositor accepted the command but verification did not observe the new
profile. Common causes:

- The generated profile is unreadable or was removed during the operation.
- The output name changed because the monitor was unplugged.
- KScreen is not honouring `iccprofile` or `colorProfileSource`.
- Another tool is rewriting the output configuration.

Run:

```bash
vivid doctor --write /tmp/vivid-diagnostics.json
ls -l ~/.local/share/vivid/icc
```

Vivid automatically attempts to restore the original assignment after a failed
apply. Confirm the outcome with `vivid reset --all` if necessary.

## "the original profile could not be restored"

The original ICC path may have been moved or deleted, or the monitor is no longer
connected. Keep `~/.local/state/vivid/state.json`. Restore the profile manually in
System Settings using the recorded path/source. If the file is gone, select the
output's EDID source or the previous calibration profile.

Reconnect the display and run:

```bash
vivid reset --all
```

## Uninstall refuses to finish

`vivid uninstall` stops when:

- restoration of a connected display fails, or
- a saved display is disconnected, or
- no original snapshot exists for an active Vivid profile.

Reconnect all saved displays, run `vivid reset --all`, then retry. Recovery data
is deliberately preserved on failure. Do not delete state or generated profiles
first.

## Autostart keeps changing a display

```bash
vivid autostart disable
vivid safe-mode on
vivid reset --all
```

Safe mode suppresses automatic restore at login and hotplug. `autostart disable`
removes the KDE autostart entry. Use `vivid autostart status` and
`vivid safe-mode status` to confirm.

## Settings or state are corrupt

Vivid writes settings atomically and keeps a `.bak` copy. Malformed JSON is
quarantined as `*.corrupt-<timestamp>`. Check the log and `vivid doctor`; the
report includes settings and recovery paths. Keep the quarantine file if you
file a bug.

## Collecting a useful report

```bash
vivid --version
vivid backend --json > /tmp/vivid-backend.json
vivid doctor --write /tmp/vivid-diagnostics.json
vivid list --json > /tmp/vivid-displays.json
journalctl --user -b --no-pager > /tmp/vivid-journal.txt
```

Review the files before posting. Remove serial numbers or other identifiers you
do not want to share, but keep KScreen and Plasma version details.

## What not to try

- Running Vivid with `sudo`.
- `xrandr` or X11 gamma tools in a Wayland session.
- Global saturation, shader, or gamma changes to work around a per-output issue.
- Forcing every display to sRGB during reset.
- Deleting `state.json` before confirming restoration.
- Replacing an original ICC file with a generated Vivid profile.
