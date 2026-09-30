"""Focused tests for fail-closed setup and the small benchmark harness."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from evaluation.citations import evaluate_answer_citations
from evaluation.run_evaluation import evaluate_retrieval_and_router
from scripts.setup_assets import MEDCPT_MODELS, ModelSetupError, setup_dataset, setup_models


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_transformers(monkeypatch, fail_model: str | None = None, expected_offline: bool | None = None):
    module = ModuleType("transformers")

    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):
            if expected_offline is not None:
                assert kwargs["local_files_only"] is expected_offline
            if model_id == fail_model:
                raise OSError("simulated unavailable weights")
            return object()

    class FakeTokenizer(FakeModel):
        pass

    module.AutoTokenizer = FakeTokenizer
    module.AutoModel = FakeModel
    module.AutoModelForSequenceClassification = FakeModel
    monkeypatch.setitem(sys.modules, "transformers", module)


def test_online_model_setup_requires_all_three_models(tmp_path, monkeypatch):
    _fake_transformers(monkeypatch, fail_model=MEDCPT_MODELS[1], expected_offline=False)

    with pytest.raises(ModelSetupError) as error:
        setup_models(tmp_path / "cache")

    assert error.value.statuses[MEDCPT_MODELS[0]]["status"] == "cached"
    assert error.value.statuses[MEDCPT_MODELS[1]]["status"] == "failed"
    assert error.value.statuses[MEDCPT_MODELS[2]]["status"] == "cached"


def test_explicit_offline_mode_uses_cached_weights_or_marks_mock(tmp_path, monkeypatch):
    _fake_transformers(monkeypatch, fail_model=MEDCPT_MODELS[0], expected_offline=True)

    result = setup_models(tmp_path / "cache", offline=True)

    assert result[MEDCPT_MODELS[0]]["status"] == "offline_mock"
    assert all(result[model]["status"] == "cached" for model in MEDCPT_MODELS[1:])


def test_dataset_reuse_checks_schema_and_is_idempotent(tmp_path):
    fixture_root = tmp_path / "project"
    fixture_path = fixture_root / "tests" / "fixtures" / "synthetic_pubmed.csv"
    fixture_path.parent.mkdir(parents=True)
    fixture_path.write_text("pmid,title,abstract\n123,Title,Abstract\n", encoding="utf-8")
    raw_path = fixture_root / "data" / "raw" / "pubmed_sample.csv"

    assert setup_dataset(fixture_root, raw_path) == 1
    before = raw_path.read_bytes()
    assert setup_dataset(fixture_root, raw_path) == 1
    assert raw_path.read_bytes() == before

    raw_path.write_text("bad_header\nrow\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required columns"):
        setup_dataset(fixture_root, raw_path)


def test_ir_and_router_metrics_use_labeled_queries():
    queries = [
        {"id": "one", "query": "alpha", "relevant_pmids": ["1"], "expected_route": "SIMPLE"},
        {"id": "two", "query": "beta", "relevant_pmids": ["2", "3"], "expected_route": "COMPLEX"},
    ]
    rankings = {"alpha": [(1, 2.0), (2, 1.0)], "beta": [(9, 3.0), (3, 1.0)]}
    routes = {"alpha": "SIMPLE", "beta": "COMPLEX"}

    report = evaluate_retrieval_and_router(
        queries,
        lambda query, top_k: rankings[query][:top_k],
        lambda query: routes[query],
        top_k=2,
    )

    assert report["metrics"]["recall@2"] == pytest.approx(0.75)
    assert report["metrics"]["precision@2"] == pytest.approx(0.5)
    assert report["metrics"]["router_accuracy"] == 1.0


def test_citation_checks_fail_closed_for_unretrieved_ids_and_bad_quotes():
    abstract = "Treatment reduced hospitalization in the reported study."
    answer = {
        "evidence": [{"pmid": "123", "abstract": abstract}],
        "claims": [{
            "text": "Treatment reduced hospitalization.",
            "citations": [
                {"pmid": "123", "quote": "Treatment reduced hospitalization"},
                {"pmid": "999", "quote": "Fabricated evidence"},
                {"pmid": "123", "quote": "This text is absent"},
            ],
        }],
    }

    result = evaluate_answer_citations(answer)

    assert result["citation_count"] == 3
    assert result["valid_pmid_count"] == 2
    assert result["quoted_span_count"] == 3
    assert result["valid_quoted_span_count"] == 1
    assert [item["reason"] for item in result["invalid_citations"]] == [
        "pmid_not_in_retrieved_evidence",
        "quote_not_in_cited_abstract",
    ]


def test_citation_check_reads_research_response_and_does_not_trust_reported_precision():
    abstract = "Participants receiving treatment had fewer hospitalizations."
    response = {
        "synthesis": "Treatment reduced hospitalizations [PMID: 123].",
        "cited_pmids": ["123", "999"],
        "citations_valid": True,
        "citation_precision": 1.0,
        "retrieved_papers": [{"pmid": "123", "abstract": abstract}],
        "evidence_table": [{"pmid": "123", "supporting_text_spans": ["fewer hospitalizations"]}],
    }

    result = evaluate_answer_citations(response)

    assert result["pmid_precision"] == pytest.approx(0.5)
    assert result["quoted_span_precision"] == 1.0
    assert result["invalid_citations"][0]["pmid"] == "999"


def test_benchmark_relevance_labels_are_present_in_bundled_demo_corpus():
    root = Path(__file__).resolve().parents[2]
    with (root / "tests" / "fixtures" / "synthetic_pubmed.csv").open(encoding="utf-8", newline="") as stream:
        pmids = {row["pmid"] for row in csv.DictReader(stream)}
    benchmark = json.loads((root / "data" / "evaluation" / "queries.json").read_text(encoding="utf-8"))

    assert benchmark
    assert all(set(item["relevant_pmids"]).issubset(pmids) for item in benchmark)


def test_task11_documents_exist_link_correctly_and_cover_the_required_architecture():
    root = Path(__file__).resolve().parents[2]
    required = (
        "architecture.md", "architecture.mmd", "architecture.svg", "evaluation_plan.md",
        "evaluation_report.md", "api_contract.md", "demo_script.md",
    )
    for name in required:
        assert (root / "docs" / name).is_file(), f"missing docs/{name}"

    architecture = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    diagram = (root / "docs" / "architecture.mmd").read_text(encoding="utf-8")
    svg = (root / "docs" / "architecture.svg").read_text(encoding="utf-8")
    for concept in (
        "offline indexing", "query understanding", "research-plan dag", "dense-only", "hybrid",
        "reranked", "agentic", "corrective retrieval", "provenance", "claim repair", "citation validation",
        "administrator", "public",
    ):
        assert concept in architecture.casefold(), concept
    assert "<svg" in svg and 'class="flowchart"' in svg and "Dense-only" in svg
    assert diagram.strip()
    assert "architecture.svg" in architecture

    markdown_files = [root / "README.md", *(root / "docs" / name for name in required if name.endswith(".md"))]
    for markdown_path in markdown_files:
        markdown = markdown_path.read_text(encoding="utf-8")
        for target in __import__("re").findall(r"\[[^\]]*\]\(([^)]+)\)", markdown):
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            local_target = target.split("#", 1)[0]
            if local_target:
                assert (markdown_path.parent / local_target).resolve().is_file(), (markdown_path, target)


def test_task11_promoted_report_is_complete_checksum_valid_and_matches_docs():
    from evaluation.benchmark import stable_checksum
    from evaluation.reporting import validate_report_agreement

    root = Path(__file__).resolve().parents[2]
    benchmark_path = root / "data" / "evaluation" / "benchmark_v2.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    assert len(benchmark["entries"]) == 40
    assert len({entry["id"] for entry in benchmark["entries"]}) == 40
    assert benchmark["corpus_record_count"] == 29994
    index_manifest = json.loads((root / "data" / "manifests" / "index_manifest.json").read_text(encoding="utf-8"))
    assert index_manifest["corpus"]["total_records"] == 29994

    reports = root / "evaluation" / "reports"
    manifest = json.loads((reports / "manifest.json").read_text(encoding="utf-8"))
    run_id = manifest["latest_run_id"]
    run_dir = reports / run_id
    report_path = run_dir / "report.json"
    report_md_path = run_dir / "report.md"
    checksums_path = run_dir / "checksums.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    checksums = json.loads(checksums_path.read_text(encoding="utf-8"))
    assert report["run_id"] == run_id
    assert _sha256(report_path) == checksums["report.json"]
    assert _sha256(report_md_path) == checksums["report.md"]
    assert report["benchmark_checksum"] == _sha256(benchmark_path)
    assert report["corpus_checksum"] == index_manifest["corpus"]["sha256"]
    assert __import__("re").fullmatch(r"[0-9a-f]{64}", report["configuration_checksum"])
    assert report["query_count"] == 40
    assert report["variants"] == ["dense_only", "hybrid", "reranked", "agentic"]
    assert {metric["status"] for metric in report["metrics"].values()} <= {"completed", "not_run", "failed"}
    assert all(
        (metric.get("value") is not None and metric.get("reason") is None)
        if metric["status"] == "completed"
        else (metric.get("value") is None and bool(metric.get("reason")))
        for metric in report["metrics"].values()
    )
    assert len(checksums["queries"]) == 40
    for filename, checksum in checksums["queries"].items():
        assert _sha256(run_dir / "queries" / filename) == checksum
    markdown = report_md_path.read_text(encoding="utf-8")
    validate_report_agreement(report, markdown)
    assert all(f"| {name} | {metric['status']} |" in markdown for name, metric in report["metrics"].items())
    promoted_run = next(item for item in manifest["runs"] if item["run_id"] == run_id)
    assert promoted_run["report_checksum"] == checksums["report.json"]
    assert promoted_run["checksums_checksum"] == stable_checksum(checksums)

    evaluation_doc = (root / "docs" / "evaluation_report.md").read_text(encoding="utf-8")
    for value in (run_id, report["benchmark_checksum"], report["corpus_checksum"], report["configuration_checksum"]):
        assert value in evaluation_doc
    assert "administrator" in evaluation_doc.casefold()
    assert "web-assisted PubMed source verification" in evaluation_doc
    assert "human review" not in evaluation_doc.casefold()
    for variant in report["variants"]:
        for metric_name in ("recall@10", "precision@10", "mrr@10", "ndcg@10", "filter_accuracy"):
            metric = report["metrics"][f"{variant}.{metric_name}"]
            assert str(metric["value"]) in evaluation_doc
        latency = report["metrics"][f"{variant}.latency_ms"]["value"]
        for statistic in ("mean", "median", "max"):
            assert str(latency[statistic]) in evaluation_doc
    for variant in ("dense_only", "hybrid", "reranked"):
        assert report["metrics"][f"{variant}.answer_completeness"] == {
            "status": "not_run", "value": None,
            "reason": "saved artifacts do not contain the required validated reference or claim-level fields",
        }
