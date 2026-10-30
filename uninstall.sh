#!/usr/bin/env bash
# Safely uninstall a source installation. No root privileges are used.
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
AUTOSTART="$CONFIG_HOME/autostart/vivid.desktop"
PLASMOID_ID=io.github.vivid.DisplaySaturation
PLASMOID_DIR="$DATA_HOME/plasma/plasmoids/$PLASMOID_ID"
PURGE=0

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '%s\n' "$*"
}

usage() {
    cat <<'EOF'
Usage: ./uninstall.sh [--purge]

Restore every display Vivid changed, disable autostart, and remove the
user-level application files.

By default, settings, recovery state, and the user configuration directory are
kept. Pass --purge to remove them after a successful restoration.

If display restoration fails, the uninstaller stops and keeps recovery data.
EOF
}

for argument in "$@"; do
    case "$argument" in
        --purge)
            PURGE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $argument (use --help)"
            ;;
    esac
done

VIVID_BIN=""
if [[ -x $VENV/bin/vivid ]]; then
    VIVID_BIN="$VENV/bin/vivid"
elif command -v vivid >/dev/null 2>&1; then
    VIVID_BIN=$(command -v vivid)
fi

if [[ -z $VIVID_BIN ]]; then
    die "the Vivid CLI was not found; cannot verify display restoration. \
Restore displays manually in System Settings, then remove generated profiles from \
$APPDATA/icc and delete $DOCDIR, $VENV, and the desktop files."
fi

if [[ -d $PLASMOID_DIR ]] && ! command -v kpackagetool6 >/dev/null 2>&1; then
    die "kpackagetool6 is required to remove the installed Vivid Plasma panel widget"
fi

info "Restoring displays changed by Vivid"
if [[ $PURGE -eq 1 ]]; then
    "$VIVID_BIN" uninstall --purge || die \
        "display restoration failed; nothing was removed and recovery data was preserved. \
Read $ROOT/docs/RECOVERY.md"
else
    "$VIVID_BIN" uninstall || die \
        "display restoration failed; nothing was removed and recovery data was preserved. \
Read $ROOT/docs/RECOVERY.md"
fi

if [[ -d $PLASMOID_DIR ]]; then
    kpackagetool6 --type Plasma/Applet --remove "$PLASMOID_ID" || die \
        "could not remove the Vivid Plasma panel widget; other files were preserved"
fi

rm -f "$BINDIR/vivid" "$BINDIR/vivid-gui"
rm -f "$APPLICATIONS/$APP_ID.desktop"
rm -f "$ICONS/$APP_ID.svg"
rm -f "$METAINFO/$APP_ID.metainfo.xml"
rm -f "$AUTOSTART"
rm -rf "$DOCDIR" "$VENV"

if [[ $PURGE -eq 1 ]]; then
    rm -rf "$APPDATA"
    rm -rf "$CONFIG_HOME/vivid"
    rm -rf "$STATE_HOME/vivid"
    info "Vivid and all user data were removed."
else
    info "Vivid was removed."
    info "Settings and recovery state were preserved:"
    info "  $CONFIG_HOME/vivid"
    info "  $STATE_HOME/vivid"
    info "Run this command again with --purge to remove them."
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS" >/dev/null 2>&1 || true
fi
