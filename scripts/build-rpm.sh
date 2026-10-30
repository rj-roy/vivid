#!/usr/bin/env bash
# Build a Fedora source RPM and binary RPM from this checkout.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
NAME=vivid
TOPDIR=${RPM_TOPDIR:-"$ROOT/rpmbuild"}
SPEC="$ROOT/packaging/vivid.spec"

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

info() {
    printf '%s\n' "$*"
}

usage() {
    cat <<'EOF'
Usage: ./scripts/build-rpm.sh

Build a source tarball from the current checkout and run rpmbuild. The output is
written to rpmbuild/RPMS and rpmbuild/SRPMS.

Environment:
  RPM_TOPDIR  rpmbuild top directory (default: ./rpmbuild)

Required Fedora packages:
  rpm-build rpmdevtools python3-devel python3-setuptools python3-wheel \
  pyproject-rpm-macros desktop-file-utils

Build requirements are not installed automatically and sudo is never used.
EOF
}

if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
    usage
    exit 0
fi

[[ -f $ROOT/pyproject.toml ]] || die "run this script from a Vivid source checkout"
[[ -f $SPEC ]] || die "missing $SPEC"
command -v rpmbuild >/dev/null 2>&1 || die "rpmbuild is missing; install rpm-build"
command -v tar >/dev/null 2>&1 || die "tar is missing"

VERSION=$(
    python3 - "$ROOT/pyproject.toml" <<'PY'
import sys
import tomllib

with open(sys.argv[1], "rb") as handle:
    data = tomllib.load(handle)
print(data["project"]["version"])
PY
)

info "Preparing $NAME $VERSION"
mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/vivid-rpm.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/$NAME-$VERSION"
tar \
    -C "$ROOT" \
    --exclude='./rpmbuild' \
    --exclude='./.git' \
    --exclude='./.github' \
    --exclude='./.venv' \
    --exclude='./venv' \
    --exclude='./build' \
    --exclude='./dist' \
    --exclude='./*.egg-info' \
    --exclude='./tests' \
    --exclude='./prd.md' \
    --exclude='./requirements-dev.txt' \
    --exclude='./CONTRIBUTING.md' \
    --exclude='./CODE_OF_CONDUCT.md' \
    --exclude='./docs/ARCHITECTURE.md' \
    --exclude='./docs/BACKEND.md' \
    --exclude='./docs/TESTING.md' \
    --exclude='./docs/screenshot.png' \
    --exclude='./__pycache__' \
    --exclude='./.pytest_cache' \
    --exclude='./.mypy_cache' \
    --exclude='./.ruff_cache' \
    --exclude='*.pyc' \
    -cf - . | tar -C "$STAGE/$NAME-$VERSION" -xf -

TARBALL="$TOPDIR/SOURCES/$NAME-$VERSION.tar.gz"
tar -C "$STAGE" --sort=name --owner=0 --group=0 --numeric-owner -czf "$TARBALL" "$NAME-$VERSION"
cp -f "$SPEC" "$TOPDIR/SPECS/$NAME.spec"

if command -v rpmspec >/dev/null 2>&1; then
    rpmspec -P "$TOPDIR/SPECS/$NAME.spec" >/dev/null || die "the RPM spec is not valid"
fi

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$ROOT/packaging/vivid.desktop" || die \
        "the desktop entry failed validation"
else
    info "warning: desktop-file-validate is unavailable; skipping desktop entry validation"
fi

if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate --no-net \
        "$ROOT/packaging/io.github.vivid.DisplaySaturation.metainfo.xml" || die \
        "the AppStream metadata failed validation"
else
    info "warning: appstreamcli is unavailable; skipping AppStream validation"
fi

info "Building RPM"
rpmbuild \
    --define "_topdir $TOPDIR" \
    --define "use_source_date_epoch_as_buildtime 1" \
    -ba "$TOPDIR/SPECS/$NAME.spec"

info ""
info "Built packages:"
find "$TOPDIR/RPMS" "$TOPDIR/SRPMS" -type f \( -name '*.rpm' -o -name '*.src.rpm' \) -print
