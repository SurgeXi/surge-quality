"""Unit tests for the dashboard helpers.

These exercise the math + template rendering without a live Postgres,
so they run on any developer machine. The integration test
(test_dashboard_route.py) hits the actual endpoint against a real
surge_brain DB and is gated on DATABASE_URL reachability.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from surge_quality.api.dashboard import (
    _combined_score,
    _model_family,
    _telemetry_contribution,
)


# --- _model_family ---------------------------------------------------------


@pytest.mark.parametrize(
    "model,family",
    [
        ("claude-opus-4-7", "claude"),
        ("anthropic/claude-3.5", "claude"),
        ("hermes3:8b", "surge"),
        ("qwen2.5:14b", "surge"),
        ("llama3.1:8b", "surge"),
        ("surge-fast", "surge"),
        ("ollama:phi3", "surge"),
        ("gpt-4o", "other"),
        ("", "other"),
    ],
)
def test_model_family_buckets(model: str, family: str) -> None:
    assert _model_family(model) == family


# --- _telemetry_contribution -----------------------------------------------


def test_telemetry_contribution_no_signals_returns_neutral() -> None:
    """No signals → 0.5, so a fresh response isn't dragged down."""
    assert _telemetry_contribution([]) == 0.5


def test_telemetry_contribution_thumbs_up_pushes_toward_one() -> None:
    val = _telemetry_contribution([("thumbs_up", 1.0)])
    assert val == pytest.approx(1.0)


def test_telemetry_contribution_thumbs_down_plus_dropoff_pushes_toward_zero() -> None:
    val = _telemetry_contribution([("thumbs_down", 1.0), ("dropoff", 1.0)])
    # avg of (-1, -0.5) = -0.75 → clamped to -0.75 → mapped (0.125)
    assert val == pytest.approx(0.125)


def test_telemetry_contribution_reply_time_fast() -> None:
    """Fast reply (<= 30s) is a positive signal."""
    val = _telemetry_contribution([("reply_time_seconds", 12.0)])
    # avg = +0.3 → mapped to (0.3 + 1)/2 = 0.65
    assert val == pytest.approx(0.65)


def test_telemetry_contribution_reply_time_slow() -> None:
    """Slow reply (>90s) is a negative signal."""
    val = _telemetry_contribution([("reply_time_seconds", 240.0)])
    assert val == pytest.approx(0.35)


def test_telemetry_contribution_ignores_unknown_signal() -> None:
    """Unknown signals are skipped, not crash."""
    val = _telemetry_contribution([("unknown_thing", 1.0), ("thumbs_up", 1.0)])
    assert val == pytest.approx(1.0)


# --- _combined_score -------------------------------------------------------


def test_combined_score_uses_70_30_weighting() -> None:
    """rubric=8.0/10 (0.8), telem=0.5 → 0.7*0.8 + 0.3*0.5 = 0.71."""
    assert _combined_score(8.0, 0.5) == pytest.approx(0.71)


def test_combined_score_zero_rubric_zero_telem_is_zero() -> None:
    assert _combined_score(0.0, 0.0) == 0.0


def test_combined_score_perfect_is_one() -> None:
    assert _combined_score(10.0, 1.0) == pytest.approx(1.0)


def test_combined_score_handles_none_rubric() -> None:
    """A None rubric (no score yet) shouldn't crash; treated as 0."""
    assert _combined_score(None, 0.5) == pytest.approx(0.15)


# --- Template render -------------------------------------------------------


def _empty_shadow_corpus() -> dict:
    """Empty Phase B payload used to satisfy the dashboard's template
    inputs in tests that focus on the original (non-shadow) panels.
    Kept here (not at module top) so it's adjacent to the tests that
    use it."""
    return {
        "window_days": 14,
        "total_shadow_responses": 0,
        "acceptance_corpus_size": 0,
        "negative_corpus_size": 0,
        "claude_reviewer_queue_depth": 0,
        "acceptance_growth_last_7d": 0,
        "avg_composite_overall": 0.0,
    }


def test_dashboard_template_renders_with_empty_payload() -> None:
    """The template must not crash on empty days/topics/lows."""
    templates_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "surge_quality"
        / "templates"
    )
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("dashboard.html.j2")
    html = template.render(
        generated_at="2026-06-04T06:00:00+00:00",
        today="2026-06-04",
        window_days=14,
        claude_review_threshold=5.0,
        daily=[],
        topics=[],
        low_scores=[],
        shadow_trend=[],
        shadow_topics=[],
        shadow_corpus=_empty_shadow_corpus(),
    )
    # Sanity: the three empty-state strings render.
    assert "No scored responses in the window." in html
    assert "No routing decisions in the window." in html
    assert "Surge is on the rails" in html
    # Phase B section renders an empty-state message rather than crashing.
    assert "Phase B" in html
    assert "Phase B has not yet been wired in" in html


def test_dashboard_template_renders_with_populated_payload() -> None:
    templates_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "surge_quality"
        / "templates"
    )
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("dashboard.html.j2")
    html = template.render(
        generated_at="2026-06-04T06:00:00+00:00",
        today="2026-06-04",
        window_days=14,
        claude_review_threshold=5.0,
        daily=[
            {
                "day": "2026-06-04",
                "surge_share_pct": 80.0,
                "claude_share_pct": 20.0,
                "avg_combined": 0.74,
                "n_responses": 10,
            },
            {
                "day": "2026-06-03",
                "surge_share_pct": 60.0,
                "claude_share_pct": 40.0,
                "avg_combined": 0.62,
                "n_responses": 6,
            },
        ],
        topics=[
            {"topic": "tax-deadline", "n": 12, "avg_composite": 7.5},
            {"topic": "(unclassified)", "n": 5, "avg_composite": 4.2},
        ],
        low_scores=[
            {
                "response_id": 42,
                "conversation_id": "abc-123",
                "composite": 3.8,
                "combined": 0.41,
                "model_used": "hermes3:8b",
                "generated_at": "2026-06-04T05:30:00+00:00",
                "snippet": "Here is a confidently wrong answer.",
            }
        ],
        shadow_trend=[],
        shadow_topics=[],
        shadow_corpus=_empty_shadow_corpus(),
    )
    # SVG chart present.
    assert '<svg class="chart"' in html
    # Topic table shows up.
    assert "tax-deadline" in html
    # Low-score replay row + the score api link.
    assert ">42<" in html
    assert "/v1/quality/score-response/42" in html
    # Low-score "teach" pill for the <5 row.
    assert "teach" in html


def test_dashboard_template_renders_phase_b_panels() -> None:
    """Phase B section must render all three panels (stat tiles + trend
    line + topic table) when populated. Locks the template against an
    accidental ``shadow_corpus`` / ``shadow_trend`` / ``shadow_topics``
    rename — the dashboard.py builder + template names MUST stay in
    lock-step.
    """
    templates_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "surge_quality"
        / "templates"
    )
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("dashboard.html.j2")
    html = template.render(
        generated_at="2026-06-04T06:00:00+00:00",
        today="2026-06-04",
        window_days=14,
        claude_review_threshold=5.0,
        daily=[],
        topics=[],
        low_scores=[],
        shadow_trend=[
            {"day": "2026-06-03", "n_responses": 5, "avg_composite": 6.2},
            {"day": "2026-06-04", "n_responses": 8, "avg_composite": 7.1},
        ],
        shadow_topics=[
            {"topic": "tax-deadline", "n": 6, "avg_composite": 7.4},
            {"topic": "(unclassified)", "n": 4, "avg_composite": 3.9},
        ],
        shadow_corpus={
            "window_days": 14,
            "total_shadow_responses": 13,
            "acceptance_corpus_size": 10,
            "negative_corpus_size": 3,
            "claude_reviewer_queue_depth": 1,
            "acceptance_growth_last_7d": 8,
            "avg_composite_overall": 6.7,
        },
    )
    # Phase B stat tiles
    assert "Total shadow turns" in html
    assert "Acceptance corpus" in html
    assert "Negative corpus" in html
    assert "Reviewer queue depth" in html
    # Numbers render (acceptance 10 visible, growth +8 visible).
    assert ">10<" in html or "10\n" in html  # tile-value can be on its own line
    assert "+8 last 7d" in html
    # Trend SVG chart present
    assert 'aria-label="phase B surge quality trend"' in html
    # Topic table renders with the pill class — accept (pill surge) for
    # >= threshold, warn for < threshold.
    assert "pill surge" in html  # tax-deadline is above 5.0
    assert "pill warn" in html   # (unclassified) is below 5.0
