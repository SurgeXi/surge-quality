# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""LLM reviewer client for the LLM-as-teacher loop.

The reviewer is a pluggable seam: ``LlmReviewer`` exposes a provider-neutral
``review()`` coroutine and ships with a hosted-frontier backend as the default
implementation. Swapping the backend is a matter of pointing the seam at a
different client that satisfies the same ``review()`` contract.

We use an async client so the reviewer can be invoked from inside an async
FastAPI background task without blocking the event loop. The model defaults to
the value in settings; the prompt produces a strict JSON object that
``parser.py`` can deserialize.

Prompt caching: the system prompt (the persona + JSON contract) is identical
for every review call, so we cache it. The variable per-call payload — the
actual Surge response + rubric scores — is NOT cached.
"""

from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


class LlmReviewer:
    """Async LLM reviewer client.

    Ships with a hosted-frontier backend (the Anthropic SDK) as the default
    provider. The public surface — the ``review()`` coroutine — is
    provider-neutral so an alternate backend can be dropped in without
    touching the reviewer service.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-7",
        max_tokens: int = 2048,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("reviewer API key is empty — reviewer cannot run")
        self.model = model
        self.max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

    async def review(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        cache_system: bool = True,
    ) -> str:
        """Call the LLM reviewer; return the raw text body. The caller parses JSON."""
        system_blocks: list[dict[str, Any]] = [
            {"type": "text", "text": system_prompt}
        ]
        if cache_system:
            system_blocks[0]["cache_control"] = {"type": "ephemeral"}

        msg = await self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_blocks,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if not msg.content:
            return ""
        block = msg.content[0]
        return getattr(block, "text", "") or ""
