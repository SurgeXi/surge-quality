"""Unit tests for the rubric prompt template + parser. No I/O."""

from __future__ import annotations

from surge_quality.scoring.parser import parse_rubric_json
from surge_quality.scoring.rubric import AXES, AXIS_DEFINITIONS, render_prompt


def test_axes_match_definitions() -> None:
    assert set(AXES) == set(AXIS_DEFINITIONS.keys())
    assert len(AXES) == 10


def test_render_prompt_includes_message_and_response() -> None:
    p = render_prompt(
        customer_message="why is my bank feed broken?",
        surge_response="Looks like a Plaid token expired.",
        identity_context={"logged_in_user": "sheilia@timesavedap.com"},
    )
    assert "why is my bank feed broken?" in p
    assert "Plaid token expired" in p
    assert "sheilia@timesavedap.com" in p
    for axis in AXES:
        assert axis in p


def test_render_prompt_no_identity() -> None:
    p = render_prompt(
        customer_message="hello", surge_response="hi", identity_context=None
    )
    assert "hello" in p
    assert "IDENTITY CONTEXT" not in p


def test_parse_full_payload() -> None:
    payload = {
        "correctness": 9.0,
        "tone_match": 7.0,
        "completeness": 8.5,
        "action_orientation": 6.0,
        "brevity": 7.5,
        "citation_quality": 5.0,
        "identity_awareness": 8.0,
        "memory_usage": 6.0,
        "safety": 10.0,
        "confidence_calibration": 7.0,
        "justification": "decent answer, missed naming the source",
    }
    parsed = parse_rubric_json(payload)
    assert parsed.axes["correctness"] == 9.0
    assert parsed.composite == sum(
        v for k, v in payload.items() if k in AXES
    ) / len(AXES)
    assert "missed naming" in parsed.justification


def test_parse_missing_axis_defaults_to_5() -> None:
    payload = {"correctness": 9.0, "justification": "partial"}
    parsed = parse_rubric_json(payload)
    assert parsed.axes["correctness"] == 9.0
    assert parsed.axes["safety"] == 5.0  # missing -> default
    expected_composite = (9.0 + 5.0 * 9) / 10
    assert parsed.composite == expected_composite


def test_parse_out_of_range_clamped() -> None:
    payload = {axis: 99.0 for axis in AXES}  # nonsense
    parsed = parse_rubric_json(payload)
    assert all(v == 10.0 for v in parsed.axes.values())
    assert parsed.composite == 10.0


def test_parse_non_numeric_defaults() -> None:
    payload = {"correctness": "not a number", "safety": None}
    parsed = parse_rubric_json(payload)
    assert parsed.axes["correctness"] == 5.0
    assert parsed.axes["safety"] == 5.0
