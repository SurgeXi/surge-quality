# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Unit tests for reviewer prompt rendering + parser."""

from __future__ import annotations

import json

import pytest

from surge_quality.reviewer.parser import ReviewParseError, parse_review_json
from surge_quality.reviewer.prompts import SYSTEM_PROMPT, render_user_prompt


def test_system_prompt_specifies_json_only() -> None:
    assert "JSON" in SYSTEM_PROMPT
    assert "better_response" in SYSTEM_PROMPT
    assert "what_was_wrong" in SYSTEM_PROMPT
    assert "how_to_fix" in SYSTEM_PROMPT


def test_render_user_prompt_includes_all_inputs() -> None:
    p = render_user_prompt(
        customer_message="why is my bank feed broken?",
        surge_response="Looks like a token expired.",
        rubric_axes={"correctness": 3.0, "safety": 10.0},
        rubric_composite=4.5,
        telemetry_signals=[{"signal_type": "thumbs_down", "value": 1.0}],
        identity_context={"logged_in_user": "sheilia@timesavedap.com"},
    )
    assert "bank feed broken" in p
    assert "token expired" in p
    assert "correctness" in p
    assert "thumbs_down" in p
    assert "sheilia" in p


def test_render_user_prompt_without_optional_blocks() -> None:
    p = render_user_prompt(
        customer_message="hi",
        surge_response="hello",
        rubric_axes={"correctness": 5.0},
        rubric_composite=5.0,
    )
    assert "CUSTOMER TELEMETRY" not in p
    assert "IDENTITY CONTEXT" not in p


def test_parse_review_clean_json() -> None:
    payload = {
        "better_response": "Here is the better answer.",
        "what_was_wrong": "Ignored the actual question.",
        "how_to_fix": "Re-read the user's last turn before composing.",
    }
    parsed = parse_review_json(json.dumps(payload))
    assert parsed.better_response == "Here is the better answer."
    assert parsed.what_was_wrong == "Ignored the actual question."
    assert parsed.how_to_fix == "Re-read the user's last turn before composing."


def test_parse_review_fenced_json() -> None:
    fenced = (
        "Sure, here is the review:\n\n```json\n"
        '{"better_response":"a","what_was_wrong":"b","how_to_fix":"c"}'
        "\n```"
    )
    parsed = parse_review_json(fenced)
    assert parsed.better_response == "a"
    assert parsed.what_was_wrong == "b"
    assert parsed.how_to_fix == "c"


def test_parse_review_with_prose_around_braces() -> None:
    text = (
        'I think Surge should have said this: {"better_response":"x",'
        '"what_was_wrong":"y","how_to_fix":"z"} and then continue.'
    )
    parsed = parse_review_json(text)
    assert parsed.better_response == "x"


def test_parse_review_empty_raises() -> None:
    with pytest.raises(ReviewParseError):
        parse_review_json("")


def test_parse_review_garbage_raises() -> None:
    with pytest.raises(ReviewParseError):
        parse_review_json("definitely not json at all")
