"""Optional RAGAS collections scorers behind an isolated, lazy adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Iterable, Protocol


SCORERS = {
    "faithfulness": ("Faithfulness", {"user_input", "response", "retrieved_contexts"}),
    "context_precision": ("ContextPrecision", {"user_input", "retrieved_contexts", "reference"}),
    "context_recall": ("ContextRecall", {"user_input", "retrieved_contexts", "reference"}),
    "context_entity_recall": ("ContextEntityRecall", {"reference", "retrieved_contexts"}),
    "answer_relevancy": ("AnswerRelevancy", {"user_input", "response", "retrieved_contexts"}),
    "answer_correctness": ("AnswerCorrectness", {"response", "reference"}),
}


class ProviderAdapter(Protocol):
    """Provider boundary keeps credentials and client setup outside evaluation."""

    def score(self, scorer: Any, sample: Mapping[str, Any]) -> float: ...


class RagasEvaluator:
    """Run collection scorers through an explicitly supplied provider adapter.

    Providers implement ``score(scorer_name, sample)``.  RAGAS is imported only
    when evaluation is requested, keeping the core evaluator optional.
    """

    def __init__(self, provider: Any = None):
        self.provider = provider
        self._scorers: dict[str, Any] | None = None

    def _load_scorers(self) -> dict[str, Any]:
        if self._scorers is None:
            from ragas.metrics.collections import (
                AnswerCorrectness, AnswerRelevancy, ContextEntityRecall,
                ContextPrecision, ContextRecall, Faithfulness,
            )
            self._scorers = {
                "Faithfulness": Faithfulness,
                "ContextPrecision": ContextPrecision,
                "ContextRecall": ContextRecall,
                "ContextEntityRecall": ContextEntityRecall,
                "AnswerRelevancy": AnswerRelevancy,
                "AnswerCorrectness": AnswerCorrectness,
            }
        return self._scorers

    def evaluate(self, sample: Mapping[str, Any], metrics: Iterable[str] | None = None) -> dict[str, dict[str, Any]]:
        selected = list(metrics or SCORERS)
        results: dict[str, dict[str, Any]] = {}
        scorers = None
        for name in selected:
            if name not in SCORERS:
                results[name] = {"status": "not_run", "value": None, "reason": "unknown RAGAS metric"}
                continue
            scorer_name, required = SCORERS[name]
            missing = sorted(field for field in required if sample.get(field) is None or sample.get(field) == "" or sample.get(field) == [])
            if missing:
                results[name] = {"status": "not_run", "value": None, "reason": f"missing required fields: {', '.join(missing)}"}
                continue
            if self.provider is None:
                results[name] = {"status": "not_run", "value": None, "reason": "provider credentials or adapter unavailable"}
                continue
            try:
                if scorers is None:
                    scorers = self._load_scorers()
                score = self.provider.score(scorers[scorer_name], {field: sample[field] for field in required})
                if hasattr(score, "__await__"):
                    raise TypeError("async providers are not supported by the synchronous evaluator")
                results[name] = {"status": "completed", "value": float(score), "reason": None}
            except (ImportError, ModuleNotFoundError) as exc:
                results[name] = {"status": "not_run", "value": None, "reason": f"optional RAGAS dependency unavailable: {exc}"}
            except Exception as exc:  # Per-metric isolation is intentional.
                results[name] = {"status": "failed", "value": None, "reason": str(exc)[:240] or type(exc).__name__}
        return results
