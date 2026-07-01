# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""LLM reviewer prompt templates.

The reviewer's job is to be the senior partner that fixes + teaches.
Output is strict JSON: better_response, what_was_wrong, how_to_fix.
"""

from __future__ import annotations

import json
from textwrap import dedent
from typing import Any

SYSTEM_PROMPT = dedent(
    """\
    You are the senior partner reviewing an AI assistant ("Surge")
    response that scored poorly on a 10-axis rubric. Your role is the
    teacher / repairer: show what Surge SHOULD have said, explain what
    went wrong, and describe a concrete change Surge can apply next time
    on similar turns.

    You MUST return ONLY a JSON object with EXACTLY these three string
    fields (no other keys, no prose before or after):

      {
        "better_response": "the response you would have given the customer",
        "what_was_wrong": "specific issues in the original Surge response",
        "how_to_fix": "concrete advice for Surge's next turn on similar input"
      }

    Keep "better_response" customer-ready (no meta commentary).
    Keep "what_was_wrong" specific (cite the bad axis or behavior).
    Keep "how_to_fix" actionable (one or two concrete changes).
    """
).strip()


def render_user_prompt(
    *,
    customer_message: str,
    surge_response: str,
    rubric_axes: dict[str, float],
    rubric_composite: float,
    telemetry_signals: list[dict[str, Any]] | None = None,
    identity_context: dict[str, Any] | None = None,
) -> str:
    """Compose the per-call user prompt fed to the LLM reviewer."""
    telemetry_block = ""
    if telemetry_signals:
        telemetry_block = (
            "\nCUSTOMER TELEMETRY SIGNALS (post-response):\n"
            + json.dumps(telemetry_signals, indent=2, default=str)
        )
    identity_block = ""
    if identity_context:
        identity_block = "\nIDENTITY CONTEXT:\n" + json.dumps(
            identity_context, indent=2, default=str
        )
    rubric_block = json.dumps(
        {"composite": rubric_composite, **rubric_axes}, indent=2
    )
    return dedent(
        f"""\
        CUSTOMER MESSAGE:
        \"\"\"
        {customer_message}
        \"\"\"

        SURGE RESPONSE:
        \"\"\"
        {surge_response}
        \"\"\"

        RUBRIC SCORE (composite 0-10, plus per-axis):
        {rubric_block}{telemetry_block}{identity_block}

        Return your review as the JSON object specified in the system
        instructions. JSON only — no prose.
        """
    ).strip()
