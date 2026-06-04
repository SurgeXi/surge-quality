"""Operator dashboard — server-side Jinja2 render.

This is the Jinja2 fallback dashboard called out in the PR-7 plan. It
exists in addition to (not instead of) the Grafana dashboards under
``dashboards/`` so the service ships a working operator view even on
nodes that don't run Grafana — and so the surge-quality service itself
can be smoke-tested visually without crossing a process boundary.

Endpoints
---------
``GET /v1/quality/dashboard``
    HTML page. Three sections, all driven by the same SQL aggregates the
    Grafana panels use:
        1. Per-day Surge share (% of scored responses where
           ``responses.model_used`` matches the ``surge_*`` family, vs
           Claude). Last 14 days.
        2. Per-day average combined quality score (rubric composite
           normalized 0-1 + telemetry contribution). Last 14 days.
        3. Topic-area breakdown — bucket by the routing-decision
           ``factors_json -> topic`` when present, else "(unclassified)".
        4. Low-score replay — last 25 responses where composite <
           ``claude_review_threshold``; each row links to its underlying
           JSON via the existing scoring API.

``GET /v1/quality/dashboard/metrics``
    JSON variant of the same payload. The HTML page eats this; external
    callers (curl + jq) can hit it directly. Useful in PR-10 smoke too.

Design notes
------------
* Auth: the dashboard is read-only and contains no PII the rest of the
  service doesn't already expose, BUT it is still gated by the same
  ``X-Surge-Quality-Token`` header as everything else in /v1/quality —
  uniform auth surface, no special cases.  The metrics-JSON endpoint is
  gated the same way.  When ``settings.service_token`` is empty (dev
  default) auth is disabled for parity with the other endpoints.
* Charts: no JS chart library — the HTML uses inline SVG produced
  server-side so the dashboard renders in any browser with no network
  fetches after the initial GET. This is on purpose: keeps the
  attack surface small (no CDN dependency), makes the headless-smoke
  in PR-10 trivial (one request, no JS execution required), and keeps
  the service self-contained.
* "Combined quality" matches the formula documented in docs/PLAN.md §3:
  ``0.7 * (rubric_composite / 10) + 0.3 * telemetry_score``. Telemetry
  score is computed from the per-response signal mix using the same
  weights the routing engine uses.

Read-only — no writes, no side-effects. Safe to expose.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import text
from sqlalchemy.orm import Session

from surge_quality.api.auth import require_service_token
from surge_quality.db import get_db
from surge_quality.settings import get_settings

router = APIRouter(prefix="/v1/quality", tags=["dashboard"])

# --- Telemetry weight table -------------------------------------------------
# Mirrored from docs/PLAN.md §3. Keep in sync with the routing engine.
_TELEMETRY_WEIGHTS: dict[str, float] = {
    "thumbs_up": +1.0,
    "thumbs_down": -1.0,
    "dropoff": -0.5,
    "reask": -0.5,
    "human_escalation_request": -1.0,
    # reply_time_seconds handled separately: shorter = better. We map
    # 0-30s → +0.3, 30-90s → 0, >90s → -0.3 in _telemetry_contribution.
}


# --- Jinja2 environment -----------------------------------------------------
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    enable_async=False,
)


@dataclass(slots=True)
class DayBucket:
    """One row in the per-day chart payload."""

    day: str
    surge_share_pct: float
    claude_share_pct: float
    avg_combined: float
    n_responses: int


@dataclass(slots=True)
class TopicBucket:
    topic: str
    n: int
    avg_composite: float


@dataclass(slots=True)
class LowScoreRow:
    response_id: int
    conversation_id: str
    composite: float
    combined: float
    model_used: str
    generated_at: datetime
    snippet: str


# --- SQL helpers ------------------------------------------------------------


def _model_family(model: str) -> str:
    """Bucket the heterogeneous ``model_used`` values into surge vs claude
    vs other. We treat anything containing 'claude' as claude, anything
    starting with 'hermes', 'qwen', 'llama', 'surge' as surge, everything
    else as 'other'. Matches the labels used in the Grafana panels."""
    m = (model or "").lower()
    if "claude" in m:
        return "claude"
    if (
        m.startswith(("hermes", "qwen", "llama", "surge"))
        or "ollama" in m
    ):
        return "surge"
    return "other"


def _telemetry_contribution(signals: list[tuple[str, float | None]]) -> float:
    """Compute the 0-1 telemetry component for a single response.

    Each signal contributes per the weight table; numeric reply_time gets a
    bucketed contribution. Final value is clamped to [-1, 1] then mapped to
    [0, 1] so it composes with the rubric composite/10.
    """
    raw = 0.0
    n = 0
    for sig_type, value in signals:
        if sig_type == "reply_time_seconds":
            if value is None:
                continue
            if value <= 30:
                raw += 0.3
            elif value <= 90:
                raw += 0.0
            else:
                raw -= 0.3
            n += 1
        else:
            w = _TELEMETRY_WEIGHTS.get(sig_type)
            if w is None:
                continue
            raw += w
            n += 1
    if n == 0:
        # No telemetry yet — neutral 0.5 so combined isn't dragged down.
        return 0.5
    # Clamp + remap.
    clamped = max(-1.0, min(1.0, raw / max(1, n)))
    return (clamped + 1.0) / 2.0


def _combined_score(rubric_composite: float | None, telemetry_unit: float) -> float:
    """0.7 * rubric + 0.3 * telemetry, all on the same 0-1 scale."""
    rubric_unit = (rubric_composite or 0.0) / 10.0
    return round(0.7 * rubric_unit + 0.3 * telemetry_unit, 4)


# --- Query aggregations -----------------------------------------------------


def _query_daily(db: Session, schema: str, days: int = 14) -> list[DayBucket]:
    """Per-day Surge share + average combined quality, last ``days`` days.

    Uses a single Postgres CTE so the result set is small (one row per
    day). Joining telemetry as an aggregate keeps the row count bounded
    even on busy days.
    """
    sql = text(
        f"""
        WITH days AS (
            SELECT (date_trunc('day', now() - (n || ' days')::interval))::date AS day
            FROM generate_series(0, :days - 1) AS n
        ),
        scored AS (
            SELECT
                date_trunc('day', r.generated_at)::date AS day,
                r.id,
                r.model_used,
                rs.composite,
                (
                    SELECT COALESCE(
                        AVG(
                            CASE
                                WHEN ts.signal_type = 'thumbs_up' THEN 1.0
                                WHEN ts.signal_type = 'thumbs_down' THEN -1.0
                                WHEN ts.signal_type = 'dropoff' THEN -0.5
                                WHEN ts.signal_type = 'reask' THEN -0.5
                                WHEN ts.signal_type = 'human_escalation_request' THEN -1.0
                                WHEN ts.signal_type = 'reply_time_seconds' AND ts.value <= 30 THEN 0.3
                                WHEN ts.signal_type = 'reply_time_seconds' AND ts.value <= 90 THEN 0.0
                                WHEN ts.signal_type = 'reply_time_seconds' THEN -0.3
                                ELSE NULL
                            END
                        ),
                        NULL
                    )
                    FROM {schema}.telemetry_signals ts WHERE ts.response_id = r.id
                ) AS telem_raw
            FROM {schema}.responses r
            JOIN {schema}.rubric_scores rs ON rs.response_id = r.id
            WHERE r.generated_at >= now() - (:days || ' days')::interval
        )
        SELECT
            d.day,
            COALESCE(SUM(CASE WHEN s.model_used ILIKE '%claude%' THEN 0 ELSE 1 END), 0) AS surge_n,
            COALESCE(SUM(CASE WHEN s.model_used ILIKE '%claude%' THEN 1 ELSE 0 END), 0) AS claude_n,
            COUNT(s.id) AS n,
            AVG(s.composite) AS avg_composite,
            AVG(s.telem_raw) AS avg_telem_raw
        FROM days d
        LEFT JOIN scored s ON s.day = d.day
        GROUP BY d.day
        ORDER BY d.day
        """
    )
    rows = db.execute(sql, {"days": days}).all()
    out: list[DayBucket] = []
    for row in rows:
        n = int(row.n or 0)
        surge_n = int(row.surge_n or 0)
        claude_n = int(row.claude_n or 0)
        # If we have no rows for the day, share defaults to 0/0.
        if n == 0:
            surge_pct = claude_pct = 0.0
            combined = 0.0
        else:
            surge_pct = round(100.0 * surge_n / n, 2)
            claude_pct = round(100.0 * claude_n / n, 2)
            avg_telem_raw = row.avg_telem_raw
            if avg_telem_raw is None:
                telem_unit = 0.5
            else:
                clamped = max(-1.0, min(1.0, float(avg_telem_raw)))
                telem_unit = (clamped + 1.0) / 2.0
            combined = _combined_score(float(row.avg_composite or 0.0), telem_unit)
        out.append(
            DayBucket(
                day=row.day.isoformat(),
                surge_share_pct=surge_pct,
                claude_share_pct=claude_pct,
                avg_combined=combined,
                n_responses=n,
            )
        )
    return out


def _query_topics(db: Session, schema: str, days: int = 14) -> list[TopicBucket]:
    """Topic breakdown — extract ``factors_json->>'topic'`` when the
    routing engine logged one, else ``(unclassified)``.

    Routing decisions don't directly join to a response, so we group by
    topic only, not by response. Counts are turns routed."""
    sql = text(
        f"""
        SELECT
            COALESCE(rd.factors_json->>'topic', '(unclassified)') AS topic,
            COUNT(*) AS n,
            AVG(rs.composite) AS avg_composite
        FROM {schema}.routing_decisions rd
        LEFT JOIN {schema}.responses r ON r.conversation_id = rd.conversation_id
        LEFT JOIN {schema}.rubric_scores rs ON rs.response_id = r.id
        WHERE rd.decided_at >= now() - (:days || ' days')::interval
        GROUP BY topic
        ORDER BY n DESC
        LIMIT 12
        """
    )
    rows = db.execute(sql, {"days": days}).all()
    return [
        TopicBucket(
            topic=row.topic,
            n=int(row.n),
            avg_composite=round(float(row.avg_composite or 0.0), 2),
        )
        for row in rows
    ]


def _query_low_scores(
    db: Session, schema: str, threshold: float, limit: int = 25
) -> list[LowScoreRow]:
    """Most recent low-scoring responses for the replay panel."""
    sql = text(
        f"""
        SELECT
            r.id AS response_id,
            r.conversation_id,
            r.model_used,
            r.generated_at,
            LEFT(r.response_text, 240) AS snippet,
            rs.composite
        FROM {schema}.responses r
        JOIN {schema}.rubric_scores rs ON rs.response_id = r.id
        WHERE rs.composite < :threshold
        ORDER BY r.generated_at DESC
        LIMIT :limit
        """
    )
    rows = db.execute(sql, {"threshold": threshold, "limit": limit}).all()
    out: list[LowScoreRow] = []
    for row in rows:
        # Per-response telemetry for the combined-score column.
        sig_rows = db.execute(
            text(
                f"""
                SELECT signal_type, value
                FROM {schema}.telemetry_signals
                WHERE response_id = :rid
                """
            ),
            {"rid": row.response_id},
        ).all()
        telem = _telemetry_contribution([(r.signal_type, r.value) for r in sig_rows])
        out.append(
            LowScoreRow(
                response_id=int(row.response_id),
                conversation_id=str(row.conversation_id),
                composite=float(row.composite),
                combined=_combined_score(float(row.composite), telem),
                model_used=str(row.model_used),
                generated_at=row.generated_at,
                snippet=str(row.snippet or "").strip(),
            )
        )
    return out


# --- Metrics builder shared by HTML + JSON ---------------------------------


def _build_metrics(db: Session) -> dict[str, Any]:
    settings = get_settings()
    schema = settings.db_schema
    daily = _query_daily(db, schema)
    topics = _query_topics(db, schema)
    low = _query_low_scores(db, schema, threshold=settings.claude_review_threshold)
    today: date = datetime.now(timezone.utc).date()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "window_days": 14,
        "claude_review_threshold": settings.claude_review_threshold,
        "daily": [d.__dict__ for d in daily],
        "topics": [t.__dict__ for t in topics],
        "low_scores": [
            {
                **row.__dict__,
                "generated_at": row.generated_at.isoformat(),
            }
            for row in low
        ],
    }


# --- Endpoints --------------------------------------------------------------


@router.get(
    "/dashboard/metrics",
    dependencies=[Depends(require_service_token)],
    response_class=JSONResponse,
)
def dashboard_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """JSON variant. Same payload the HTML view consumes."""
    return _build_metrics(db)


@router.get(
    "/dashboard",
    dependencies=[Depends(require_service_token)],
    response_class=HTMLResponse,
)
def dashboard_html(db: Session = Depends(get_db)) -> HTMLResponse:
    """HTML view — Jinja2-rendered, inline SVG charts, no JS."""
    metrics = _build_metrics(db)
    template = _env.get_template("dashboard.html.j2")
    body = template.render(**metrics)
    return HTMLResponse(body, status_code=200)
