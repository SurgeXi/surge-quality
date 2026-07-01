"""Parse the LLM reviewer's JSON into a structured ParsedReview.

the LLM reviewer is usually well-behaved with JSON but occasionally wraps the
output in ```json ... ``` fences or prepends a single explanatory
sentence. We strip those defensively.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]+?)\s*```", re.MULTILINE)


@dataclass(slots=True)
class ParsedReview:
    better_response: str
    what_was_wrong: str
    how_to_fix: str
    raw: dict | None = None


class ReviewParseError(ValueError):
    """Raised when the LLM reviewer's output cannot be parsed into the contract."""


def _strip_fences(text: str) -> str:
    m = _JSON_FENCE.search(text)
    if m:
        return m.group(1).strip()
    # Otherwise look for the first '{' and the last '}' and trim.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text.strip()


def parse_review_json(raw_text: str) -> ParsedReview:
    """Best-effort parse of the LLM reviewer's output."""
    if not raw_text or not raw_text.strip():
        raise ReviewParseError("reviewer returned empty body")
    cleaned = _strip_fences(raw_text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ReviewParseError(f"non-JSON output from reviewer: {cleaned[:300]}") from exc
    if not isinstance(payload, dict):
        raise ReviewParseError("reviewer output was not a JSON object")
    return ParsedReview(
        better_response=str(payload.get("better_response", "")).strip(),
        what_was_wrong=str(payload.get("what_was_wrong", "")).strip(),
        how_to_fix=str(payload.get("how_to_fix", "")).strip(),
        raw=payload,
    )
