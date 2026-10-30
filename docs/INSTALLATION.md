# Installation

Vivid targets Fedora KDE Plasma 6 on native Wayland. Routine use does not require
root. The source installer installs only into the current user's home directory.

## Dependencies

Fedora packages:

```bash
sudo dnf install python3 python3-pip python3-pyside6 libkscreen kwin \
  plasma-workspace plasma5support lcms2
```

`libkscreen` provides `/usr/bin/kscreen-doctor`. `kwin` and `plasma-workspace`
provide the compositor and Plasma session. Little CMS 2 is loaded through
`ctypes`.

For development and RPM builds:

```bash
sudo dnf install python3-devel python3-setuptools python3-wheel rpm-build rpmdevtools \
  pyproject-rpm-macros desktop-file-utils appstream
```

## Source installation

From a checkout:

```bash
./install.sh
```

The installer:

- Checks Python, PySide6, Little CMS, `kscreen-doctor`, `kpackagetool6`, Fedora,
  and the session.
- Creates a private virtual environment at `~/.local/share/vivid/venv`.
- Reuses system PySide6 through `--system-site-packages`.
- Installs the `vivid` and `vivid-gui` launchers.
- Installs the native Plasma panel widget through `kpackagetool6`.
- Installs the desktop entry, icon, AppStream metadata, and documentation.
- Creates Vivid runtime directories.
- Does not use `sudo` and does not write to system directories.

Ensure `~/.local/bin` is on `PATH`:

```bash
command -v vivid
vivid --version
```

Start the GUI:

```bash
vivid-gui
```

or select Vivid from the application launcher.

To add the panel widget, enter KDE panel edit mode, choose **Add Widgets**, and
search for **Vivid Saturation Controls**. Open it to see one slider per display;
click its panel button to open the controls; no main-window launch is needed.
Drag a display's slider and Vivid applies the value when you release. Keyboard
or wheel adjustments apply after a short pause. The current value appears beside
each slider and in the widget tooltip. **Reset all to baseline** restores the
original profile for every display Vivid has changed. The widget refreshes the
display list when it opens. Its sliders use the same `-100` to `+100` scale as
the GUI and CLI. It resolves the Vivid launcher from the usual user-install and
RPM paths, so the panel does not depend on Plasma inheriting `~/.local/bin` in
its `PATH`.

### Custom prefix

The installer supports a custom user prefix:

```bash
PREFIX="$HOME/bin" ./install.sh
```

The application data still lives under `XDG_DATA_HOME`, and launchers are placed
in `$PREFIX/bin`. The desktop entry uses the absolute launcher path.

## Fedora RPM

Build an RPM from the checkout:

```bash
./build-rpm.sh
```

The output is under `rpmbuild/RPMS/noarch/`. Install it with:

```bash
sudo dnf install rpmbuild/RPMS/noarch/vivid-1.0.0-1.fc44.noarch.rpm
```

The spec is `packaging/vivid.spec`. It installs the Python package, CLI and GUI
entry points, native Plasma panel widget, desktop entry, icon, AppStream metadata,
documentation, and license.
Runtime dependencies are declared on Fedora packages; Qt and Little CMS are not
bundled.

The spec and build script were validated by building both RPMs in a Fedora 44
container. Compatibility with third-party repositories and non-Fedora RPM
environments is not claimed.

## Upgrading

Source installation:

```bash
./install.sh
```

The installer upgrades the package inside the existing virtual environment and
refreshes launchers and desktop files. Settings and recovery state are preserved.

RPM:

```bash
sudo dnf upgrade vivid
```

Settings and recovery state are preserved across upgrades.

## Uninstallation

Source installation:

```bash
./uninstall.sh
```

RPM:

```bash
vivid uninstall
sudo dnf remove vivid
```

Both paths attempt safe restoration first. `vivid uninstall` restores every display
Vivid changed, disables autostart, and removes Vivid-owned generated profiles. It
preserves settings and recovery state by default.

To remove user data too:

```bash
vivid uninstall --purge
```

For the source installer:

```bash
./uninstall.sh --purge
```

If restoration fails, uninstallation stops and keeps the recovery snapshot. See
[RECOVERY.md](RECOVERY.md).

## Verifying the installation

See [CLI.md](CLI.md) for command and JSON details, and
[TROUBLESHOOTING.md](TROUBLESHOOTING.md) if a check fails.

```bash
vivid --version
vivid capabilities
vivid list
vivid doctor
```

`vivid capabilities` must report `Supported: yes` on a supported KDE Wayland
session.
A warning about a single display is expected on a laptop without an external
monitor. A warning about an unverified Plasma version means the required
interfaces were detected but that release has not been hardware-tested.

## Files and paths

| Path | Purpose |
| --- | --- |
| `~/.local/bin/vivid` | CLI launcher for source installs |
| `~/.local/bin/vivid-gui` | GUI launcher for source installs |
| `~/.local/share/vivid/venv` | Source-install virtual environment |
| `~/.local/share/vivid/icc` | Generated ICC profiles |
| `~/.config/vivid/config.json` | Settings |
| `~/.local/state/vivid/state.json` | Original-state recovery snapshots |
| `~/.local/state/vivid/vivid.log` | Rotating log |
| `~/.config/autostart/vivid.desktop` | KDE autostart entry, when enabled |
| `~/.local/share/applications/io.github.vivid.DisplaySaturation.desktop` | Desktop entry |
| `~/.local/share/icons/hicolor/scalable/apps/io.github.vivid.DisplaySaturation.svg` | Icon |
| `~/.local/share/metainfo/io.github.vivid.DisplaySaturation.metainfo.xml` | AppStream metadata |
| `~/.local/share/plasma/plasmoids/io.github.vivid.DisplaySaturation` | Native Plasma panel widget |

The desktop entry and icon are installed under `/usr/share` for RPM installs.
