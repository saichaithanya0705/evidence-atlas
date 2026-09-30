"""Dependency-free deterministic metrics for retrieval and answer evaluation."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Iterable, Mapping, Sequence


def _relevant(relevance: Mapping[str, int] | Iterable[str]) -> dict[str, int]:
    if isinstance(relevance, Mapping):
        return {str(key): int(value) for key, value in relevance.items() if int(value) > 0}
    return {str(item): 1 for item in relevance}


def recall_at_k(ranking: Sequence[str], relevance: Mapping[str, int] | Iterable[str], k: int) -> float | None:
    """Binary Recall@k; missing/empty reference labels are undefined (None)."""
    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = _relevant(relevance)
    if not relevant:
        return None
    return len(set(map(str, ranking[:k])) & relevant.keys()) / len(relevant)


def precision_at_k(ranking: Sequence[str], relevance: Mapping[str, int] | Iterable[str], k: int) -> float:
    """Precision@k uses the requested k as denominator, even for short rankings."""
    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = _relevant(relevance)
    return len(set(map(str, ranking[:k])) & relevant.keys()) / k


def reciprocal_rank(ranking: Sequence[str], relevance: Mapping[str, int] | Iterable[str], k: int) -> float:
    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = _relevant(relevance)
    return next((1.0 / rank for rank, item in enumerate(ranking[:k], 1) if str(item) in relevant), 0.0)


def ndcg_at_k(ranking: Sequence[str], relevance: Mapping[str, int] | Iterable[str], k: int) -> float:
    """Graded nDCG@k with linear gains and log2(rank + 1) discount."""
    if k < 1:
        raise ValueError("k must be >= 1")
    relevant = _relevant(relevance)
    if not relevant:
        return 0.0
    dcg = sum(relevant.get(str(item), 0) / math.log2(rank + 1) for rank, item in enumerate(ranking[:k], 1))
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


ROUTES = ("SIMPLE", "MODERATE", "COMPLEX")


def route_confusion(expected: Sequence[str | None], predicted: Sequence[str | None]) -> dict[str, dict[str, int]]:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted routes must have equal length")
    matrix = {actual: {guess: 0 for guess in ROUTES} for actual in ROUTES}
    for actual, guess in zip(expected, predicted):
        if actual in matrix and guess in ROUTES:
            matrix[actual][guess] += 1
    return matrix


def route_accuracy(expected: Sequence[str | None], predicted: Sequence[str | None]) -> float | None:
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted routes must have equal length")
    labeled = [(a, p) for a, p in zip(expected, predicted) if a in ROUTES]
    return sum(a == p for a, p in labeled) / len(labeled) if labeled else None


def filter_accuracy(expected: Mapping[str, object], applied: Mapping[str, object]) -> float | None:
    """Fraction of expected filters exactly applied; absent expected filters are undefined."""
    return sum(applied.get(key) == value for key, value in expected.items()) / len(expected) if expected else None


def subquestion_coverage(required: Iterable[str], covered: Iterable[str]) -> float | None:
    required_set = set(required)
    return len(required_set & set(covered)) / len(required_set) if required_set else None


def answer_completeness(required: Iterable[str], answered: Iterable[str]) -> float | None:
    return subquestion_coverage(required, answered)


def citation_validity(citations: Iterable[str], valid_pmids: Iterable[str]) -> float | None:
    citations = list(map(str, citations))
    if not citations:
        return None
    valid = set(map(str, valid_pmids))
    return sum(citation in valid for citation in citations) / len(citations)


def citation_precision(citations: Iterable[str], relevant_pmids: Iterable[str]) -> float | None:
    return citation_validity(citations, relevant_pmids)


def span_precision(valid_spans: int, cited_spans: int) -> float | None:
    return valid_spans / cited_spans if cited_spans else None


def attribution_precision(correct_attributions: int, total_attributions: int) -> float | None:
    return correct_attributions / total_attributions if total_attributions else None


def supported_claim_rate(supported_claims: int, material_claims: int) -> float | None:
    return supported_claims / material_claims if material_claims else None


def latency_summary(latencies_ms: Iterable[float]) -> dict[str, float | int | None]:
    values = sorted(float(value) for value in latencies_ms)
    if not values:
        return {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    return {"count": len(values), "min": values[0], "median": statistics.median(values), "mean": statistics.fmean(values), "max": values[-1]}


def failure_category_counts(categories: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(str(category) for category in categories if category).items()))
