"""Deterministic biomedical retrieval robustness perturbations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping


SCENARIOS = (
    "irrelevant_context", "conflicting_evidence", "incomplete_evidence",
    "misleading_context", "noisy_query", "acronym_query", "filter_pressure",
)


def perturb_sample(sample: Mapping[str, Any], scenario: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown robustness scenario: {scenario}")
    result = deepcopy(dict(sample))
    changed: list[str] = []
    contexts = list(result.get("contexts", []))
    context_pmids = list(result.get("context_pmids", []))
    if scenario == "irrelevant_context":
        contexts.append("Unrelated observational findings on a different population and outcome.")
        result["contexts"] = contexts
        if "context_pmids" in result:
            result["context_pmids"] = context_pmids + [None]
        changed.append("contexts")
    elif scenario == "conflicting_evidence":
        contexts.append("Conflicting trial evidence reports the opposite direction of effect.")
        result["contexts"] = contexts
        if "context_pmids" in result:
            result["context_pmids"] = context_pmids + [None]
        changed.append("contexts")
    elif scenario == "incomplete_evidence":
        result["contexts"] = contexts[: max(0, len(contexts) - 1)]
        if "context_pmids" in result:
            result["context_pmids"] = context_pmids[: max(0, len(context_pmids) - 1)]
        changed.append("contexts")
    elif scenario == "misleading_context":
        contexts.insert(0, "Misleading context: an unadjusted association proves causal benefit.")
        result["contexts"] = contexts
        if "context_pmids" in result:
            result["context_pmids"] = [None, *context_pmids]
        changed.append("contexts")
    elif scenario == "noisy_query":
        query = str(result.get("query", ""))
        result["query"] = query.replace("e", "3", 1) + " ???"
        changed.append("query")
    elif scenario == "acronym_query":
        query = str(result.get("query", ""))
        result["query"] = query.replace("aspirin", "ASA").replace("stroke", "CVA")
        if result["query"] == query:
            result["query"] = "CVA / ASA " + query
        changed.append("query")
    else:
        filters = dict(result.get("filters", {}))
        filters.update({"year_from": 2024, "year_to": 2024, "study_type": "randomized controlled trial", "language": "English"})
        result["filters"] = filters
        changed.append("filters")
    return result, {"scenario": scenario, "changed_fields": changed, "description": scenario.replace("_", " ")}


def evaluate_robustness(sample: Mapping[str, Any], evaluator: Callable[[Mapping[str, Any]], Mapping[str, float | int | None]]) -> dict[str, Any]:
    baseline = dict(evaluator(sample))
    if not baseline or not any(value is not None for value in baseline.values()):
        raise ValueError("baseline robustness evaluation returned no numeric metrics")
    rows: dict[str, Any] = {}
    for scenario in SCENARIOS:
        perturbed, provenance = perturb_sample(sample, scenario)
        metrics = dict(evaluator(perturbed))
        if not metrics or not any(value is not None for value in metrics.values()):
            raise ValueError(f"robustness scenario {scenario} returned no numeric metrics")
        deltas = {
            key: round(float(metrics[key]) - float(value), 10)
            for key, value in baseline.items()
            if value is not None and metrics.get(key) is not None
        }
        if not deltas:
            raise ValueError(f"robustness scenario {scenario} produced no comparable metric deltas")
        rows[scenario] = {"provenance": provenance, "metrics": metrics, "metric_deltas": deltas}
    return {"baseline_metrics": baseline, "scenarios": rows}
