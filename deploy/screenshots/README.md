<!-- Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved. -->
# Dashboard smoke screenshots

This directory holds PNGs produced by `deploy/smoke-dashboard.sh` as
visual evidence for PR-10 (visual smoke) and any future visual
regression check.

| file | captured | route | source |
|---|---|---|---|
| `dashboard-2026-06-04.png` | 2026-06-04 | `GET /v1/quality/dashboard` | surgecore staging, seeded fixtures |

To recapture (against a running surge-quality):

```bash
./deploy/smoke-dashboard.sh \
    http://127.0.0.1:9311/v1/quality/dashboard \
    deploy/screenshots/dashboard-$(date -u +%Y-%m-%d).png
```

The smoke script preflights the route with curl, then drives Firefox
headless (or Chromium if available) to produce the PNG. Exit codes
documented in the script header.
