"""surge-quality FastAPI app factory.

Endpoints land here incrementally:
- PR-2 (this commit): /healthz, /readyz
- PR-3: /v1/quality/score-response (POST + GET)
- PR-4: /v1/quality/telemetry
- PR-5: triggered by PR-3 worker, no new endpoint
- PR-6: /v1/quality/route-decision
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from sqlalchemy import text

from surge_quality.db import SessionLocal
from surge_quality.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 — FastAPI signature
    """Startup/shutdown hook. Nothing heavy on boot — DB readiness is
    checked lazily via /readyz so the process starts even if PG is
    momentarily unavailable."""
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="surge-quality",
        version="0.1.0",
        description=(
            "SurgeXi Quality recommender. Read-only service that scores Surge "
            "responses, captures customer telemetry, asks Claude to teach when "
            "Surge underperforms, and emits routing-decision advice. Does not "
            "execute side-effects — those route through SOL."
        ),
        lifespan=lifespan,
    )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict[str, str]:
        """Process liveness. Always 200 if the event loop is alive."""
        return {"status": "ok", "service": settings.service_name}

    @app.get("/readyz", tags=["ops"])
    def readyz() -> dict[str, Any]:
        """Readiness: Postgres reachable + correct schema exists."""
        checks: dict[str, Any] = {}
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1")).scalar_one()
                schema_exists = db.execute(
                    text(
                        "SELECT 1 FROM information_schema.schemata "
                        "WHERE schema_name = :s"
                    ),
                    {"s": settings.db_schema},
                ).first()
            checks["db"] = "ok"
            checks["schema"] = "ok" if schema_exists else "missing"
        except Exception as exc:  # noqa: BLE001 — health surface
            checks["db"] = f"error: {exc.__class__.__name__}"
            checks["schema"] = "unknown"

        ok = checks.get("db") == "ok" and checks.get("schema") == "ok"
        return {"status": "ready" if ok else "not-ready", "checks": checks}

    return app


app = create_app()
