#!/usr/bin/env bash
# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
# install-systemd.sh — install the PR-9 hardened systemd unit.
#
# Idempotent. Run as root on a host where surge-quality is already
# deployed at /opt/surge-quality. Capture the *prior* unit content
# first if you want a roll-back you can audit; this script overwrites
# /etc/systemd/system/surge-quality.service with the hardened version.
#
# What it does:
#   1. Creates /opt/surge-quality/var (mode 0750, owner surge-quality)
#      and /var/log/surge-quality (mode 0750, owner surge-quality) —
#      the only two writable paths in the hardened unit.
#   2. Copies deploy/surge-quality.service to /etc/systemd/system/.
#   3. Runs systemctl daemon-reload + systemctl restart.
#   4. Probes systemd-analyze security and prints the score.
#
# Rollback (run as root):
#   # 1. Restore the prior unit if you saved it (always do this BEFORE
#   #    overwriting in production):
#   sudo cp /etc/systemd/system/surge-quality.service.bak \
#       /etc/systemd/system/surge-quality.service
#   sudo systemctl daemon-reload
#   sudo systemctl restart surge-quality
#   # 2. If no .bak: just remove the hardening lines (everything in the
#   #    "Hardening" block) and leave the rest. The pre-PR-9 unit
#   #    had only NoNewPrivileges=true + ProtectSystem=strict +
#   #    ProtectHome=true + PrivateTmp=true + ReadWritePaths=/opt/surge-quality.
set -euo pipefail

UNIT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/surge-quality.service"
UNIT_DEST="/etc/systemd/system/surge-quality.service"
SVC_USER="surge-quality"
SVC_GROUP="surge-quality"

if [[ $EUID -ne 0 ]]; then
  echo "[install-systemd.sh] must be run as root (sudo)." >&2
  exit 2
fi

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "[install-systemd.sh] ERROR: source unit not found at $UNIT_SRC" >&2
  exit 2
fi

if ! id -u "$SVC_USER" >/dev/null 2>&1; then
  echo "[install-systemd.sh] ERROR: user '$SVC_USER' does not exist." >&2
  echo "                       useradd --system $SVC_USER first." >&2
  exit 2
fi

echo "[install-systemd.sh] preparing writable paths..."
install -d -m 750 -o "$SVC_USER" -g "$SVC_GROUP" /opt/surge-quality/var
install -d -m 750 -o "$SVC_USER" -g "$SVC_GROUP" /var/log/surge-quality

# Audit-friendly: save the prior unit so the rollback path doesn't
# depend on memory.
if [[ -f "$UNIT_DEST" ]]; then
  cp -a "$UNIT_DEST" "${UNIT_DEST}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
  echo "[install-systemd.sh] backed up prior unit."
fi

install -o root -g root -m 644 "$UNIT_SRC" "$UNIT_DEST"

systemctl daemon-reload
echo "[install-systemd.sh] restarting surge-quality..."
systemctl restart surge-quality

# Wait briefly for the service to settle, then probe.
sleep 2
systemctl is-active --quiet surge-quality || {
  echo "[install-systemd.sh] FAIL: surge-quality is not active after restart." >&2
  echo "                       Check journalctl -u surge-quality for details." >&2
  exit 1
}

echo
echo "[install-systemd.sh] systemd-analyze security score:"
systemd-analyze security surge-quality --no-pager | tail -20 || true
echo
echo "[install-systemd.sh] Done. /healthz check:"
curl -fsS http://127.0.0.1:9311/healthz || true
echo
