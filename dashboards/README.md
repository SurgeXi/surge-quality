# surge-quality dashboards

Two operator dashboards ship in this repo. They render the same metrics
so either one is sufficient for the daily operator view.

## 1. Grafana dashboard (preferred)

Files in this directory:

- `surge-quality.json` — the dashboard itself. 9 panels:
  - 4 stat tiles (volume, avg rubric composite, low-score share, Claude takeovers)
  - per-day Surge share (stacked %)
  - per-day average rubric composite (line)
  - per-day combined quality score (line, 0-1)
  - topic-area breakdown (horizontal bar)
  - low-score replay (table)
- `provisioning/datasources/surge-quality.yaml` — Postgres datasource
  pointing at the `surge_quality` schema on `surge_brain`. Read-only PG
  user (`surge_quality`); password is substituted at install time from
  `SURGE_QUALITY_PG_PASSWORD`.
- `provisioning/dashboards/surge-quality.yaml` — provider config that
  watches `/var/lib/grafana/dashboards/surge-quality/`.
- `install.sh` — idempotent installer. Run on the Grafana host.

Install:

```bash
export SURGE_QUALITY_PG_PASSWORD='...'   # never commit this
sudo -E bash dashboards/install.sh
```

Rollback (from install.sh header):

```bash
sudo rm /etc/grafana/provisioning/datasources/surge-quality.yaml
sudo rm /etc/grafana/provisioning/dashboards/surge-quality.yaml
sudo rm -rf /var/lib/grafana/dashboards/surge-quality
sudo systemctl restart grafana-server
```

## 2. In-service Jinja2 dashboard (fallback)

The service exposes the same operator view as a server-rendered HTML
page at `GET /v1/quality/dashboard` with a JSON twin at
`GET /v1/quality/dashboard/metrics`. Both are gated by the standard
`X-Surge-Quality-Token` header.

This route exists for two reasons:
1. Nodes that don't run Grafana still get an operator view.
2. The visual smoke test (PR-10) hits this route with a headless browser
   without needing Grafana to be installed.

The HTML is intentionally pure-server-rendered: inline SVG charts, no JS,
no CDN dependency, no follow-on fetches. That keeps the attack surface
small and the smoke test trivial.
