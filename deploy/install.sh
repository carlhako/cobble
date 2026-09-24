#!/usr/bin/env bash
# cobble installer for an unprivileged amd64 Debian 13 LXC.
#
# Performs platform preflight, installs runtime packages (python3, curl, unzip —
# no JavaScript runtime or compiler), fetches the release tarball (pre-built web
# interface + a wheelhouse of every Python dependency), lays out the directory
# structure, installs and enables cobble.service, and installs the root upgrade
# helper (cobble-upgrade.path/.service) that the web interface's one-click
# upgrade uses.
#
# Re-running it on an existing install is an in-place upgrade: the world, the
# Bedrock installation, cobble's state and backups are left alone. The new venv
# is built beside the old one and swapped in; if the new cobble does not come
# up, the previous venv and unit are restored.
#
# Usage (as root; a fresh Debian LXC lacks curl — `apt-get install -y curl` first):
#   curl -fsSL https://github.com/carlhako/cobble/releases/latest/download/install.sh | bash
#   RELEASE_TAG=v0.1.0 bash install.sh          # pin a version
#   COBBLE_TARBALL=/path/to/cobble-*.tar.gz bash install.sh   # offline
#
# Upgrading: from v0.5.0 on, use Updates & Backups -> Settings -> "Upgrade" in
# the web interface. Installs of v0.4.0 and earlier have no upgrade helper yet:
# run the curl command above once as root, and one-click upgrades work after.

set -euo pipefail

REPO="${COBBLE_REPO:-carlhako/cobble}"
RELEASE_TAG="${RELEASE_TAG:-latest}"
PREFIX="/opt/cobble"
BEDROCK_ROOT="/srv/bedrock"
STATE_DIR="/var/lib/cobble"
BACKUP_DIR="/backup"
SERVICE_USER="cobble"
HELPER_DIR="/usr/local/libexec/cobble"
HELPER_STATUS_DIR="/var/lib/cobble-upgrade"
MIN_GLIBC_MAJOR=2
MIN_GLIBC_MINOR=26

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mXX \033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run as root"
# REPO is baked into the root upgrade helper below; accept only owner/name.
[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "COBBLE_REPO must look like owner/name"

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
# $PREFIX is root-owned, top to bottom: root builds and runs the new venv in it,
# and an upgrade can be requested by the unprivileged service, so the service
# user must never be able to swap anything in here. cobble only reads it
# (cobble.service has ProtectSystem=strict). Installs up to v0.4.0 made it
# cobble-owned; take it back before building anything.
chown -R root:root "$PREFIX"
chmod 0755 "$PREFIX"
rm -f "$PREFIX/README.md"
cp "$src/README.md" "$PREFIX/"

# Build the new venv beside the live one so a failed build leaves the running
# cobble untouched (design.md D6). pip is always run as `python -m pip`: the
# venv is renamed after it is built, so its bin/ scripts are re-pointed below.
new_venv="$PREFIX/venv.new"
rm -rf "$new_venv"
log "creating virtualenv and installing cobble"
python3 -m venv "$new_venv"
"$new_venv/bin/python" -m pip install --quiet --upgrade pip
# Install the bundled wheel BY PATH (never by bare name — an unrelated project
# named "cobble" exists on PyPI). --only-binary=:all: is the "no compiler on the
# host" guarantee: every dependency is installed as a pre-built wheel or the
# install fails loudly. Set COBBLE_WHEELHOUSE=/path for a fully offline install.
if [ -n "${COBBLE_WHEELHOUSE:-}" ]; then
  "$new_venv/bin/python" -m pip install --quiet --only-binary=:all: --no-index \
    --find-links "$COBBLE_WHEELHOUSE" "$wheel"
else
  "$new_venv/bin/python" -m pip install --quiet --only-binary=:all: "$wheel"
fi
new_version="$(basename "$wheel" | sed -E 's/^cobble-([^-]+)-.*/\1/')"

# --- directory layout (design.md D5) --------------------
log "creating $BEDROCK_ROOT, $STATE_DIR, $BACKUP_DIR"
mkdir -p "$BEDROCK_ROOT/versions" "$STATE_DIR" "$BACKUP_DIR"
chown -R "$SERVICE_USER:$SERVICE_USER" "$BEDROCK_ROOT" "$STATE_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$BACKUP_DIR" || warn "could not chown $BACKUP_DIR (bind mount?); ensure cobble can write to it"

# --- upgrade helper (cobble-self-update, design.md D2/D3) ------------
# Root-owned and outside $PREFIX (which the service user owns): root must never
# run a file the cobble user could edit.
log "installing the upgrade helper"
install -d -m 0755 -o root -g root "$HELPER_DIR" "$HELPER_STATUS_DIR"
install -m 0755 -o root -g root "$src/deploy/cobble-upgrade" "$HELPER_DIR/cobble-upgrade"
sed -i "s|^REPO = .*|REPO = \"${REPO}\"|" "$HELPER_DIR/cobble-upgrade"
install -d -m 0755 -o "$SERVICE_USER" -g "$SERVICE_USER" "$STATE_DIR/upgrade"
install -m 0644 "$src/deploy/cobble-upgrade.path" /etc/systemd/system/cobble-upgrade.path
install -m 0644 "$src/deploy/cobble-upgrade.service" /etc/systemd/system/cobble-upgrade.service

# --- systemd unit + swap --------------------------------------------
# Stop before swapping: a running cobble lazily imports modules from its venv
# path, and must never load new code into an old process. Stopping cleanly
# shuts the Bedrock server down; cobble brings it back on start if it was
# running.
unit=/etc/systemd/system/cobble.service
had_previous=0
[ -d "$PREFIX/venv" ] && had_previous=1

log "stopping cobble"
systemctl stop cobble.service 2>/dev/null || true
if [ "$had_previous" -eq 1 ]; then
  rm -rf "$PREFIX/venv.old"
  mv "$PREFIX/venv" "$PREFIX/venv.old"
  [ -f "$unit" ] && cp -a "$unit" "$unit.old"
fi
mv "$new_venv" "$PREFIX/venv"
# Re-point the venv's scripts (shebangs, activate) at its final path.
{ grep -rlI -- "$new_venv" "$PREFIX/venv/bin" 2>/dev/null || true; } \
  | xargs -r sed -i "s|$new_venv|$PREFIX/venv|g"

log "installing cobble.service"
install -m 0644 "$src/deploy/cobble.service" "$unit"
systemctl daemon-reload
systemctl enable cobble.service
systemctl enable --now cobble-upgrade.path
systemctl start cobble.service
restarts_at_start="$(systemctl show -p NRestarts --value cobble.service)"

# The new cobble must answer /health with the version just installed.
cobble_port() {
  local p
  p="$(sed -n 's/^COBBLE_PORT=//p' /etc/cobble/cobble.env 2>/dev/null | tail -n1 | tr -d "\"' ")"
  echo "${p:-80}"
}
wait_healthy() {
  local url i state
  url="http://127.0.0.1:$(cobble_port)/health"
  for i in $(seq 1 60); do
    if curl -fsS --max-time 2 "$url" 2>/dev/null | grep -q "\"version\":\"${new_version}\""; then
      return 0
    fi
    state="$(systemctl show -p ActiveState --value cobble.service)"
    [ "$state" = "failed" ] && return 1
    sleep 1
  done
  # /health was unreachable on the port we guessed (it can also be set in
  # cobble.toml): accept a service systemd reports as running that it has not
  # had to auto-restart since we started it (a crash loop never qualifies).
  [ "$(systemctl show -p SubState --value cobble.service)" = "running" ] || return 1
  [ "$(systemctl show -p NRestarts --value cobble.service)" = "$restarts_at_start" ] || return 1
  warn "could not reach $url; cobble.service is running, assuming it is healthy"
  return 0
}

log "waiting for cobble ${new_version} to answer"
if wait_healthy; then
  rm -rf "$PREFIX/venv.old" "$unit.old"
elif [ "$had_previous" -eq 1 ]; then
  warn "cobble ${new_version} did not start; restoring the previous version"
  systemctl stop cobble.service 2>/dev/null || true
  rm -rf "$PREFIX/venv.failed"
  mv "$PREFIX/venv" "$PREFIX/venv.failed"
  mv "$PREFIX/venv.old" "$PREFIX/venv"
  [ -f "$unit.old" ] && mv "$unit.old" "$unit"
  systemctl daemon-reload
  systemctl start cobble.service
  rm -rf "$PREFIX/venv.failed"
  die "upgrade to cobble ${new_version} failed; the previous version is running again (journalctl -u cobble)"
else
  die "cobble ${new_version} did not start (journalctl -u cobble)"
fi

log "done. cobble ${new_version} is running; on first run it will download the current Bedrock server."
log "open http://$(hostname -I | awk '{print $1}')/ on the LAN"
