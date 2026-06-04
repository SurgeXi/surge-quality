#!/usr/bin/env bash
# smoke-dashboard.sh — headless-browser visual smoke for the dashboard.
#
# Hits the dashboard route with a real browser, dumps a PNG to disk, and
# asserts the file is non-trivial. Designed to run on any SurgeXi node
# that has either Firefox or a chromium binary available.
#
# Why this exists: PR-10 of the surge-quality 4-PR ship. The Jinja2
# dashboard route renders inline SVG with zero JavaScript on purpose,
# so a single GET + render is sufficient to prove "the operator view is
# actually usable" — no client-side data fetch to wait on.
#
# Usage:
#   ./deploy/smoke-dashboard.sh [URL] [OUTPUT_PNG]
# Defaults:
#   URL          http://127.0.0.1:9311/v1/quality/dashboard
#   OUTPUT_PNG   /tmp/surge-quality-dashboard-smoke.png
#
# Exit codes:
#   0  PNG captured and is > MIN_SIZE_BYTES
#   1  no headless browser available — gap documented in stderr
#   2  HTTP fetch of the dashboard URL failed
#   3  browser ran but produced no PNG or PNG too small
set -euo pipefail

URL="${1:-http://127.0.0.1:9311/v1/quality/dashboard}"
OUT="${2:-/tmp/surge-quality-dashboard-smoke.png}"
WINDOW_SIZE="${WINDOW_SIZE:-1400,2400}"
MIN_SIZE_BYTES="${MIN_SIZE_BYTES:-30000}"   # 30 KB — empty page is much smaller

echo "[smoke] target: $URL"
echo "[smoke] output: $OUT"

# 1. Pre-flight: dashboard must respond with HTTP 200 before we burn
#    seconds on a browser launch. If the service is down, fail fast.
if ! curl -fsS -m 10 -o /dev/null -w "%{http_code}\n" "$URL" | grep -q '^200$'; then
  status=$(curl -s -m 10 -o /dev/null -w "%{http_code}" "$URL" || echo "000")
  echo "[smoke] FAIL: $URL returned HTTP $status" >&2
  exit 2
fi
echo "[smoke] HTTP 200 OK"

# 2. Find a headless browser. Order of preference: chromium (fastest
#    headless), then Firefox (already available across the fleet).
rm -f "$OUT"
browser=""
for cand in chromium chromium-browser google-chrome google-chrome-stable; do
  if command -v "$cand" >/dev/null 2>&1; then
    browser="$cand"
    break
  fi
done

if [[ -n "$browser" ]]; then
  echo "[smoke] using $browser headless"
  "$browser" --headless --disable-gpu --no-sandbox \
    --window-size="${WINDOW_SIZE/,/x}" \
    --screenshot="$OUT" \
    "$URL"
elif command -v firefox >/dev/null 2>&1; then
  echo "[smoke] using firefox headless"
  # Firefox >=100 only writes -screenshot output into $HOME if no path is
  # given, and won't accept an absolute path without --screenshot=PATH
  # (the equals form). We use --screenshot=PATH so the file lands
  # exactly where we tell it, no matter the cwd.
  rm -f "$OUT"
  MOZ_HEADLESS=1 firefox \
      "--screenshot=${OUT}" \
      --window-size="$WINDOW_SIZE" \
      "$URL" \
      >/tmp/smoke-firefox.log 2>&1 || true
  # Older Firefox builds ignored the = form and dropped the PNG in $HOME
  # as "screenshot.png". Fall back to that location.
  if [[ ! -s "$OUT" && -s "$HOME/screenshot.png" ]]; then
    mv "$HOME/screenshot.png" "$OUT"
  fi
else
  cat >&2 <<'EOF'
[smoke] FAIL: no headless browser found on PATH.
[smoke] Install one of: chromium, google-chrome, or firefox.
[smoke] GAP documented per PR-10 task spec — capture cannot proceed
[smoke] until a headless browser is provisioned on this node.
EOF
  exit 1
fi

# 3. Validate.
if [[ ! -s "$OUT" ]]; then
  echo "[smoke] FAIL: browser produced no output at $OUT" >&2
  exit 3
fi
size=$(stat -c '%s' "$OUT" 2>/dev/null || stat -f '%z' "$OUT")
if (( size < MIN_SIZE_BYTES )); then
  echo "[smoke] FAIL: PNG too small ($size bytes < $MIN_SIZE_BYTES). Likely a blank page." >&2
  exit 3
fi

echo "[smoke] OK: $OUT ($size bytes)"
