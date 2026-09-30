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
        candidate_pmids=["100"], candidates=[{"pmid": "100", "abstract": "Aspirin stroke evidence."}],
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


def test_saved_variant_runner_accepts_matching_identity_and_persists_robustness_results(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants
    from evaluation.robustness import SCENARIOS

    benchmark, artifacts, reports, entry, artifact = _runner_fixture(tmp_path)
    calls = []

    def robustness_runner(current_entry, current_artifact, sample):
        calls.append((current_entry.id, current_artifact.query_id, sample["query"]))
        return {"relevance": 0.8 if sample["query"] == current_entry.query else 0.4}

    evaluate_saved_variants(
        benchmark, artifacts, reports, run_id="robust-run", robustness_runner=robustness_runner,
    )
    report = json.loads((reports / "robust-run" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "robust-run" / "queries" / "q1.json").read_text(encoding="utf-8"))
    robustness = query["variants"]["dense_only"]["robustness"]

    assert calls[0][:2] == (entry.id, artifact.query_id)
    assert set(robustness["scenarios"]) == set(SCENARIOS)
    assert all(row["provenance"]["scenario"] == name for name, row in robustness["scenarios"].items())
    assert all("relevance" in row["metric_deltas"] for row in robustness["scenarios"].values())
    assert report["metrics"]["dense_only.robustness"]["status"] == "completed"
    assert report["metrics"]["dense_only.robustness"]["value"]["scenario_count"] == len(SCENARIOS)

    evaluate_saved_variants(benchmark, artifacts, reports, run_id="robust-not-run")
    skipped_report = json.loads((reports / "robust-not-run" / "report.json").read_text(encoding="utf-8"))
    assert skipped_report["metrics"]["dense_only.robustness"]["status"] == "not_run"
    assert "callback" in skipped_report["metrics"]["dense_only.robustness"]["reason"]
