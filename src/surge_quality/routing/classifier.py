"""Routing classifier — input message + context → routing advice.

Per docs/PLAN.md §5, the output is one of:
- surge                       Surge handles the turn alone
- surge_with_claude_review    Surge drafts, the LLM reviewer reviews before send
- claude_primary              the stronger model handles the turn directly

Decision factors (sorted by weight on the final pick):
1. urgency keywords in the input
2. similarity to past low-scoring turns
3. high-stakes identity context (customer-facing money/tax/deadline)
4. topic complexity (length + keyword heuristic)

The classifier is fully deterministic — no LLM call — so the routing
endpoint is fast (<5ms) and easy to test/reason about. The recommendation
is read-only; the consumer asks SOL to dispatch any side-effect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Trigger words that bias decisions toward the stronger model.
_URGENCY_PATTERNS = re.compile(
    r"\b(urgent|asap|now|broken|help|emergency|right now|immediately|stuck|blocked|"
    r"down|crashed|losing money|can'?t (?:see|find|access|pay))\b",
    re.IGNORECASE,
)

# Topics that warrant elevated scrutiny when the customer is in the seat.
_HIGH_STAKES_PATTERNS = re.compile(
    r"\b(tax|irs|payroll|payment|refund|fraud|audit|deadline|due\b|filing|"
    r"penalty|wire transfer|bank account)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class RouteDecision:
    """Final classifier output."""

    decision: str  # surge | surge_with_claude_review | claude_primary
    reasoning: str
    factors: dict[str, Any]


def _is_customer_facing(identity_context: dict[str, Any] | None) -> bool:
    if not identity_context:
        return False
    user = (identity_context.get("logged_in_user") or "").lower()
    surface = (identity_context.get("session_surface") or "").lower()
    # Customer-facing == NOT Todd (the operator) AND a chat surface.
    if not user:
        return False
    if "todd@surgexi.com" in user:
        return False
    return surface in {"pulsepoint-chat", "pulsepoint_widget", "customer-chat"}


def classify(
    input_message: str,
    *,
    identity_context: dict[str, Any] | None = None,
    history_length: int = 0,
    max_similarity_low_score: float = 0.0,
    similarity_threshold: float = 0.70,
) -> RouteDecision:
    """Produce a deterministic routing decision."""

    factors: dict[str, Any] = {
        "urgency": False,
        "high_stakes": False,
        "customer_facing": False,
        "similarity_to_low_score": round(max_similarity_low_score, 3),
        "similarity_threshold": similarity_threshold,
        "history_length": history_length,
        "message_length": len(input_message),
    }

    urgency = bool(_URGENCY_PATTERNS.search(input_message))
    high_stakes = bool(_HIGH_STAKES_PATTERNS.search(input_message))
    customer_facing = _is_customer_facing(identity_context)
    long_message = len(input_message) > 500  # tier-2/3 complexity heuristic

    factors["urgency"] = urgency
    factors["high_stakes"] = high_stakes
    factors["customer_facing"] = customer_facing
    factors["long_message"] = long_message

    # 1. High similarity to past low-score turns → bias hard to the stronger model.
    if max_similarity_low_score >= similarity_threshold:
        return RouteDecision(
            decision="claude_primary",
            reasoning=(
                f"input is highly similar (jaccard={max_similarity_low_score:.2f}) "
                f"to past low-scoring turns above threshold {similarity_threshold:.2f}"
            ),
            factors=factors,
        )

    # 2. Customer-facing + (urgent OR high-stakes) → stronger-model primary.
    if customer_facing and (urgency or high_stakes):
        why = []
        if urgency:
            why.append("urgency keyword")
        if high_stakes:
            why.append("high-stakes topic")
        return RouteDecision(
            decision="claude_primary",
            reasoning=(
                f"customer-facing surface + {' + '.join(why)}"
            ),
            factors=factors,
        )

    # 3. Customer-facing + long message → the LLM reviewer reviews Surge's draft.
    if customer_facing and long_message:
        return RouteDecision(
            decision="surge_with_claude_review",
            reasoning="customer-facing surface + long/complex message (>500 chars)",
            factors=factors,
        )

    # 4. Moderate similarity to low-score AND customer-facing → review.
    if (
        customer_facing
        and max_similarity_low_score >= similarity_threshold * 0.6
    ):
        return RouteDecision(
            decision="surge_with_claude_review",
            reasoning=(
                f"customer-facing + moderate similarity to past low-score turns "
                f"(jaccard={max_similarity_low_score:.2f})"
            ),
            factors=factors,
        )

    # 5. Default: Surge handles it.
    return RouteDecision(
        decision="surge",
        reasoning=(
            "no high-similarity match, no urgency/high-stakes signal in input"
        ),
        factors=factors,
    )
