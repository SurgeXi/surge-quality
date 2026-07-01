"""Async httpx client for the surge-ai Hermes endpoint.

The scoring backend runs Ollama with the Hermes 3 8B model (GPU
per memory `surge_ai_upgrade_2026_06`). We call the ``/api/generate``
endpoint with ``format=json`` to coerce a structured rubric response.

Failure handling matches the SOL "ironclad over quick" mandate:
- explicit timeout
- retry once on the documented "server busy" pending-queue response
- raise on any other 5xx so the caller can decide to fail or queue
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HermesError(RuntimeError):
    """Raised when Hermes returns an unrecoverable error."""


class HermesClient:
    """Thin async wrapper over Ollama's /api/generate endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 4,
        backoff_seconds: float = 3.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    async def generate_json(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        num_predict: int = 1024,
    ) -> dict[str, Any]:
        """Call Hermes with ``format=json`` and return the parsed payload.

        Raises ``HermesError`` if Hermes is unrecoverable or the response
        is not valid JSON after exhausting retries.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }
        if system is not None:
            payload["system"] = system

        last_err: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    r = await client.post(f"{self.base_url}/api/generate", json=payload)
                if r.status_code == 200:
                    body = r.json()
                    # Hermes may still embed an "error" field with success status code
                    if "error" in body and "response" not in body:
                        last_err = body["error"]
                        if "busy" in last_err.lower() and attempt < self.max_retries:
                            await asyncio.sleep(self.backoff_seconds * (attempt + 1))
                            continue
                        raise HermesError(f"hermes error: {last_err}")
                    raw = body.get("response", "")
                    if not raw:
                        raise HermesError(f"hermes returned empty response: {body}")
                    try:
                        return json.loads(raw)
                    except json.JSONDecodeError as exc:
                        raise HermesError(
                            f"hermes returned non-JSON despite format=json: {raw[:500]}"
                        ) from exc
                # Ollama returns 503 with body {"error": "server busy ..."}
                # under queue pressure — treat as retryable.
                busy_503 = r.status_code == 503 and "busy" in r.text.lower()
                if (r.status_code >= 500 or busy_503) and attempt < self.max_retries:
                    last_err = f"http {r.status_code}: {r.text[:200]}"
                    await asyncio.sleep(self.backoff_seconds * (attempt + 1))
                    continue
                raise HermesError(f"hermes returned http {r.status_code}: {r.text[:200]}")
            except httpx.TimeoutException as exc:
                last_err = f"timeout after {self.timeout_seconds}s"
                if attempt >= self.max_retries:
                    raise HermesError(last_err) from exc
                await asyncio.sleep(self.backoff_seconds * (attempt + 1))

        raise HermesError(f"hermes exhausted retries: {last_err}")
