from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest


def _runner_fixture(tmp_path, *, benchmark_version="2.0", artifact_version="2.0", artifact_corpus_identity=None):
    from evaluation.models import BenchmarkDataset
    from evaluation.variants import QueryEvaluationArtifact

    corpus_path = tmp_path / "corpus.parquet"
    pd.DataFrame({"pmid": ["100"]}).to_parquet(corpus_path)
    corpus_identity = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    dataset = BenchmarkDataset.model_validate({
        "version": benchmark_version,
        "corpus_path": str(corpus_path),
        "corpus_record_count": 1,
        "entries": [{
            "id": "q1", "query": "Does aspirin prevent stroke?", "category": "neurology",
            "expected_route": "SIMPLE", "study_type": "trial", "relevant_pmids": ["100"],
            "judgments": [{
                "pmid": "100", "title": "Trial title", "title_match": True, "relevance": 3,
                "rationale": "This primary study reports the target outcome in the target population.",
                "source_url": "https://pubmed.ncbi.nlm.nih.gov/100/", "adjudicated_on": "2026-09-29",
            }],
        }],
    })
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(dataset.model_dump(mode="json")), encoding="utf-8")
    artifact = QueryEvaluationArtifact(
        benchmark_version=artifact_version,
        corpus_identity=artifact_corpus_identity or corpus_identity,
        query_id="q1", query="Does aspirin prevent stroke?", expected_route="SIMPLE",
        variant="dense_only", configuration_hash="d" * 64,
        metadata_filters={"study_types": ["trial"]}, top_k=5,
        candidate_pmids=["100"], candidates=[{"pmid": "100", "abstract": "Aspirin stroke evidence.", "year": 2020, "study_type": "trial"}],
        latency_ms=15,
    )
    artifacts = tmp_path / "artifacts" / "dense_only"
    artifacts.mkdir(parents=True)
    (artifacts / "q1.json").write_text(artifact.model_dump_json(), encoding="utf-8")
    return benchmark_path, tmp_path / "artifacts", tmp_path / "reports", dataset.entries[0], artifact


@pytest.mark.parametrize("field,value", [("benchmark_version", "1.0"), ("corpus_identity", "0" * 64)])
def test_saved_variant_runner_rejects_artifacts_bound_to_other_benchmark_or_corpus(tmp_path, field, value):
    from evaluation.run_evaluation import evaluate_saved_variants

    kwargs = {"artifact_version": "2.0", "artifact_corpus_identity": None}
    if field == "benchmark_version":
        kwargs["artifact_version"] = value
    else:
        kwargs["artifact_corpus_identity"] = value
    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path, **kwargs)

    with pytest.raises(ValueError, match="identity mismatch"):
        evaluate_saved_variants(benchmark, artifacts, reports, run_id="identity-check")
    assert not (reports / "manifest.json").exists()


def test_saved_variant_runner_default_path_persists_all_robustness_scenarios(tmp_path):
    from evaluation.run_evaluation import main
    from evaluation.robustness import SCENARIOS

    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path)
    main([
        "--benchmark", str(benchmark), "--artifacts-dir", str(artifacts),
        "--reports-dir", str(reports), "--run-id", "robust-run",
    ])
    report = json.loads((reports / "robust-run" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "robust-run" / "queries" / "q1.json").read_text(encoding="utf-8"))
    robustness = query["variants"]["dense_only"]["robustness"]

    assert set(robustness["scenarios"]) == set(SCENARIOS)
    assert all(row["provenance"]["scenario"] == name for name, row in robustness["scenarios"].items())
    assert all(row["metric_deltas"] for row in robustness["scenarios"].values())
    assert robustness["scenarios"]["filter_pressure"]["metric_deltas"]["candidate_filter_compliance"] < 0
    assert report["metrics"]["dense_only.robustness"]["status"] == "completed"
    assert report["metrics"]["dense_only.robustness"]["value"]["scenario_count"] == len(SCENARIOS)


def test_runner_fails_closed_when_robustness_scorer_returns_empty_metrics(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path)
    evaluate_saved_variants(
        benchmark, artifacts, reports, run_id="empty-deltas",
        robustness_runner=lambda _entry, _artifact, _sample: {},
    )
    report = json.loads((reports / "empty-deltas" / "report.json").read_text(encoding="utf-8"))
    result = report["metrics"]["dense_only.robustness"]
    assert result["status"] == "failed"
    assert result["value"] is None
    assert result["reason"]
