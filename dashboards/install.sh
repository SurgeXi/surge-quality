#!/usr/bin/env bash
# install.sh — provision the surge-quality dashboard into a Grafana node.
#
# Idempotent. Run on a host that already has Grafana installed and the
# surge_brain Postgres reachable on localhost:5432 with a surge_quality
# read-only user. Re-running is safe — the script overwrites the same
# files and triggers a single reload.
#
# Inputs (env):
#   GRAFANA_PROV_DIR    default /etc/grafana/provisioning
#   GRAFANA_DASH_DIR    default /var/lib/grafana/dashboards/surge-quality
#   SURGE_QUALITY_PG_PASSWORD   REQUIRED. Read-only PG password for the
#                               surge_quality user. NEVER commit this.
#
# What it does:
#   1. Renders the datasource YAML with the PG password substituted in.
#   2. Drops the dashboard provisioning YAML.
#   3. Copies surge-quality.json into the dashboards folder.
#   4. Triggers a `systemctl reload grafana-server` (or restart if reload
#      is unsupported on this Grafana build).
#
# Rollback:
#   sudo rm /etc/grafana/provisioning/datasources/surge-quality.yaml
#   sudo rm /etc/grafana/provisioning/dashboards/surge-quality.yaml
#   sudo rm -rf /var/lib/grafana/dashboards/surge-quality
#   sudo systemctl restart grafana-server
set -euo pipefail

GRAFANA_PROV_DIR="${GRAFANA_PROV_DIR:-/etc/grafana/provisioning}"
GRAFANA_DASH_DIR="${GRAFANA_DASH_DIR:-/var/lib/grafana/dashboards/surge-quality}"

if [[ -z "${SURGE_QUALITY_PG_PASSWORD:-}" ]]; then
  echo "[install.sh] ERROR: SURGE_QUALITY_PG_PASSWORD env var is required." >&2
  echo "             Set it from /etc/surge-quality/db.env or your secrets store." >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[install.sh] Provisioning surge-quality Grafana assets..."

# 1. Datasource. Substitute the password rather than relying on Grafana's
#    env-var resolution — keeps the rendered file self-contained and easy
#    to inspect. The file is chmod 600 to the grafana user.
sudo install -d -m 755 "$GRAFANA_PROV_DIR/datasources"
sudo install -d -m 755 "$GRAFANA_PROV_DIR/dashboards"
sudo install -d -m 755 "$GRAFANA_DASH_DIR"

# A tiny render: only one variable to substitute, so envsubst is overkill.
# We use sed with a defensive replacement (no slashes allowed) to avoid
# breaking if the password has '/' in it. Use a control char as the
# delimiter that cannot legally appear in a password.
ds_template="$HERE/provisioning/datasources/surge-quality.yaml"
ds_target="$GRAFANA_PROV_DIR/datasources/surge-quality.yaml"
tmp="$(mktemp)"
# shellcheck disable=SC2016
awk -v pw="$SURGE_QUALITY_PG_PASSWORD" '
  { gsub(/\$\{SURGE_QUALITY_PG_PASSWORD\}/, pw); print }
' "$ds_template" > "$tmp"
sudo install -o root -g grafana -m 640 "$tmp" "$ds_target"
rm -f "$tmp"

# 2. Dashboard provider.
sudo install -o root -g grafana -m 644 \
  "$HERE/provisioning/dashboards/surge-quality.yaml" \
  "$GRAFANA_PROV_DIR/dashboards/surge-quality.yaml"

# 3. Dashboard JSON.
sudo install -o root -g grafana -m 644 \
  "$HERE/surge-quality.json" \
  "$GRAFANA_DASH_DIR/surge-quality.json"

# 4. Reload Grafana. systemd reload is fine on grafana-server >= 8;
#    fall back to restart if reload is not implemented.
if sudo systemctl reload grafana-server 2>/dev/null; then
  echo "[install.sh] grafana-server reloaded."
else
  echo "[install.sh] reload not supported on this build — restarting."
  sudo systemctl restart grafana-server
fi

echo "[install.sh] Done. Dashboard UID = 'surge-quality'."
echo "             URL: <grafana>/d/surge-quality/surge-quality-recommender"
