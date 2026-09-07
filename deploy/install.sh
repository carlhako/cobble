#!/usr/bin/env bash
# cobble installer for an unprivileged amd64 Debian 13 LXC.
#
# Performs platform preflight, installs runtime packages (python3, curl, unzip —
# no JavaScript runtime or compiler), fetches the release tarball (pre-built web
# interface + a wheelhouse of every Python dependency), lays out the directory
# structure, and installs and enables cobble.service.
#
# Usage:
#   curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh | bash
#   RELEASE_TAG=v0.1.0 bash install.sh          # pin a version
#   COBBLE_TARBALL=/path/to/cobble-*.tar.gz bash install.sh   # offline

set -euo pipefail

REPO="${COBBLE_REPO:-carlhako/cobble}"
RELEASE_TAG="${RELEASE_TAG:-latest}"
PREFIX="/opt/cobble"
BEDROCK_ROOT="/srv/bedrock"
STATE_DIR="/var/lib/cobble"
BACKUP_DIR="/backup"
SERVICE_USER="cobble"
MIN_GLIBC_MAJOR=2
MIN_GLIBC_MINOR=26

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"

# --- platform preflight ---------------------------------------------
arch="$(uname -m)"
case "$arch" in
  x86_64|amd64) ;;
  *) die "the Bedrock Dedicated Server is unavailable for this architecture ($arch); it is published only for 64-bit x86 (amd64)" ;;
esac

glibc_ver="$(ldd --version 2>/dev/null | head -n1 | grep -oE '[0-9]+\.[0-9]+' | head -n1 || true)"
[ -n "$glibc_ver" ] || die "could not determine the system C library version; the Bedrock server requires glibc ${MIN_GLIBC_MAJOR}.${MIN_GLIBC_MINOR} or newer"
glibc_major="${glibc_ver%%.*}"; glibc_minor="${glibc_ver#*.}"
if [ "$glibc_major" -lt "$MIN_GLIBC_MAJOR" ] || { [ "$glibc_major" -eq "$MIN_GLIBC_MAJOR" ] && [ "$glibc_minor" -lt "$MIN_GLIBC_MINOR" ]; }; then
  die "system C library is glibc ${glibc_ver}; the Bedrock server requires at least glibc ${MIN_GLIBC_MAJOR}.${MIN_GLIBC_MINOR}"
fi
log "platform ok: ${arch}, glibc ${glibc_ver}"

# --- runtime packages (no node, no compiler) ---------------------
log "installing python3, curl, unzip"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl unzip ca-certificates >/dev/null

# --- service user -----------------------------------------------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  log "creating service user '$SERVICE_USER'"
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

# --- fetch the release ----------------------------------------
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
if [ -n "${COBBLE_TARBALL:-}" ]; then
  log "using local tarball $COBBLE_TARBALL"
  tar -xzf "$COBBLE_TARBALL" -C "$work"
else
  if [ "$RELEASE_TAG" = "latest" ]; then
    base="https://github.com/${REPO}/releases/latest/download"
  else
    base="https://github.com/${REPO}/releases/download/${RELEASE_TAG}"
  fi
  log "downloading cobble release from $base"
  curl -fsSL "${base}/cobble.tar.gz" -o "$work/cobble.tar.gz" \
    || die "could not download the release tarball"
  tar -xzf "$work/cobble.tar.gz" -C "$work"
fi
src="$work/cobble"
wheel="$(ls "$src"/dist/cobble-*-py3-none-any.whl 2>/dev/null | head -n1 || true)"
[ -n "$wheel" ] || die "release tarball has no cobble wheel"

# --- install application -----------------------------------
log "installing application to $PREFIX"
mkdir -p "$PREFIX"
cp -a "$src/README.md" "$PREFIX/"

log "creating virtualenv and installing cobble"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
# Install the bundled wheel BY PATH (never by bare name — an unrelated project
# named "cobble" exists on PyPI). --only-binary=:all: is the "no compiler on the
# host" guarantee: every dependency is installed as a pre-built wheel or the
# install fails loudly. Set COBBLE_WHEELHOUSE=/path for a fully offline install.
if [ -n "${COBBLE_WHEELHOUSE:-}" ]; then
  "$PREFIX/venv/bin/pip" install --quiet --only-binary=:all: --no-index \
    --find-links "$COBBLE_WHEELHOUSE" "$wheel"
else
  "$PREFIX/venv/bin/pip" install --quiet --only-binary=:all: "$wheel"
fi

# --- directory layout (design.md D5) --------------------
log "creating $BEDROCK_ROOT, $STATE_DIR, $BACKUP_DIR"
mkdir -p "$BEDROCK_ROOT/versions" "$STATE_DIR" "$BACKUP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$PREFIX" "$BEDROCK_ROOT" "$STATE_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR" || warn "could not chown $BACKUP_DIR (bind mount?); ensure cobble can write to it"

# --- systemd unit ------------------------------------------
log "installing cobble.service"
install -m 0644 "$src/deploy/cobble.service" /etc/systemd/system/cobble.service
systemctl daemon-reload
systemctl enable --now cobble.service

log "done. cobble is starting; on first run it will download the current Bedrock server."
log "open http://$(hostname -I | awk '{print $1}'):8000/ on the LAN"
