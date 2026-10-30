# Recovery

Vivid changes a display only after writing an original-state snapshot. This
guide explains how to undo a change, disable automatic restoration, and recover
when the GUI or compositor refuses a profile.

## Important files

| Path | Contents |
| --- | --- |
| `~/.local/state/vivid/state.json` | Original profile path, colour source, power preference, backend versions |
| `~/.local/state/vivid/vivid.log` | Rotating application log |
| `~/.local/share/vivid/icc/` | Generated `vivid-*.icc` profiles |
| `~/.config/vivid/config.json` | Saved per-display preferences |
| `~/.config/autostart/vivid.desktop` | KDE autostart entry, when enabled |

Do not delete `state.json` or the generated profiles until the original profile
has been restored. They are the information needed to recover.

## Quick commands

```bash
vivid reset DP-1            # restore one display by output name or stable ID
vivid reset --all           # restore every display Vivid changed
vivid safe-mode on          # stop automatic restoration
vivid autostart disable     # stop restoration at login
vivid doctor --write /tmp/vivid-diagnostics.json
```

`vivid reset --all` restores recorded original assignments. It does not force
every display to sRGB and it does not touch outputs without a Vivid snapshot.

## Reset one display

```bash
vivid list
vivid reset HDMI-A-1
```

The output name is the connector label printed by `vivid list`. A stable ID,
UUID, or unique model name is also accepted. If a selector matches more than one
display, Vivid refuses to choose one; use the connector or stable ID instead.

A successful reset is verified by re-reading the compositor state. An exit code
of 0 without that verification is not reported as success.

## Reset all displays

```bash
vivid reset --all
```

This is idempotent. A display with no Vivid adjustment is left untouched. If one
display cannot be restored, the command returns a nonzero exit code and the other
results are still printed.

## Disable automatic restoration first

If restoration keeps trying and is making the desktop hard to use:

```bash
vivid safe-mode on
```

Safe mode prevents login restoration, hotplug restoration, and automatic
reapplication. It does not undo an existing profile; use `vivid reset` after
entering safe mode.

To re-enable automatic restoration:

```bash
vivid safe-mode off
```

To disable only login restoration:

```bash
vivid autostart disable
```

## The GUI will not start

Use the CLI:

```bash
vivid status
vivid reset --all
vivid doctor --write /tmp/vivid-diagnostics.json
```

If the CLI is also unavailable, restore the profile in KDE System Settings:

1. Open **System Settings → Display and Monitor → Display Configuration**.
2. Select the affected output.
3. Open the colour profile control.
4. Select the profile that was active before Vivid. The original path is in
   `~/.local/state/vivid/state.json` under `originals` and `icc_profile_path`.
5. If the original source was `EDID` or `SRGB`, select that source instead of an
   ICC file.
6. Set the colour power preference back to its recorded value.

Do not select a generic sRGB profile merely to make the Vivid profile disappear.

## A Vivid profile is active but there is no snapshot

Vivid refuses to guess when it sees a `vivid-*.icc` profile but no recovery
snapshot. This can happen after partial manual cleanup or if state was deleted.

1. Read the current path from `vivid doctor` or `vivid list --json`.
2. Find the original profile path in KDE System Settings or from your own notes.
3. Select the original profile manually.
4. If you have no record of the original profile, select the output's EDID
   source, or the monitor's previous calibration profile if you know it.
5. Remove only the orphaned generated file after the display is restored.
6. Run `vivid doctor` to confirm that no Vivid profile is active.

## The compositor rejects the profile

Typical messages:

- `KWin rejected the display profile`
- `the compositor did not confirm the adjustment`
- `the original profile could not be restored`

Check:

```bash
vivid doctor
vivid backend
```

Common causes:

- The original ICC file was moved or deleted.
- The generated profile directory is not readable by your user.
- KScreen does not expose `iccprofile` or `colorProfileSource`.
- The colour power preference is not `PreferAccuracy`.
- The output name changed while the operation was in progress.

If Vivid could not restore the original profile, keep the recovery snapshot and
restore the assignment manually in System Settings. Reconnect a disconnected
monitor and run `vivid reset --all` again; Vivid refuses to declare an uninstall
complete while a saved display is disconnected.

## KScreen rejects an argument

Run `kscreen-doctor --help` and check that these options exist:

```text
--outputs
--iccprofile
--colorprofilesource
--colorpowertradeoff
```

If they are missing, the installed KScreen does not provide the interface Vivid
requires. Keep Vivid in safe mode or remove it; do not attempt a global shader,
gamma, or `xrandr` workaround on Wayland.

## Malformed settings or state

Vivid quarantines malformed JSON as `config.json.corrupt-<timestamp>` or
`state.json.corrupt-<timestamp>` and tries to recover the `.bak` copy. It does
not silently discard preferences.

If recovery fails:

1. Preserve the quarantine file.
2. Inspect the `.bak` file.
3. Run `vivid doctor --write` and attach the report to a bug report after
   removing sensitive identifiers.

## Uninstallation

Source installation:

```bash
./scripts/uninstall.sh
```

RPM:

```bash
vivid uninstall
sudo dnf remove vivid
```

Uninstallation attempts restoration before removing generated profiles. If
restoration fails, the uninstaller stops and keeps the recovery data. Use
`--purge` only after restoration succeeds and only if you also want to delete
settings and recovery state.

## What not to do

- Do not run Vivid as root.
- Do not use `xrandr` as a Wayland workaround.
- Do not apply a global saturation or gamma change to hide a failed per-output
  change.
- Do not force every display to sRGB during reset or uninstall.
- Do not delete `state.json` before confirming that every display was restored.
- Do not replace an original profile file with a Vivid-generated profile of the
  same name; Vivid uses a separate `vivid-*.icc` namespace.
