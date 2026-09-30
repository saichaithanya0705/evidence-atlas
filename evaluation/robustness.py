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
    if scenario == "irrelevant_context":
        contexts.append("Unrelated observational findings on a different population and outcome.")
        result["contexts"] = contexts
        changed.append("contexts")
    elif scenario == "conflicting_evidence":
        contexts.append("Conflicting trial evidence reports the opposite direction of effect.")
        result["contexts"] = contexts
        changed.append("contexts")
    elif scenario == "incomplete_evidence":
        result["contexts"] = contexts[: max(0, len(contexts) - 1)]
        changed.append("contexts")
    elif scenario == "misleading_context":
        contexts.insert(0, "Misleading context: an unadjusted association proves causal benefit.")
        result["contexts"] = contexts
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
    rows: dict[str, Any] = {}
    for scenario in SCENARIOS:
        perturbed, provenance = perturb_sample(sample, scenario)
        metrics = dict(evaluator(perturbed))
        deltas = {
            key: round(float(metrics[key]) - float(value), 10)
            for key, value in baseline.items()
            if value is not None and metrics.get(key) is not None
        }
        rows[scenario] = {"provenance": provenance, "metrics": metrics, "metric_deltas": deltas}
    return {"baseline_metrics": baseline, "scenarios": rows}
