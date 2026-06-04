"""Hermes client unit tests against a mocked Ollama endpoint."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from surge_quality.scoring.hermes_client import HermesClient, HermesError


@pytest.mark.asyncio
async def test_generate_json_success() -> None:
    payload = {"correctness": 8.0, "safety": 10.0, "justification": "ok"}
    with respx.mock(base_url="http://hermes.test") as mock:
        mock.post("/api/generate").mock(
            return_value=httpx.Response(
                200, json={"response": json.dumps(payload), "done": True}
            )
        )
        client = HermesClient("http://hermes.test", "hermes3:8b", timeout_seconds=5)
        out = await client.generate_json("prompt", system="sys")
    assert out["correctness"] == 8.0
    assert out["justification"] == "ok"


@pytest.mark.asyncio
async def test_generate_json_retries_on_busy() -> None:
    payload = {"correctness": 7.0, "justification": "second try"}
    with respx.mock(base_url="http://hermes.test") as mock:
        route = mock.post("/api/generate")
        route.side_effect = [
            httpx.Response(200, json={"error": "server busy, try again"}),
            httpx.Response(200, json={"response": json.dumps(payload), "done": True}),
        ]
        client = HermesClient(
            "http://hermes.test", "hermes3:8b", timeout_seconds=5, backoff_seconds=0
        )
        out = await client.generate_json("prompt")
    assert out["correctness"] == 7.0


@pytest.mark.asyncio
async def test_generate_json_raises_on_hard_error() -> None:
    with respx.mock(base_url="http://hermes.test") as mock:
        mock.post("/api/generate").mock(
            return_value=httpx.Response(400, json={"error": "bad request"})
        )
        client = HermesClient(
            "http://hermes.test", "hermes3:8b", timeout_seconds=5, backoff_seconds=0
        )
        with pytest.raises(HermesError):
            await client.generate_json("prompt")


@pytest.mark.asyncio
async def test_generate_json_raises_on_garbage() -> None:
    with respx.mock(base_url="http://hermes.test") as mock:
        mock.post("/api/generate").mock(
            return_value=httpx.Response(
                200, json={"response": "this is not json", "done": True}
            )
        )
        client = HermesClient(
            "http://hermes.test", "hermes3:8b", timeout_seconds=5, backoff_seconds=0
        )
        with pytest.raises(HermesError):
            await client.generate_json("prompt")
