"""Visual-smoke entrypoint test.

This test is the PR-10 deliverable: it asserts the smoke shell script
is on disk, executable, and structurally sane (preflights with curl,
falls back across browsers, validates PNG size). The actual headless
browser run is an integration step (see deploy/smoke-dashboard.sh and
deploy/screenshots/) that requires a node with Firefox or Chromium
available — this test pins the contract for that script.

Gated on the presence of `firefox` or a chromium binary so the test
self-skips on developer laptops without one.
"""

from __future__ import annotations

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SMOKE = REPO_ROOT / "deploy" / "smoke-dashboard.sh"


def test_smoke_script_exists() -> None:
    assert SMOKE.exists(), f"missing smoke script at {SMOKE}"


def test_smoke_script_is_executable() -> None:
    mode = SMOKE.stat().st_mode
    assert mode & stat.S_IXUSR, "smoke-dashboard.sh must be executable"


def test_smoke_script_has_failure_path_for_missing_browser() -> None:
    """If no headless browser is available, the script must exit 1
    with a clear "GAP documented" message — that's the explicit
    requirement from the PR-10 task spec."""
    body = SMOKE.read_text()
    assert "no headless browser found" in body
    assert "GAP documented" in body
    assert "exit 1" in body


def test_smoke_script_validates_png_size() -> None:
    """A successful run must assert the PNG is non-trivial — a blank
    page from a broken dashboard would be a much smaller file."""
    body = SMOKE.read_text()
    assert "MIN_SIZE_BYTES" in body


def test_smoke_script_preflights_with_curl() -> None:
    """The script must fail fast on HTTP failure before launching the
    browser. Otherwise a down service produces a confusing
    "PNG too small" error instead of an HTTP error."""
    body = SMOKE.read_text()
    assert "curl" in body
    assert "exit 2" in body  # HTTP failure path


@pytest.mark.skipif(
    not (shutil.which("firefox") or shutil.which("chromium") or shutil.which("google-chrome")),
    reason="no headless browser on PATH — see PR-10 gap docs in deploy/screenshots/README.md",
)
def test_smoke_script_fails_cleanly_against_bad_url(tmp_path: Path) -> None:
    """Run the script against a URL that doesn't exist. It must exit 2
    (curl preflight failure) BEFORE trying to launch the browser."""
    bad_url = "http://127.0.0.1:1/v1/quality/dashboard"
    out_png = tmp_path / "out.png"
    r = subprocess.run(
        [str(SMOKE), bad_url, str(out_png)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}: {r.stderr}"
    assert not out_png.exists()
