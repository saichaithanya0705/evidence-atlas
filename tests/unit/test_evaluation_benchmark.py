"""Contracts for the frozen, source-linked biomedical benchmark."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest


def _models():
    from evaluation.models import BenchmarkDataset

    return BenchmarkDataset


def _entry(index: int = 1, *, pmid: str = "100", grade: int = 3, **updates):
    from evaluation.models import BenchmarkEntry

    payload = {
        "id": f"q{index}",
        "query": f"query {index}",
        "category": "nephrology",
        "expected_route": "SIMPLE",
        "study_type": "randomized controlled trial",
        "relevant_pmids": [pmid] if grade > 0 else [],
        "judgments": [{
            "pmid": pmid,
            "title": "Verified title",
            "title_match": True,
            "relevance": grade,
            "rationale": "The record directly reports the query outcome in the target population.",
            "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "adjudicated_on": "2026-09-29",
        }],
    }
    payload.update(updates)
    return BenchmarkEntry.model_validate(payload)


def _dataset(entries=None):
    BenchmarkDataset = _models()
    return BenchmarkDataset.model_validate({
        "version": "2.0",
        "corpus_path": "data/processed/cleaned_pubmed.parquet",
        "corpus_record_count": 29994,
        "entries": list(entries if entries is not None else [_entry()]),
    })


def test_dataset_contract_accepts_30_to_50_entries_and_benchmark_has_exactly_40():
    from evaluation.benchmark import validate_benchmark

    for count in (30, 40, 50):
        routes = ["SIMPLE", "MODERATE", "COMPLEX"]
        categories = ["nephrology", "cardiology", "endocrinology", "transplant"]
        study_types = ["trial", "cohort", "systematic review"]
        entries = [
            _entry(
                i + 1,
                pmid=str(100 + i),
                expected_route=routes[i % len(routes)],
                category=categories[i % len(categories)],
                study_type=study_types[i % len(study_types)],
            )
            for i in range(count)
        ]
        report = validate_benchmark(_dataset(entries), {str(100 + i) for i in range(count)})
        assert report.query_count == count
        assert report.valid

    benchmark = Path("data/evaluation/benchmark_v2.json")
    assert len(json.loads(benchmark.read_text(encoding="utf-8"))["entries"]) == 40


def test_entry_ids_must_be_unique():
    from evaluation.benchmark import validate_benchmark

    dataset = _dataset([_entry(1, pmid="100"), _entry(1, pmid="101")])
    with pytest.raises(ValueError, match="unique"):
        validate_benchmark(dataset, {"100", "101"})


def test_benchmark_covers_all_routes_and_multiple_categories_and_study_types():
    from evaluation.benchmark import validate_benchmark

    entries = [
        _entry(1, pmid="100", expected_route="SIMPLE", category="nephrology", study_type="cohort"),
        _entry(2, pmid="101", expected_route="MODERATE", category="cardiology", study_type="trial"),
        _entry(3, pmid="102", expected_route="COMPLEX", category="endocrinology", study_type="systematic review"),
    ]
    report = validate_benchmark(_dataset(entries), {"100", "101", "102"}, enforce_size=False)
    assert report.routes == {"SIMPLE", "MODERATE", "COMPLEX"}
    assert len(report.categories) >= 3
    assert len(report.study_types) >= 3


def test_relevance_is_graded_and_references_are_derived_consistently():
    entry = _entry(grade=2)
    assert entry.relevant_pmids == ["100"]
    assert entry.judgments[0].relevance == 2
    with pytest.raises(ValueError):
        _entry(relevant_pmids=["999"])
    with pytest.raises(ValueError):
        _entry(grade=4)


def test_validation_rejects_relevant_pmids_outside_active_corpus():
    from evaluation.benchmark import validate_benchmark

    report = validate_benchmark(_dataset(), {"other"}, enforce_size=False)
    assert not report.valid
    assert report.corpus_id_mismatches == ["100"]


def test_every_judgment_requires_a_source_url_and_direct_title_match():
    from evaluation.models import RelevanceJudgment

    with pytest.raises(ValueError):
        RelevanceJudgment.model_validate({
            "pmid": "100", "title": "x", "title_match": False, "relevance": 1,
            "rationale": "Evidence supports this query's topic and target population.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/100/",
            "adjudicated_on": "2026-09-29",
        })
    with pytest.raises(ValueError, match="PMID"):
        RelevanceJudgment.model_validate({
            "pmid": "100", "title": "x", "title_match": True, "relevance": 1,
            "rationale": "Evidence directly describes the topic and population.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/101/", "adjudicated_on": "2026-09-29",
        })
    with pytest.raises(ValueError):
        RelevanceJudgment.model_validate({
            "pmid": "100", "title": "x", "title_match": True, "relevance": 1,
            "rationale": "Evidence", "source_url": "not-a-url", "adjudicated_on": "2026-09-29",
        })


def test_checksum_is_stable_for_equivalent_json_values():
    from evaluation.benchmark import stable_checksum

    assert stable_checksum({"b": 2, "a": 1}) == stable_checksum({"a": 1, "b": 2})
    assert stable_checksum({"a": 1}) == hashlib.sha256(b'{"a":1}').hexdigest()


def test_client_rate_limit_depends_only_on_api_key_presence():
    from evaluation.adjudication import PubMedClient

    assert PubMedClient(api_key=None, transport=lambda *_: None).requests_per_second == 3
    assert PubMedClient(api_key="secret", transport=lambda *_: None).requests_per_second == 10


def test_efetch_uses_required_tool_and_only_includes_contact_when_supplied(tmp_path):
    from evaluation.adjudication import PubMedClient

    default_client = PubMedClient(cache_dir=tmp_path, transport=lambda *_: "", sleep=lambda _: None)
    params = default_client._params(["100"])
    assert params["tool"] == "EvidenceAtlas"
    assert params["rettype"] == "abstract"
    assert "email" not in params

    configured = PubMedClient(api_key="secret", email="contact@example.org", cache_dir=tmp_path, transport=lambda *_: "", sleep=lambda _: None)
    assert configured._params(["100"])["email"] == "contact@example.org"


def test_cached_fetch_avoids_a_second_network_request(tmp_path):
    from evaluation.adjudication import PubMedClient

    calls = []
    def transport(url, params, timeout):
        calls.append(params["id"])
        return "<PubmedArticleSet><PubmedArticle><PMID>100</PMID><ArticleTitle>Verified title</ArticleTitle></PubmedArticle></PubmedArticleSet>"

    client = PubMedClient(cache_dir=tmp_path, transport=transport, sleep=lambda _: None)
    first = client.fetch_records(["100"])
    second = client.fetch_records(["100"])
    assert first == second
    assert len(calls) == 1


def test_efetch_requests_are_batched_at_100_ids(tmp_path):
    from evaluation.adjudication import PubMedClient

    batch_sizes = []
    def transport(url, params, timeout):
        pmids = params["id"].split(",")
        batch_sizes.append(len(pmids))
        return "<PubmedArticleSet>" + "".join(f"<PubmedArticle><PMID>{pmid}</PMID><ArticleTitle>Title {pmid}</ArticleTitle></PubmedArticle>" for pmid in pmids) + "</PubmedArticleSet>"

    PubMedClient(cache_dir=tmp_path, transport=transport, sleep=lambda _: None).fetch_records([str(i) for i in range(205)])
    assert batch_sizes == [100, 100, 5]


def test_title_mismatch_is_reported_as_unverified_label():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(_dataset(), {"100": "Different title"})
    assert result.unverified_labels == 1
    assert result.label_status["q1:100"] == "title_mismatch"


def test_missing_pubmed_record_is_reported_as_unverified_label():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(_dataset(), {})
    assert result.unverified_labels == 1
    assert result.label_status["q1:100"] == "missing_source_verification_evidence"


def _source_verification(*, source_title="Verified title", source_url="https://pubmed.ncbi.nlm.nih.gov/100/"):
    return {
        "q1:100": {
            "pmid": "100",
            "source_title": source_title,
            "method": "official_pubmed_page_title_check",
            "checked_at": "2026-09-30T00:00:00+00:00",
            "source_url": source_url,
        }
    }


def test_efetch_failure_cannot_verify_from_forged_direct_title_match_alone():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(_dataset(), {}, {"100"})
    assert result.verified_labels == 0
    assert result.unverified_labels == 1
    assert result.web_source_verified_labels == 0
    assert result.label_status["q1:100"] == "missing_source_verification_evidence"


def test_efetch_failure_with_absent_source_verification_evidence_is_unverified():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(_dataset(), {}, {"100"}, corpus_titles={"100": "Verified title"})
    assert result.verified_labels == 0
    assert result.label_status["q1:100"] == "missing_source_verification_evidence"


def test_efetch_failure_rejects_source_url_for_a_different_pmid():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(
        _dataset(), {}, {"100"}, source_verification=_source_verification(source_url="https://pubmed.ncbi.nlm.nih.gov/101/"),
        corpus_titles={"100": "Verified title"},
    )
    assert result.verified_labels == 0
    assert result.label_status["q1:100"] == "source_url_pmid_mismatch"


def test_efetch_failure_rejects_source_title_mismatch():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(
        _dataset(), {}, {"100"}, source_verification=_source_verification(source_title="A forged title"),
        corpus_titles={"100": "Verified title"},
    )
    assert result.verified_labels == 0
    assert result.label_status["q1:100"] == "source_title_mismatch"


def test_efetch_failure_requires_corpus_title_to_match_source_and_benchmark():
    from evaluation.adjudication import adjudicate_records

    result = adjudicate_records(
        _dataset(), {}, {"100"}, source_verification=_source_verification(),
        corpus_titles={"100": "Different local title"},
    )
    assert result.verified_labels == 0
    assert result.label_status["q1:100"] == "corpus_title_mismatch"


def test_source_verification_artifact_checksum_and_schema_are_required(tmp_path):
    from evaluation.adjudication import load_source_verification
    from evaluation.benchmark import stable_checksum

    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(json.dumps(_dataset([_entry()]).model_dump(mode="json")), encoding="utf-8")
    payload = {
        "version": "1.0",
        "benchmark_checksum": hashlib.sha256(benchmark_path.read_bytes()).hexdigest(),
        "records": [{
            "entry_id": "q1", "pmid": "100", "source_title": "Verified title",
            "method": "official_pubmed_page_title_check", "checked_at": "2026-09-30T00:00:00+00:00",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/100/",
        }],
    }
    payload["verification_checksum"] = stable_checksum(payload)
    artifact_path = tmp_path / "verification.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_source_verification(artifact_path, benchmark_path)["q1:100"]["source_title"] == "Verified title"

    payload["benchmark_checksum"] = "0" * 64
    payload["verification_checksum"] = stable_checksum({key: value for key, value in payload.items() if key != "verification_checksum"})
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        load_source_verification(artifact_path, benchmark_path)

    payload["benchmark_checksum"] = hashlib.sha256(benchmark_path.read_bytes()).hexdigest()
    payload["records"][0]["source_title"] = "Tampered after checksum"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact checksum"):
        load_source_verification(artifact_path, benchmark_path)


def test_partial_network_failures_retry_only_with_a_bounded_attempt_count(tmp_path):
    from evaluation.adjudication import PubMedClient

    calls = []
    def transport(url, params, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise OSError("temporary failure")
        return "<PubmedArticleSet><PubmedArticle><PMID>100</PMID><ArticleTitle>Verified title</ArticleTitle></PubmedArticle></PubmedArticleSet>"

    client = PubMedClient(cache_dir=tmp_path, transport=transport, retries=2, sleep=lambda _: None)
    assert "100" in client.fetch_records(["100"])
    assert len(calls) == 3


def test_retry_exhaustion_reports_a_partial_fetch_without_unbounded_loop(tmp_path):
    from evaluation.adjudication import PubMedClient

    calls = []
    def transport(url, params, timeout):
        calls.append(1)
        raise OSError("offline")

    client = PubMedClient(cache_dir=tmp_path, transport=transport, retries=1, sleep=lambda _: None)
    result = client.fetch_records_partial(["100"])
    assert result.records == {}
    assert result.failed_pmids == ["100"]
    assert len(calls) == 2


def test_validation_file_is_written_atomically(tmp_path, monkeypatch):
    from evaluation.adjudication import atomic_write_json

    output = tmp_path / "report.json"
    atomic_write_json(output, {"ok": True})
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}
    assert list(tmp_path.iterdir()) == [output]


def test_load_benchmark_preserves_typed_relevance_fields(tmp_path):
    from evaluation.benchmark import load_benchmark

    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(_dataset([_entry()]).model_dump(mode="json")), encoding="utf-8")
    loaded = load_benchmark(path)
    assert loaded.entries[0].judgments[0].adjudicated_on == date(2026, 9, 29)
