from __future__ import annotations


def test_robustness_scenarios_are_exact_and_preserve_perturbation_provenance():
    from evaluation.robustness import SCENARIOS, perturb_sample, evaluate_robustness

    assert SCENARIOS == (
        "irrelevant_context", "conflicting_evidence", "incomplete_evidence",
        "misleading_context", "noisy_query", "acronym_query", "filter_pressure",
    )
    base = {"query": "Does aspirin prevent stroke?", "contexts": ["aspirin evidence"], "filters": {"year": 2020}}
    for scenario in SCENARIOS:
        changed, provenance = perturb_sample(base, scenario)
        assert changed != base
        assert provenance["scenario"] == scenario
        assert provenance["changed_fields"]

    report = evaluate_robustness(base, lambda sample: {"score": 0.8 if sample == base else 0.5})
    assert set(report["scenarios"]) == set(SCENARIOS)
    assert all(row["metric_deltas"]["score"] == -0.3 for row in report["scenarios"].values())
