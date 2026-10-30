#!/usr/bin/env bash
# Install Vivid for the current user. No root privileges are used.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$SCRIPT_DIR
APP_ID=io.github.vivid.DisplaySaturation
PREFIX=${PREFIX:-"$HOME/.local"}
BINDIR=${BINDIR:-"$PREFIX/bin"}
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
STATE_HOME=${XDG_STATE_HOME:-"$HOME/.local/state"}
APPDATA=${VIVID_DATA_DIR:-"$DATA_HOME/vivid"}
VENV=${VIVID_VENV:-"$APPDATA/venv"}
APPLICATIONS="$DATA_HOME/applications"
ICONS="$DATA_HOME/icons/hicolor/scalable/apps"
METAINFO="$DATA_HOME/metainfo"
DOCDIR="$DATA_HOME/doc/vivid"
PLASMOID_ID=io.github.vivid.DisplaySaturation
PLASMOID_DIR="$DATA_HOME/plasma/plasmoids/$PLASMOID_ID"
PYTHON=${PYTHON:-python3}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

warn() {
    printf 'warning: %s\n' "$*" >&2
}

info() {
    printf '%s\n' "$*"
}

usage() {
    cat <<'EOF'
Usage: ./install.sh

Install Vivid for the current user under ~/.local by default.

Environment:
  PREFIX          Installation prefix (default: ~/.local)
  BINDIR          Launcher directory (default: PREFIX/bin)
  PYTHON          Python interpreter to use (default: python3)
  VIVID_DATA_DIR  Application data directory (default: XDG_DATA_HOME/vivid)
  VIVID_VENV      Virtual environment path (default: VIVID_DATA_DIR/venv)

No sudo is used. Settings and generated profiles are stored in the XDG
configuration, data, and state directories described in docs/INSTALLATION.md.
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
    usage
    exit 0
fi

[[ -f $ROOT/pyproject.toml ]] || die "run this script from a Vivid source checkout"
command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON is not installed"
command -v install >/dev/null 2>&1 || die "the 'install' command is required"
command -v tar >/dev/null 2>&1 || die "tar is required"

"$PYTHON" - <<'PY' || die "Python 3.10 or newer is required"
import sys
if sys.version_info < (3, 10):
    raise SystemExit(1)
PY

if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    if [[ ${ID:-} != "fedora" ]]; then
        warn "${PRETTY_NAME:-this distribution} is not Fedora; packaging and testing target Fedora KDE"
    fi
else
    warn "could not read /etc/os-release; Fedora KDE is the supported target"
fi

session=${XDG_SESSION_TYPE:-unknown}
desktop=${XDG_CURRENT_DESKTOP:-unknown}
if [[ $session != "wayland" ]]; then
    warn "the current session is '$session', not Wayland; Vivid will report the backend as unsupported"
fi
if [[ $desktop != *KDE* && $desktop != *Plasma* ]]; then
    warn "the current desktop is '$desktop', not KDE Plasma; Vivid targets KWin"
fi

command -v kscreen-doctor >/dev/null 2>&1 || die \
    "kscreen-doctor is missing; install libkscreen (sudo dnf install libkscreen)"
command -v kpackagetool6 >/dev/null 2>&1 || die \
    "kpackagetool6 is missing; install KDE Plasma workspace tools"

"$PYTHON" - <<'PY' || die "missing runtime dependencies; install python3-pyside6 and lcms2"
import ctypes.util
import sys

missing = []
try:
    import PySide6  # noqa: F401
except Exception:
    missing.append("PySide6 (Fedora: python3-pyside6)")
if not ctypes.util.find_library("lcms2"):
    missing.append("Little CMS 2 (Fedora: lcms2)")
if missing:
    print("missing: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)
PY

mkdir -p "$APPDATA" "$BINDIR"
chmod 700 "$APPDATA" 2>/dev/null || true

if [[ ! -x $VENV/bin/python ]]; then
    info "Creating a private virtual environment in $VENV"
    "$PYTHON" -m venv --system-site-packages "$VENV" || die \
        "could not create a virtual environment; install python3-venv"
fi

"$VENV/bin/python" -m pip --version >/dev/null 2>&1 || die \
    "pip is missing from the virtual environment; install python3-pip and retry"

info "Installing Vivid into $VENV"
"$VENV/bin/python" -m pip install \
    --quiet --upgrade --no-deps --no-build-isolation "$ROOT" || die \
    "Python package installation failed"

write_launcher() {
    local target=$1
    local command=$2
    local temporary="${target}.tmp.$$"
    printf '#!/bin/sh\nexec %q "$@"\n' "$command" >"$temporary"
    chmod 0755 "$temporary"
    mv -f "$temporary" "$target"
}

write_launcher "$BINDIR/vivid" "$VENV/bin/vivid"
write_launcher "$BINDIR/vivid-gui" "$VENV/bin/vivid-gui"

install -Dm0644 "$ROOT/packaging/vivid.desktop" "$APPLICATIONS/$APP_ID.desktop"
install -Dm0644 "$ROOT/packaging/io.github.vivid.DisplaySaturation.metainfo.xml" \
    "$METAINFO/$APP_ID.metainfo.xml"
install -Dm0644 "$ROOT/packaging/icons/hicolor/scalable/apps/$APP_ID.svg" \
    "$ICONS/$APP_ID.svg"

# Point the user-level desktop entry and TryExec at the absolute launcher.
"$PYTHON" - "$APPLICATIONS/$APP_ID.desktop" "$BINDIR/vivid-gui" <<'PY'
import shlex
import sys

path, command = sys.argv[1], sys.argv[2]
quoted = '"' + command.replace("\\", "\\\\").replace('"', '\\"') + '"'
lines = []
with open(path, encoding="utf-8") as handle:
    for line in handle:
        if line.startswith(("Exec=", "TryExec=")):
            key = line.split("=", 1)[0]
            value = quoted if key == "Exec" else shlex.quote(command)
            lines.append(f"{key}={value}\n")
        else:
            lines.append(line)
with open(path, "w", encoding="utf-8") as handle:
    handle.writelines(lines)
PY

install -d -m0755 "$DOCDIR"
for document in README.md SECURITY.md LICENSE; do
    install -m0644 "$ROOT/$document" "$DOCDIR/$document"
done
for document in "$ROOT"/docs/*.md; do
    [[ -e $document ]] || continue
    install -m0644 "$document" "$DOCDIR/$(basename "$document")"
done

"$VENV/bin/python" -c 'from vivid.paths import ensure_runtime_dirs; ensure_runtime_dirs()'

if [[ -d $PLASMOID_DIR ]]; then
    kpackagetool6 --type Plasma/Applet --upgrade "$ROOT/packaging/plasmoid" || die \
        "could not upgrade the Vivid Plasma panel widget"
else
    kpackagetool6 --type Plasma/Applet --install "$ROOT/packaging/plasmoid" || die \
        "could not install the Vivid Plasma panel widget"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

info ""
info "Vivid was installed for the current user."
info "  CLI:     $BINDIR/vivid"
info "  GUI:     $BINDIR/vivid-gui"
info "  Panel:   Vivid Saturation Controls (add it from KDE's Add Widgets menu)"
info "  Config:  $CONFIG_HOME/vivid/config.json"
info "  State:   $STATE_HOME/vivid/state.json"
info ""
info "Ensure $BINDIR is on PATH, then run:"
info "  vivid capabilities"
info "  vivid list"
info "  vivid-gui"
info ""
info "To remove it, run ./uninstall.sh"
