import json
from types import SimpleNamespace

import pytest

from evaluation.models import BenchmarkEntry
from evaluation.variants import (
    AgenticVariant,
    DenseOnlyVariant,
    HybridVariant,
    QueryEvaluationArtifact,
    RerankedVariant,
    configuration_hash,
    run_evaluation,
    write_artifact_atomic,
)
from backend.app.query.models import QueryPlan
from backend.app.retrieval.hybrid import HybridRetriever


def entry():
    return BenchmarkEntry.model_validate({
        "id": "query-1",
        "query": "Does treatment affect kidney outcomes?",
        "category": "nephrology",
        "expected_route": "MODERATE",
        "study_type": "Randomized Controlled Trial",
        "relevant_pmids": ["123"],
        "judgments": [{
            "pmid": "123", "title": "Kidney outcomes with treatment",
            "title_match": True, "relevance": 2,
            "rationale": "Directly reports the kidney outcome for the treatment.",
            "source_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
            "adjudicated_on": "2026-09-30",
        }],
    })


class Retriever:
    def __init__(self):
        self.calls = []
        self.last_trace = {"candidate_pmids": ["123", "456"]}

    def search_channels(self, plan, *, channels, top_k):
        self.calls.append((plan, tuple(channels), top_k))
        return [SimpleNamespace(pmid="123", model_dump=lambda **kwargs: {"pmid": "123", "reranker_score": None})]


class Reranker:
    def __init__(self):
        self.pool = None

    def rerank(self, query, candidates, *, top_n):
        self.pool = candidates
        return candidates, {"enabled": True}


class OriginalQueryEncoder:
    def __init__(self):
        self.queries = []

    def encode_queries(self, queries):
        self.queries.extend(queries)
        return [[1.0, 0.0] for _ in queries]


class FilterRecordingQdrant:
    def __init__(self):
        self.filters = []

    def search_dense(self, vector, limit, **filters):
        self.filters.append(filters)
        return [{"pmid": "123", "score": .9}, {"pmid": "456", "score": .8}]


def make_plan(query, filters, route_override=None):
    return SimpleNamespace(original_query=query, canonical_query=query, subqueries=["expanded query"], route="MODERATE", filters=filters)


def test_dense_only_production_channel_embeds_original_query_and_applies_study_filter():
    entry_data = entry()
    encoder, qdrant = OriginalQueryEncoder(), FilterRecordingQdrant()
    retriever = HybridRetriever(
        settings=SimpleNamespace(DENSE_TOP_K=10, SPARSE_TOP_K=10, RRF_K=60, MAX_SUBQUERIES=4),
        qdrant_service=qdrant,
        records=[
            {"pmid": "123", "title": "A", "year": 2023, "study_type": "Randomized Controlled Trial"},
            {"pmid": "456", "title": "B", "year": 2023, "study_type": "Observational"},
        ],
        query_encoder=encoder,
    )
    plan = QueryPlan(
        original_query=entry_data.query, clean_query=entry_data.query,
        canonical_query="expanded canonical version", route="MODERATE",
        study_type_filters=[entry_data.study_type], subqueries=["another expanded query"],
    )

    candidates = retriever.search_channels(plan, channels=("dense_original",), top_k=5)

    assert encoder.queries == [entry_data.query]
    assert qdrant.filters == [{"year_min": None, "year_max": None, "study_types": ["Randomized Controlled Trial"], "mesh_terms": []}]
    assert [candidate.pmid for candidate in candidates] == ["123"]


def test_dense_only_uses_only_original_dense_channel_and_entry_hard_filter():
    retriever = Retriever()
    variant = DenseOnlyVariant(
        planner=make_plan, retriever=retriever, top_k=7,
        benchmark_version="2.0", corpus_identity="sha256:corpus",
    )

    artifact = variant.run(entry())

    assert retriever.calls[0][1] == ("dense_original",)
    assert retriever.calls[0][2] == 7
    assert retriever.calls[0][0].filters == {"study_types": ["Randomized Controlled Trial"]}
    assert artifact.variant == "dense_only"
    assert artifact.metadata_filters == {"study_types": ["Randomized Controlled Trial"]}


def test_hybrid_has_no_cross_encoder_result_and_reranked_pool_is_identical():
    hybrid_retriever, rerank_retriever = Retriever(), Retriever()
    hybrid = HybridVariant(planner=make_plan, retriever=hybrid_retriever, top_k=7, benchmark_version="2.0", corpus_identity="sha256:corpus")
    reranker = Reranker()
    reranked = RerankedVariant(planner=make_plan, retriever=rerank_retriever, reranker=reranker, top_k=7, benchmark_version="2.0", corpus_identity="sha256:corpus")

    hybrid_artifact = hybrid.run(entry())
    reranked_artifact = reranked.run(entry())

    assert "reranker" not in hybrid_artifact.model_dump()
    assert rerank_retriever.calls[-1][1:] == hybrid_retriever.calls[-1][1:]
    assert [item.pmid for item in reranker.pool] == [item.pmid for item in hybrid_retriever.search_channels(make_plan("", {}, None), channels=("dense_original", "dense_canonical", "bm25", "mesh_graph"), top_k=7)]
    assert reranked_artifact.hybrid_candidate_pool_pmids == hybrid_artifact.candidate_pmids
    assert [item.pmid for item in reranker.pool] == reranked_artifact.hybrid_candidate_pool_pmids


def test_agentic_artifact_records_production_trace_plan_coverage_and_answer():
    response = SimpleNamespace(request_id="request-1", model_dump=lambda **kwargs: {"synthesis": "Answer", "cited_pmids": ["123"]}, research_plan={"subquestions": []}, coverage_statuses={"sq-1": "covered"}, retrieved_papers=[], evidence_table=[], cited_pmids=["123"])
    service = SimpleNamespace(
        research=lambda query, user_filters, max_loops, route_floor: response,
        get_trace=lambda request_id: {"research_plan": {"subquestions": []}, "coverage_history": [{"covered": True}], "corrective_queries": [], "timings_ms": {"total": 4}},
    )

    artifact = AgenticVariant(service=service, top_k=7, benchmark_version="2.0", corpus_identity="sha256:corpus").run(entry())

    assert artifact.research_plan == {"subquestions": []}
    assert artifact.coverage
    assert artifact.answer["synthesis"] == "Answer"
    assert artifact.citations == ["123"]
    assert artifact.latency_ms >= 0


def test_artifacts_share_strict_schema_and_configuration_hash_tracks_material_settings():
    base = {"schema_version": "1.0", "benchmark_version": "2.0", "corpus_identity": "sha256:corpus", "query_id": "q", "variant": "dense_only", "configuration_hash": "a" * 64, "metadata_filters": {}, "top_k": 5, "candidate_pmids": [], "candidates": [], "latency_ms": 1.0}
    assert QueryEvaluationArtifact.model_validate(base).query_id == "q"
    with pytest.raises(ValueError):
        QueryEvaluationArtifact.model_validate({**base, "unexpected": True})
    assert configuration_hash({"top_k": 5}) == configuration_hash({"top_k": 5})
    assert configuration_hash({"top_k": 5}) != configuration_hash({"top_k": 6})
    same_config = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus")
    changed_config = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=6, benchmark_version="2.0", corpus_identity="sha256:corpus")
    assert configuration_hash(same_config._configuration()) == configuration_hash(same_config._configuration())
    assert configuration_hash(same_config._configuration()) != configuration_hash(changed_config._configuration())


def test_atomic_write_and_resume_preserve_valid_artifacts_and_repair_malformed(tmp_path):
    retriever = Retriever()
    variant = DenseOnlyVariant(planner=make_plan, retriever=retriever, top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus")
    output = tmp_path / "out"
    target = output / "dense_only" / "query-1.json"
    target.parent.mkdir(parents=True)
    target.write_text("{broken", encoding="utf-8")
    result = run_evaluation([entry()], {"dense_only": variant}, output_dir=output, resume=True)
    assert result["written"] == 1
    assert json.loads(target.read_text(encoding="utf-8"))["query_id"] == "query-1"
    valid = target.read_bytes()
    result = run_evaluation([entry()], {"dense_only": variant}, output_dir=output, resume=True)
    assert result["skipped"] == 1
    assert target.read_bytes() == valid
    assert list(output.rglob("*.tmp")) == []

    atomic_path = tmp_path / "atomic" / "artifact.json"
    write_artifact_atomic(atomic_path, {"query_id": "q", "ok": True})
    assert json.loads(atomic_path.read_text(encoding="utf-8")) == {"query_id": "q", "ok": True}
    assert sorted(item.name for item in atomic_path.parent.iterdir()) == ["artifact.json"]
