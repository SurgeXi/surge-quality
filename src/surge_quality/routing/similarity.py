"""Similarity scoring between incoming messages and past low-score turns.

We use a simple token-overlap (Jaccard-on-shingles) measure rather than
an embedding-based one for the MVP, because:

1. Hermes is queue-saturated for embedding swaps right now (per PR-3
   smoke notes); we shouldn't depend on Hermes for routing decisions.
2. Jaccard-on-shingles is robust to short queries and ships with zero
   extra dependencies — no embedding store, no vector index, no rebuilds.
3. A future iteration can swap this for nomic-embed-text + pgvector when a
   underloaded and the volume justifies the operational cost.

The similarity score is in [0.0, 1.0] where 0.0 = disjoint and 1.0 =
identical shingles.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _shingles(tokens: list[str], k: int = 2) -> set[tuple[str, ...]]:
    if len(tokens) < k:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def jaccard_similarity(text_a: str, text_b: str, *, k: int = 2) -> float:
    """0.0 (disjoint) to 1.0 (identical k-shingles)."""
    sh_a = _shingles(_tokenize(text_a), k=k)
    sh_b = _shingles(_tokenize(text_b), k=k)
    if not sh_a or not sh_b:
        return 0.0
    inter = sh_a & sh_b
    union = sh_a | sh_b
    return len(inter) / len(union)


def max_similarity_to_corpus(
    incoming: str, corpus: Iterable[str], *, k: int = 2
) -> float:
    """Return the highest Jaccard similarity between incoming and any
    document in the corpus. Empty corpus -> 0.0."""
    best = 0.0
    for other in corpus:
        s = jaccard_similarity(incoming, other, k=k)
        if s > best:
            best = s
    return best
