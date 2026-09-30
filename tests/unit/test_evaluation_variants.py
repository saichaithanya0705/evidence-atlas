import json
from types import SimpleNamespace

import pytest

from evaluation import variants
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
    base = {"schema_version": "1.0", "benchmark_version": "2.0", "corpus_identity": "sha256:corpus", "query_id": "q", "query": "query text", "expected_route": "SIMPLE", "variant": "dense_only", "configuration_hash": "a" * 64, "metadata_filters": {}, "top_k": 5, "candidate_pmids": [], "candidates": [], "latency_ms": 1.0}
    assert QueryEvaluationArtifact.model_validate(base).query_id == "q"
    with pytest.raises(ValueError):
        QueryEvaluationArtifact.model_validate({**base, "unexpected": True})
    assert configuration_hash({"top_k": 5}) == configuration_hash({"top_k": 5})
    assert configuration_hash({"top_k": 5}) != configuration_hash({"top_k": 6})
    same_config = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus")
    changed_config = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=6, benchmark_version="2.0", corpus_identity="sha256:corpus")
    assert configuration_hash(same_config._configuration()) == configuration_hash(same_config._configuration())
    assert configuration_hash(same_config._configuration()) != configuration_hash(changed_config._configuration())


@pytest.mark.parametrize(
    "setting,changed_value",
    [
        ("RRF_K", 61),
        ("DENSE_TOP_K", 31),
        ("SPARSE_TOP_K", 31),
        ("QDRANT_STORAGE_PATH", "different-vector-store"),
        ("MEDCPT_QUERY_ENCODER", "different-query-model"),
        ("BM25_INDEX_PATH", "different-bm25-index"),
        ("MESH_GRAPH_PATH", "different-graph"),
    ],
)
def test_reranked_hash_tracks_every_material_hybrid_pool_setting(setting, changed_value):
    values = {
        "RRF_K": 60, "DENSE_TOP_K": 30, "SPARSE_TOP_K": 30,
        "MEDCPT_QUERY_ENCODER": "query-model", "BM25_INDEX_PATH": "bm25-index",
        "MESH_GRAPH_PATH": "mesh-graph", "RERANKER_TOP_N": 10,
        "MEDCPT_CROSS_ENCODER": "cross-model",
    }
    before = RerankedVariant(planner=make_plan, retriever=Retriever(), reranker=Reranker(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=SimpleNamespace(**values))
    values[setting] = changed_value
    after = RerankedVariant(planner=make_plan, retriever=Retriever(), reranker=Reranker(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=SimpleNamespace(**values))

    assert configuration_hash(before._configuration()) != configuration_hash(after._configuration())


@pytest.mark.parametrize(
    "setting,changed_value",
    [
        ("NVIDIA_MODEL_NAME", "different-llm"),
        ("LLM_MODE", "openai"),
        ("LLM_TEMPERATURE", 0.7),
        ("LLM_MAX_TOKENS", 4096),
        ("LLM_SYNTHESIS_MAX_TOKENS", 512),
        ("MAX_CORRECTIVE_LOOPS", 3),
        ("DENSE_TOP_K", 31),
        ("SPARSE_TOP_K", 31),
        ("QDRANT_STORAGE_PATH", "different-vector-store"),
        ("NVIDIA_BASE_URL", "https://different-host/v1"),
        ("RRF_K", 61),
        ("BM25_INDEX_PATH", "different-bm25-index"),
        ("MESH_GRAPH_PATH", "different-graph"),
    ],
)
def test_agentic_hash_tracks_material_workflow_and_retrieval_settings(setting, changed_value):
    values = {
        "NVIDIA_MODEL_NAME": "llm-model", "NVIDIA_BASE_URL": "https://user:password@host/v1?api_key=secret-one",
        "LLM_MODE": "mock", "LLM_TEMPERATURE": 0.1,
        "LLM_MAX_TOKENS": 2048, "LLM_SYNTHESIS_MAX_TOKENS": 300,
        "MAX_CORRECTIVE_LOOPS": 2, "DENSE_TOP_K": 30, "SPARSE_TOP_K": 30,
        "RRF_K": 60, "BM25_INDEX_PATH": "bm25-index", "MESH_GRAPH_PATH": "mesh-graph",
        "MAX_SUBQUERIES": 4, "RERANKER_TOP_N": 10,
        "MEDCPT_QUERY_ENCODER": "query-model", "MEDCPT_CROSS_ENCODER": "cross-model",
    }
    before = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=SimpleNamespace(**values))
    values[setting] = changed_value
    after = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=SimpleNamespace(**values))

    assert configuration_hash(before._configuration()) != configuration_hash(after._configuration())


def test_configuration_hash_ignores_nonmaterial_settings_and_secret_values():
    material = {"NVIDIA_MODEL_NAME": "model-a", "NVIDIA_BASE_URL": "https://user:password@host/v1?api_key=secret-one", "LLM_MODE": "mock", "RRF_K": 60, "NVIDIA_API_KEY": "secret-one", "LOG_LEVEL": "INFO"}
    before = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=SimpleNamespace(**material))
    material["NVIDIA_API_KEY"] = "secret-two"
    material["NVIDIA_BASE_URL"] = "https://another-user:another-password@host/v1?api_key=secret-two"
    material["LOG_LEVEL"] = "DEBUG"
    after = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=SimpleNamespace(**material))

    assert configuration_hash(before._configuration()) == configuration_hash(after._configuration())
    serialized = json.dumps(before._configuration())
    assert "secret-" not in serialized
    assert "password" not in serialized
    assert "another-user" not in serialized


@pytest.mark.parametrize("variant_name", ["dense_only", "hybrid", "reranked", "agentic"])
def test_model_cache_directory_changes_every_variant_hash(variant_name):
    settings = SimpleNamespace(MODELS_CACHE_DIR="cache-a")
    variants = {
        "dense_only": lambda: DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings),
        "hybrid": lambda: HybridVariant(planner=make_plan, retriever=Retriever(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings),
        "reranked": lambda: RerankedVariant(planner=make_plan, retriever=Retriever(), reranker=Reranker(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings),
        "agentic": lambda: AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings),
    }
    before = variants[variant_name]()
    before_hash = configuration_hash(before._configuration())
    settings.MODELS_CACHE_DIR = "cache-b"
    after = variants[variant_name]()

    assert before_hash != configuration_hash(after._configuration())


def test_resume_reruns_when_model_cache_directory_changes(tmp_path):
    settings = SimpleNamespace(MODELS_CACHE_DIR="cache-a")
    variant = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    output = tmp_path / "model-cache-resume"
    run_evaluation([entry()], {"dense_only": variant}, output_dir=output)
    settings.MODELS_CACHE_DIR = "cache-b"

    result = run_evaluation([entry()], {"dense_only": variant}, output_dir=output, resume=True)

    assert result == {"written": 1, "skipped": 0}


def test_endpoint_path_credentials_are_redacted_and_do_not_affect_hash():
    settings = SimpleNamespace(NVIDIA_BASE_URL="https://api.example.test/v1/chat/completions/secret-path-credential-abc123")
    before = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    before_config = before._configuration()
    before_hash = configuration_hash(before_config)
    settings.NVIDIA_BASE_URL = "https://api.example.test/v1/chat/completions/different-path-credential-xyz987"
    after = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    serialized = json.dumps(before_config)

    assert before_hash == configuration_hash(after._configuration())
    assert "secret-path-credential-abc123" not in serialized
    assert "v1" in serialized and "chat" in serialized and "completions" in serialized


def test_endpoint_static_path_change_remains_material():
    settings = SimpleNamespace(NVIDIA_BASE_URL="https://api.example.test/v1/chat/completions")
    chat = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    chat_hash = configuration_hash(chat._configuration())
    settings.NVIDIA_BASE_URL = "https://api.example.test/v1/embeddings"
    embeddings = AgenticVariant(service=object(), top_k=5, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)

    assert chat_hash != configuration_hash(embeddings._configuration())


@pytest.mark.parametrize(
    "change",
    [
        lambda original: original.model_copy(update={"study_type": "Observational"}),
        lambda original: original.model_copy(update={"query": "Updated query with same ID"}),
        lambda original: original.model_copy(update={"expected_route": "COMPLEX"}),
    ],
    ids=["filters", "query-text", "expected-route"],
)
def test_resume_reruns_when_query_or_metadata_filters_change(tmp_path, change):
    variant = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus")
    output = tmp_path / "resume-identity"
    original = entry()
    assert run_evaluation([original], {"dense_only": variant}, output_dir=output)["written"] == 1

    changed = change(original)
    result = run_evaluation([changed], {"dense_only": variant}, output_dir=output, resume=True)

    assert result == {"written": 1, "skipped": 0}
    saved = json.loads((output / "dense_only" / f"{original.id}.json").read_text(encoding="utf-8"))
    assert saved["query"] == changed.query
    assert saved["expected_route"] == changed.expected_route
    assert saved["metadata_filters"] == {"study_types": [changed.study_type]}


def test_resume_reruns_when_stored_top_k_or_configuration_is_stale(tmp_path):
    variant = DenseOnlyVariant(planner=make_plan, retriever=Retriever(), top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus")
    output = tmp_path / "resume-top-k"
    current = entry()
    run_evaluation([current], {"dense_only": variant}, output_dir=output)
    target = output / "dense_only" / f"{current.id}.json"
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["top_k"] = 4
    target.write_text(json.dumps(payload), encoding="utf-8")

    result = run_evaluation([current], {"dense_only": variant}, output_dir=output, resume=True)

    assert result == {"written": 1, "skipped": 0}
    assert json.loads(target.read_text(encoding="utf-8"))["top_k"] == 3


def test_resume_reruns_for_changed_reranked_pool_configuration(tmp_path):
    settings = SimpleNamespace(
        DENSE_TOP_K=10, SPARSE_TOP_K=10, RRF_K=60, MAX_SUBQUERIES=4,
        RERANKER_TOP_N=5, MEDCPT_QUERY_ENCODER="query-model",
        MEDCPT_CROSS_ENCODER="cross-model", BM25_INDEX_PATH="bm25-a",
        MESH_GRAPH_PATH="mesh-a",
    )
    variant = RerankedVariant(planner=make_plan, retriever=Retriever(), reranker=Reranker(), top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    output = tmp_path / "reranked-config"
    run_evaluation([entry()], {"reranked": variant}, output_dir=output)
    settings.RRF_K = 61

    result = run_evaluation([entry()], {"reranked": variant}, output_dir=output, resume=True)

    assert result == {"written": 1, "skipped": 0}


def test_resume_reruns_for_changed_agentic_llm_configuration(tmp_path):
    response = SimpleNamespace(
        request_id="request-1", model_dump=lambda **kwargs: {"synthesis": "Answer"},
        research_plan={"subquestions": []}, coverage_statuses={"sq-1": "covered"},
        retrieved_papers=[], evidence_table=[], cited_pmids=[],
    )
    service = SimpleNamespace(
        research=lambda query, user_filters, max_loops, route_floor: response,
        get_trace=lambda request_id: {"research_plan": {"subquestions": []}, "coverage_history": [{"covered": True}], "corrective_queries": []},
    )
    settings = SimpleNamespace(LLM_MODE="mock", NVIDIA_MODEL_NAME="model-a", LLM_TEMPERATURE=0.1)
    variant = AgenticVariant(service=service, top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    output = tmp_path / "agentic-config"
    run_evaluation([entry()], {"agentic": variant}, output_dir=output)
    settings.LLM_TEMPERATURE = 0.7

    result = run_evaluation([entry()], {"agentic": variant}, output_dir=output, resume=True)

    assert result == {"written": 1, "skipped": 0}


def test_resume_skips_when_only_secret_or_nonmaterial_setting_changes(tmp_path):
    response = SimpleNamespace(
        request_id="request-1", model_dump=lambda **kwargs: {"synthesis": "Answer"},
        research_plan={"subquestions": []}, coverage_statuses={"sq-1": "covered"},
        retrieved_papers=[], evidence_table=[], cited_pmids=[],
    )
    calls = []
    service = SimpleNamespace(
        research=lambda query, user_filters, max_loops, route_floor: calls.append(query) or response,
        get_trace=lambda request_id: {"research_plan": {"subquestions": []}, "coverage_history": [{"covered": True}], "corrective_queries": []},
    )
    settings = SimpleNamespace(LLM_MODE="mock", NVIDIA_MODEL_NAME="model-a", LLM_TEMPERATURE=0.1, NVIDIA_API_KEY="secret-one", LOG_LEVEL="INFO")
    variant = AgenticVariant(service=service, top_k=3, benchmark_version="2.0", corpus_identity="sha256:corpus", settings=settings)
    output = tmp_path / "agentic-nonmaterial"
    run_evaluation([entry()], {"agentic": variant}, output_dir=output)
    settings.NVIDIA_API_KEY = "secret-two"
    settings.LOG_LEVEL = "DEBUG"

    result = run_evaluation([entry()], {"agentic": variant}, output_dir=output, resume=True)

    assert result == {"written": 0, "skipped": 1}
    assert calls == [entry().query]


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


def test_atomic_write_retries_transient_replace_permission_error(tmp_path, monkeypatch):
    real_replace = variants.os.replace
    attempts = []

    def replace_with_transient_denial(source, target):
        attempts.append((source, target))
        if len(attempts) == 1:
            raise PermissionError("transient file scanner lock")
        return real_replace(source, target)

    monkeypatch.setattr(variants.os, "replace", replace_with_transient_denial)
    path = tmp_path / "atomic-retry.json"

    write_artifact_atomic(path, {"written": True})

    assert len(attempts) == 2
    assert json.loads(path.read_text(encoding="utf-8")) == {"written": True}
