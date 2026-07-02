# Copyright © 2026 SurgeXi Business Intelligence, a Teamsmith Enterprises LLC company. All Rights Reserved.
"""Unit tests for the routing classifier. Pure, no I/O."""

from __future__ import annotations

from surge_quality.routing.classifier import classify


def test_urgent_customer_message_routes_to_frontier_primary() -> None:
    r = classify(
        "this is urgent, my payroll is broken right now",
        identity_context={
            "logged_in_user": "sheilia@timesavedap.com",
            "session_surface": "pulsepoint-chat",
        },
    )
    assert r.decision == "claude_primary"
    assert "urgency" in r.reasoning or "high-stakes" in r.reasoning


def test_high_stakes_customer_routes_to_frontier_primary() -> None:
    r = classify(
        "the IRS sent us a deadline notice for the quarterly filing",
        identity_context={
            "logged_in_user": "sheilia@timesavedap.com",
            "session_surface": "pulsepoint-chat",
        },
    )
    assert r.decision == "claude_primary"
    assert "high-stakes" in r.reasoning


def test_operator_in_seat_does_not_get_customer_treatment() -> None:
    """Todd is the operator — no auto-elevation to the frontier tier for him."""
    r = classify(
        "this is urgent, payroll is broken",
        identity_context={
            "logged_in_user": "todd@surgexi.com",
            "session_surface": "pulsepoint-chat",
        },
    )
    assert r.decision == "surge"


def test_long_customer_message_routes_to_review() -> None:
    long_msg = "Hello, I have a long detailed question about something. " * 20
    r = classify(
        long_msg,
        identity_context={
            "logged_in_user": "sheilia@timesavedap.com",
            "session_surface": "pulsepoint-chat",
        },
    )
    assert r.decision == "surge_with_claude_review"
    assert "long" in r.reasoning


def test_high_similarity_to_low_score_routes_to_frontier_primary() -> None:
    r = classify(
        "anything",
        identity_context={"logged_in_user": "sheilia@timesavedap.com"},
        max_similarity_low_score=0.85,
        similarity_threshold=0.7,
    )
    assert r.decision == "claude_primary"
    assert "similar" in r.reasoning


def test_moderate_similarity_to_low_score_routes_to_review() -> None:
    r = classify(
        "anything",
        identity_context={
            "logged_in_user": "sheilia@timesavedap.com",
            "session_surface": "pulsepoint-chat",
        },
        max_similarity_low_score=0.5,
        similarity_threshold=0.7,
    )
    assert r.decision == "surge_with_claude_review"


def test_innocuous_message_routes_to_surge() -> None:
    r = classify("what's the weather today?", identity_context={})
    assert r.decision == "surge"


def test_factors_recorded() -> None:
    r = classify(
        "tax deadline help URGENT",
        identity_context={
            "logged_in_user": "sheilia@timesavedap.com",
            "session_surface": "pulsepoint-chat",
        },
    )
    assert r.factors["urgency"] is True
    assert r.factors["high_stakes"] is True
    assert r.factors["customer_facing"] is True
