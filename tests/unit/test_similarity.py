"""Unit tests for similarity scoring. Pure, no I/O."""

from __future__ import annotations

from surge_quality.routing.similarity import (
    jaccard_similarity,
    max_similarity_to_corpus,
)


def test_jaccard_identical_strings() -> None:
    assert jaccard_similarity("hello world", "hello world") == 1.0


def test_jaccard_disjoint_strings() -> None:
    assert jaccard_similarity("hello world", "foo bar baz quux") == 0.0


def test_jaccard_partial_overlap() -> None:
    s = jaccard_similarity("my bank feed is broken", "my bank feed stopped syncing")
    assert 0.0 < s < 1.0


def test_jaccard_case_insensitive() -> None:
    a = jaccard_similarity("Tax Refund Status", "tax refund status")
    assert a == 1.0


def test_jaccard_empty_strings() -> None:
    assert jaccard_similarity("", "") == 0.0
    assert jaccard_similarity("hello", "") == 0.0


def test_max_similarity_picks_best() -> None:
    corpus = [
        "where is my refund?",
        "my bank feed broke",
        "totally unrelated content here",
    ]
    s = max_similarity_to_corpus("my bank feed stopped syncing", corpus)
    assert s > 0.0
    # The middle corpus entry should score highest
    assert jaccard_similarity(
        "my bank feed stopped syncing", "my bank feed broke"
    ) == s


def test_max_similarity_empty_corpus() -> None:
    assert max_similarity_to_corpus("hello", []) == 0.0
