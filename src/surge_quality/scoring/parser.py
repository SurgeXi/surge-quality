"""Parse the Hermes JSON output into a structured RubricScore record.

The Hermes JSON is best-effort — we tolerate the model omitting an axis
(default to 5.0 = "passable but no signal") rather than refusing to score
at all. The combined ``composite`` is the mean of the 10 axes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from surge_quality.scoring.rubric import AXES


@dataclass(slots=True)
class ParsedRubric:
    """Result of parsing one Hermes JSON output."""

    axes: dict[str, float]
    composite: float
    justification: str
    raw: dict[str, Any] = field(default_factory=dict)


def _coerce_float(value: Any, default: float = 5.0) -> float:
    """Best-effort numeric coercion. Out-of-range values are clamped to [0, 10]."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return max(0.0, min(10.0, f))


def parse_rubric_json(payload: dict[str, Any]) -> ParsedRubric:
    """Parse a Hermes JSON payload into a ParsedRubric.

    Missing axes default to 5.0 (neutral). Extra keys are ignored but
    preserved in ``raw``. The justification falls back to a short string
    if missing/blank — never crashes.
    """
    axes_out: dict[str, float] = {}
    for axis in AXES:
        axes_out[axis] = _coerce_float(payload.get(axis, 5.0))

    composite = sum(axes_out.values()) / len(AXES)
    justification = str(payload.get("justification") or "").strip() or "(no justification provided)"

    return ParsedRubric(
        axes=axes_out,
        composite=composite,
        justification=justification,
        raw=payload,
    )
