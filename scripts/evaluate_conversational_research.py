"""Evaluate deterministic conversational research fixtures without corpus access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def evaluate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Summarize deterministic route, release, provenance, cost, and latency signals."""
    fixtures = report.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("report.fixtures must be a non-empty list")

    route_cases = [item for item in fixtures if item.get("expected_route") is not None]
    route_accuracy = (
        sum(str(item.get("expected_route")).upper() == str(item.get("actual_route", "")).upper() for item in route_cases)
        / len(route_cases)
        if route_cases else 0.0
    )
    status_counts: dict[str, int] = {}
    abstention_count = 0
    correction_count = 0
    latencies: list[float] = []
    llm_call_count = 0
    released_claims = []
    citation_cases = []
    for item in fixtures:
        status = str(item.get("answer_status", "UNKNOWN")).upper()
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "INSUFFICIENT" or str(item.get("action", "")).upper() == "ABSTAIN":
            abstention_count += 1
        correction_count += len(item.get("correction_queries") or [])
        if item.get("latency_ms") is not None:
            latencies.append(float(item["latency_ms"]))
        llm_call_count += max(0, int(item.get("llm_call_count", 0)))
        citation_cases.append(bool(item.get("citations_valid", False)))
        released_claims.extend(claim for claim in item.get("claims", []) if claim.get("released"))

    unsupported_count = sum(not bool(claim.get("supported")) for claim in released_claims)
    attributed_count = sum(
        bool(claim.get("supported")) and any(
            isinstance(source, dict) and str(source.get("pmid", "")).isdigit()
            and bool(str(source.get("exact_span", "")).strip())
            for source in claim.get("attributions", [])
        )
        for claim in released_claims
    )
    return {
        "deterministic": {
            "fixture_count": len(fixtures),
            "route_accuracy": route_accuracy,
            "correction_loop_count": correction_count,
            "answer_status_distribution": dict(sorted(status_counts.items())),
            "answer_abstention_distribution": {
                "SUPPORTED": status_counts.get("SUPPORTED", 0),
                "LIMITED": status_counts.get("LIMITED", 0),
                "INSUFFICIENT": status_counts.get("INSUFFICIENT", 0),
                "FAILED": status_counts.get("FAILED", 0),
                "ABSTAIN": abstention_count,
            },
            "unsupported_claim_rate": unsupported_count / len(released_claims) if released_claims else 0.0,
            "unsupported_released_claim_count": unsupported_count,
            "citation_validity_rate": sum(citation_cases) / len(citation_cases) if citation_cases else 1.0,
            "claim_attribution_rate": attributed_count / len(released_claims) if released_claims else None,
            "latency_ms": {
                "sample_count": len(latencies),
                "mean": mean(latencies) if latencies else 0.0,
                "max": max(latencies) if latencies else 0.0,
            },
            "llm_call_count": llm_call_count,
        },
        "optional_secondary_evidence": report.get("optional_signals", {}),
        "note": "Deterministic fixture checks are primary; optional LLM-as-judge and RAGAS-style signals are secondary evidence.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Path to a deterministic fixture report JSON object")
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    print(json.dumps(evaluate_report(report), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
