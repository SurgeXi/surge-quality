# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Phase-A service-token auth.

The Surge Orchestration Layer (SOL) Phase 3.4 will issue JWTs that this
service can verify. Until then surge-quality accepts a static token from
``settings.service_token`` carried in the ``X-Surge-Quality-Token``
header. Empty configured token => auth disabled (dev only).
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from surge_quality.settings import get_settings


def require_service_token(
    x_surge_quality_token: str | None = Header(default=None),
) -> None:
    """FastAPI dependency. 401 if header missing/mismatched (when configured)."""
    expected = get_settings().service_token
    if not expected:
        # Auth disabled — dev convenience. Production deployment MUST set
        # the token in /etc/surge-quality/service-tokens.env.
        return
    if not x_surge_quality_token or x_surge_quality_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Surge-Quality-Token",
        )
