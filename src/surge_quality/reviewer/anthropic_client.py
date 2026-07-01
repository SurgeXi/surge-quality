"""Anthropic SDK wrapper for the LLM-as-teacher reviewer.

We use the async client so the reviewer can be invoked from inside an
async FastAPI background task without blocking the event loop. The model
defaults to ``claude-opus-4-7`` per settings; the prompt produces a
strict JSON object that ``parser.py`` can deserialize.

Prompt caching: the system prompt (the persona + JSON contract) is
identical for every review call, so we cache it. The variable per-call
payload — the actual Surge response + rubric scores — is NOT cached.
"""

from __future__ import annotations

import logging
from typing import Any

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


class AnthropicClient:
    """Thin async wrapper over the Anthropic SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-7",
        max_tokens: int = 2048,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is empty — reviewer cannot run")
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
