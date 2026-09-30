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
        candidate_pmids=["100"], candidates=[{"pmid": "100", "abstract": "Aspirin stroke evidence.", "year": 2020, "study_type": "trial", "filter_satisfied": True}],
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
        "--reports-dir", str(reports), "--run-id", "robust-run", "--allow-subset",
    ])
    report = json.loads((reports / "diagnostic" / "robust-run" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "diagnostic" / "robust-run" / "queries" / "q1.json").read_text(encoding="utf-8"))
    robustness = query["variants"]["dense_only"]["robustness"]

    assert set(robustness["scenarios"]) == set(SCENARIOS)
    assert all(row["provenance"]["scenario"] == name for name, row in robustness["scenarios"].items())
    assert all(row["metric_deltas"] for row in robustness["scenarios"].values())
    assert robustness["scenarios"]["filter_pressure"]["metric_deltas"]["candidate_filter_compliance"] < 0
    assert report["metrics"]["dense_only.robustness"]["status"] == "completed"
    assert report["metrics"]["dense_only.robustness"]["value"]["scenario_count"] == len(SCENARIOS)
    summary = report["robustness"]["dense_only"]
    assert summary["status"] == report["metrics"]["dense_only.robustness"]["status"]
    assert summary["queries"]["q1"] == robustness
    assert "not_run" not in json.dumps(summary)


def test_runner_fails_closed_when_robustness_scorer_returns_empty_metrics(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path)
    evaluate_saved_variants(
        benchmark, artifacts, reports, run_id="empty-deltas",
        robustness_runner=lambda _entry, _artifact, _sample: {},
        allow_subset=True,
    )
    report = json.loads((reports / "diagnostic" / "empty-deltas" / "report.json").read_text(encoding="utf-8"))
    result = report["metrics"]["dense_only.robustness"]
    assert result["status"] == "failed"
    assert result["value"] is None
    assert result["reason"]
    summary = report["robustness"]["dense_only"]
    query = json.loads((reports / "diagnostic" / "empty-deltas" / "queries" / "q1.json").read_text(encoding="utf-8"))
    assert summary["status"] == result["status"]
    assert summary["reason"] == result["reason"]
    assert summary["queries"]["q1"] == query["variants"]["dense_only"]["robustness"]


def test_report_promotion_rejects_missing_requested_variants(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path)
    with pytest.raises(ValueError, match="all four variants"):
        evaluate_saved_variants(benchmark, artifacts, reports, run_id="must-have-four")
    assert not (reports / "manifest.json").exists()


def test_subset_reports_are_written_to_diagnostic_area_not_promoted(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path)
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="diagnostic-dense", allow_subset=True)

    assert (reports / "diagnostic" / "diagnostic-dense" / "report.json").is_file()
    assert (reports / "diagnostic" / "manifest.json").is_file()
    assert not (reports / "manifest.json").exists()


def test_ordinary_report_cli_rejects_dense_only_artifact_set_even_when_all_names_are_requested(tmp_path):
    from evaluation.run_evaluation import main

    benchmark, artifacts, reports, _entry, _artifact = _runner_fixture(tmp_path)
    with pytest.raises(SystemExit) as failure:
        main([
            "--benchmark", str(benchmark), "--artifacts-dir", str(artifacts),
            "--variants", "dense_only", "hybrid", "reranked", "agentic",
            "--output-dir", str(reports), "--run-id", "dense-only-must-not-promote",
        ])
    assert failure.value.code == 2
    assert not (reports / "manifest.json").exists()


@pytest.mark.parametrize("candidate_changes,filter_changes,expected", [
    ({"study_type": "cohort"}, {}, 0.0),
    ({"year": 2010}, {"year_min": 2015}, 0.0),
    ({"filter_satisfied": False}, {}, 0.0),
])
def test_filter_accuracy_uses_candidate_metadata_and_compliance_flag(tmp_path, candidate_changes, filter_changes, expected):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, artifact = _runner_fixture(tmp_path)
    artifact.candidates[0].update(candidate_changes)
    artifact.metadata_filters.update(filter_changes)
    (artifacts / "dense_only" / "q1.json").write_text(artifact.model_dump_json(), encoding="utf-8")
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="hostile-filter", allow_subset=True)
    report = json.loads((reports / "diagnostic" / "hostile-filter" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "diagnostic" / "hostile-filter" / "queries" / "q1.json").read_text(encoding="utf-8"))
    assert report["metrics"]["dense_only.filter_accuracy"]["value"] == expected
    assert query["variants"]["dense_only"]["filter_accuracy"]["status"] == "completed"


@pytest.mark.parametrize("missing_field,year_constraints", [("study_type", {}), ("year", {"year_min": 2015})])
def test_filter_accuracy_is_not_run_when_candidate_constraint_metadata_is_missing(tmp_path, missing_field, year_constraints):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, artifact = _runner_fixture(tmp_path)
    artifact.candidates[0].pop(missing_field)
    artifact.metadata_filters.update(year_constraints)
    (artifacts / "dense_only" / "q1.json").write_text(artifact.model_dump_json(), encoding="utf-8")
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="missing-filter-metadata", allow_subset=True)
    report = json.loads((reports / "diagnostic" / "missing-filter-metadata" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "diagnostic" / "missing-filter-metadata" / "queries" / "q1.json").read_text(encoding="utf-8"))
    assert report["metrics"]["dense_only.filter_accuracy"]["status"] == "not_run"
    assert query["variants"]["dense_only"]["filter_accuracy"]["status"] == "not_run"
    assert missing_field in query["variants"]["dense_only"]["filter_accuracy"]["reason"]


def test_ragas_injected_evaluator_scores_agentic_and_skips_retrieval_only(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, retrieval = _runner_fixture(tmp_path)
    agentic = retrieval.model_copy(update={
        "variant": "agentic",
        "research_plan": {"route": "SIMPLE", "subquestions": [{"id": "sq-1"}]},
        "coverage": [{"iteration": 1, "coverage": [{"subquestion_id": "sq-1", "status": "COVERED"}]}],
        "corrections": [], "evidence": [],
        "answer": {"synthesis": "A supported answer", "answer_status": "SUPPORTED", "cited_pmids": ["100"]},
        "citations": ["100"],
    })
    agentic_dir = artifacts / "agentic"
    agentic_dir.mkdir()
    (agentic_dir / "q1.json").write_text(agentic.model_dump_json(), encoding="utf-8")

    class Evaluator:
        def __init__(self):
            self.samples = []

        def evaluate(self, sample):
            self.samples.append(sample)
            return {"faithfulness": {"status": "completed", "value": 0.75, "reason": None}}

    evaluator = Evaluator()
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="ragas-injected", allow_subset=True, ragas_evaluator=evaluator)
    report = json.loads((reports / "diagnostic" / "ragas-injected" / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["agentic.ragas.faithfulness"] == {"status": "completed", "value": 0.75, "reason": None}
    assert report["metrics"]["dense_only.ragas.faithfulness"]["status"] == "not_run"
    assert "reference" not in evaluator.samples[0]
    assert report["metrics"]["agentic.supported_claim_rate"]["status"] == "not_run"
    assert report["metrics"]["agentic.route_accuracy"]["value"] == 1.0
    assert report["metrics"]["agentic.subquestion_coverage"]["value"] == 1.0
    assert report["metrics"]["agentic.answer_completeness"]["status"] == "not_run"
    assert report["answer_status_distribution"] == {"SUPPORTED": 1}
    query = json.loads((reports / "diagnostic" / "ragas-injected" / "queries" / "q1.json").read_text(encoding="utf-8"))
    assert query["variants"]["agentic"]["answer_status"] == "SUPPORTED"


def test_ragas_missing_provider_and_references_get_prerequisite_specific_reasons(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, retrieval = _runner_fixture(tmp_path)
    agentic = retrieval.model_copy(update={
        "variant": "agentic", "research_plan": {"route": "SIMPLE", "subquestions": [{"id": "sq-1"}]},
        "coverage": [], "corrections": [], "evidence": [],
        "answer": {"synthesis": "A response", "cited_pmids": []}, "citations": [],
    })
    agentic_dir = artifacts / "agentic"
    agentic_dir.mkdir()
    (agentic_dir / "q1.json").write_text(agentic.model_dump_json(), encoding="utf-8")
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="ragas-prerequisites", allow_subset=True)
    report = json.loads((reports / "diagnostic" / "ragas-prerequisites" / "report.json").read_text(encoding="utf-8"))
    assert report["metrics"]["agentic.ragas.faithfulness"]["reason"] == "provider credentials or adapter unavailable"
    assert report["metrics"]["agentic.ragas.context_precision"]["reason"] == "missing required fields: reference"
    assert report["metrics"]["dense_only.ragas.faithfulness"]["reason"] == "retrieval-only variant has no answer-generation sample"


def test_empty_coverage_is_not_run_but_explicit_empty_answered_list_is_zero(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, retrieval = _runner_fixture(tmp_path)
    agentic = retrieval.model_copy(update={
        "variant": "agentic", "research_plan": {"route": "SIMPLE", "subquestions": [{"id": "sq-1"}]},
        "coverage": [], "corrections": [], "evidence": [],
        "answer": {"synthesis": "No subquestions answered", "answered_subquestions": []}, "citations": [],
    })
    directory = artifacts / "agentic"
    directory.mkdir()
    (directory / "q1.json").write_text(agentic.model_dump_json(), encoding="utf-8")
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="empty-observations", allow_subset=True)
    report = json.loads((reports / "diagnostic" / "empty-observations" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "diagnostic" / "empty-observations" / "queries" / "q1.json").read_text(encoding="utf-8"))

    assert report["metrics"]["agentic.subquestion_coverage"]["status"] == "not_run"
    assert query["variants"]["agentic"]["subquestion_coverage"]["status"] == "not_run"
    assert report["metrics"]["agentic.answer_completeness"]["value"] == 0.0
    assert query["variants"]["agentic"]["answer_completeness"]["value"] == 0.0


def test_supporting_span_must_match_candidate_with_same_pmid(tmp_path):
    from evaluation.run_evaluation import evaluate_saved_variants

    benchmark, artifacts, reports, _entry, retrieval = _runner_fixture(tmp_path)
    agentic = retrieval.model_copy(update={
        "variant": "agentic", "research_plan": {"route": "SIMPLE", "subquestions": [{"id": "sq-1"}]},
        "coverage": [{"iteration": 1, "coverage": [{"subquestion_id": "sq-1", "status": "COVERED"}]}],
        "corrections": [], "evidence": [{"pmid": "999", "supporting_text_spans": ["Aspirin stroke evidence."]}],
        "answer": {"synthesis": "A response", "cited_pmids": []}, "citations": [],
    })
    directory = artifacts / "agentic"
    directory.mkdir()
    (directory / "q1.json").write_text(agentic.model_dump_json(), encoding="utf-8")
    evaluate_saved_variants(benchmark, artifacts, reports, run_id="mismatched-span-source", allow_subset=True)
    report = json.loads((reports / "diagnostic" / "mismatched-span-source" / "report.json").read_text(encoding="utf-8"))
    query = json.loads((reports / "diagnostic" / "mismatched-span-source" / "queries" / "q1.json").read_text(encoding="utf-8"))

    assert report["metrics"]["agentic.span_precision"]["value"] == 0.0
    assert query["variants"]["agentic"]["span_precision"]["value"] == 0.0


def test_task11_project_command_accepts_complete_variant_list_and_output_dir(tmp_path, monkeypatch):
    from evaluation import run_evaluation

    called = {}

    def capture(benchmark, artifacts, reports, *, run_id, top_k, allow_subset, ragas_evaluator):
        called.update(benchmark=benchmark, artifacts=artifacts, reports=reports, run_id=run_id, top_k=top_k, allow_subset=allow_subset, ragas_evaluator=ragas_evaluator)
        return {"status": "completed"}

    monkeypatch.setattr(run_evaluation, "evaluate_saved_variants", capture)
    run_evaluation.main([
        "--benchmark", "data/evaluation/benchmark_v2.json",
        "--variants", "dense_only", "hybrid", "reranked", "agentic",
        "--output-dir", str(tmp_path / "reports"),
    ])

    assert called["benchmark"].as_posix() == "data/evaluation/benchmark_v2.json"
    assert called["artifacts"].as_posix() == "data/evaluation/variants"
    assert called["reports"] == tmp_path / "reports"
    assert called["run_id"].startswith("eval-")
