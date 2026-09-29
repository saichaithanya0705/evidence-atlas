import json

from scripts.evaluate_conversational_research import evaluate_report


def fixture_report():
    return {
        "fixtures": [
            {
                "name": "supported-answer",
                "expected_route": "COMPLEX",
                "actual_route": "COMPLEX",
                "correction_queries": ["query one"],
                "answer_status": "SUPPORTED",
                "citations_valid": True,
                "latency_ms": 120,
                "llm_call_count": 2,
                "claims": [{
                    "released": True,
                    "supported": True,
                    "attributions": [{"pmid": "12345", "exact_span": "Exact abstract wording"}],
                }],
            },
            {
                "name": "insufficient-answer",
                "expected_route": "SIMPLE",
                "actual_route": "SIMPLE",
                "correction_queries": ["query two", "query three"],
                "answer_status": "INSUFFICIENT",
                "citations_valid": True,
                "latency_ms": 80,
                "llm_call_count": 1,
                "claims": [],
            },
        ],
        "optional_signals": {"llm_as_judge": {"score": 0.7}, "ragas": {"faithfulness": 0.9}},
    }


def test_report_prioritizes_deterministic_guardrail_metrics_and_counts_claim_provenance():
    result = evaluate_report(fixture_report())
    assert result["deterministic"]["route_accuracy"] == 1.0
    assert result["deterministic"]["correction_loop_count"] == 3
    assert result["deterministic"]["answer_status_distribution"] == {"SUPPORTED": 1, "INSUFFICIENT": 1}
    assert result["deterministic"]["answer_abstention_distribution"] == {
        "SUPPORTED": 1, "LIMITED": 0, "INSUFFICIENT": 1, "FAILED": 0, "ABSTAIN": 1,
    }
    assert result["deterministic"]["unsupported_claim_rate"] == 0.0
    assert result["deterministic"]["citation_validity_rate"] == 1.0
    assert result["deterministic"]["claim_attribution_rate"] == 1.0
    assert result["deterministic"]["latency_ms"]["mean"] == 100
    assert result["deterministic"]["llm_call_count"] == 3
    assert result["optional_secondary_evidence"]["llm_as_judge"] == {"score": 0.7}
    assert result["optional_secondary_evidence"]["ragas"] == {"faithfulness": 0.9}


def test_report_fails_closed_for_unattributed_and_unsupported_released_claims():
    fixture = fixture_report()
    fixture["fixtures"][0]["claims"].append({"released": True, "supported": False, "attributions": []})
    fixture["fixtures"][0]["citations_valid"] = False
    result = evaluate_report(fixture)
    assert result["deterministic"]["unsupported_claim_rate"] == 0.5
    assert result["deterministic"]["claim_attribution_rate"] == 0.5
    assert result["deterministic"]["citation_validity_rate"] == 0.5
    assert result["deterministic"]["unsupported_released_claim_count"] == 1


def test_abstention_only_report_has_no_claim_attribution_sample():
    report = {
        "fixtures": [{
            "name": "abstention-only", "expected_route": "SIMPLE", "actual_route": "SIMPLE",
            "answer_status": "INSUFFICIENT", "citations_valid": True,
            "latency_ms": 20, "llm_call_count": 0, "claims": [],
        }],
    }

    metrics = evaluate_report(report)["deterministic"]

    assert metrics["unsupported_claim_rate"] == 0.0
    assert metrics["unsupported_released_claim_count"] == 0
    assert metrics["claim_attribution_rate"] is None


def test_fixture_json_serializes_the_full_required_metric_contract():
    encoded = json.dumps(evaluate_report(fixture_report()))
    for metric in (
        "route_accuracy", "correction_loop_count", "answer_status_distribution", "answer_abstention_distribution",
        "unsupported_claim_rate", "citation_validity_rate", "claim_attribution_rate",
        "latency_ms", "llm_call_count",
    ):
        assert f'"{metric}"' in encoded
