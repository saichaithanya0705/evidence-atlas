from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.evidence.extraction import EvidenceExtractor
from backend.app.models.request_response import RetrievalCandidate
from backend.app.query.models import PICOModel, QueryPlan
from backend.app.retrieval.hybrid import HybridRetriever, reciprocal_rank_fusion
from backend.app.retrieval.reranker import MedCPTReranker
from backend.app.workflow.judge import EvidenceGrade
from backend.app.workflow.service import ResearchService
from backend.app.workflow.synthesis import EvidenceSynthesizer


def make_plan(**kwargs):
    values = {
        "original_query": "Empagliflozin in type 2 diabetes and chronic kidney disease",
        "clean_query": "Empagliflozin in type 2 diabetes and chronic kidney disease",
        "canonical_query": "Empagliflozin for type 2 diabetes and chronic kidney disease",
        "mesh_terms": ["Diabetes Mellitus, Type 2"],
        "concepts": ["empagliflozin", "type 2 diabetes", "chronic kidney disease"],
        "route": "SIMPLE",
    }
    values.update(kwargs)
    return QueryPlan(**values)


def make_candidate(pmid="35100001", abstract=None):
    return RetrievalCandidate(
        pmid=pmid,
        title="Empagliflozin in diabetes and kidney disease",
        abstract=abstract or (
            "Conclusions: Among patients with type 2 diabetes and chronic kidney disease, "
            "empagliflozin reduced progression of kidney disease compared with placebo."
        ),
        year=2023,
        study_type="Randomized Controlled Trial",
        mesh_terms=["Diabetes Mellitus, Type 2"],
        rrf_score=0.04,
    )


class FakeEncoder:
    def encode_queries(self, queries):
        return np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)


class FakeQdrant:
    def search_dense(self, vector, limit, **filters):
        pmids = ["35100001", "35100002"] if vector[0] else ["35100002", "35100001"]
        records = [
            {"pmid": pmid, "score": 0.9 - index / 10, "payload": {}}
            for index, pmid in enumerate(pmids)
        ]
        return records


class FakeBM25:
    def search(self, query, top_k):
        return [(35100001, 8.0), (35100002, 4.0), (35100003, 2.0)]


def test_rrf_deduplicates_within_channel_and_combines_ranks():
    scores = reciprocal_rank_fusion(
        {"dense_original": ["1", "1", "2"], "bm25": ["2", "1"]}, k=60
    )
    assert scores["1"] == pytest.approx(1 / 61 + 1 / 62)
    # The duplicate occupies its original rank slot, while only its first
    # occurrence contributes a score in that channel.
    assert scores["2"] == pytest.approx(1 / 63 + 1 / 61)


def test_hybrid_retrieval_applies_hard_filters_and_preserves_channel_provenance():
    records = [
        {"pmid": "35100001", "title": "A", "abstract": "diabetes kidney", "year": 2023, "study_type": "Randomized Controlled Trial", "mesh_terms": []},
        {"pmid": "35100002", "title": "B", "abstract": "diabetes kidney", "year": 2024, "study_type": "Randomized Controlled Trial", "mesh_terms": []},
        {"pmid": "35100003", "title": "C", "abstract": "diabetes kidney", "year": 2020, "study_type": "Randomized Controlled Trial", "mesh_terms": []},
    ]
    settings = SimpleNamespace(DENSE_TOP_K=10, SPARSE_TOP_K=10, RRF_K=60, MAX_SUBQUERIES=4)
    retriever = HybridRetriever(
        settings=settings,
        qdrant_service=FakeQdrant(),
        bm25_index=FakeBM25(),
        records=records,
        query_encoder=FakeEncoder(),
    )
    plan = make_plan(year_min=2022, study_type_filters=["Randomized Controlled Trial"])
    results = retriever.search(plan, top_k=10)
    assert {item.pmid for item in results} == {"35100001", "35100002"}
    assert all(item.filter_satisfied for item in results)
    assert results[0].channel_ranks
    assert "dense_original" in results[0].channel_ranks
    assert "bm25" in results[0].channel_ranks


class FakeGraph:
    def expand_query_mesh_terms(self, terms, top_k=5):
        return list(terms) + ["Kidney Diseases"]

    def get_papers_for_mesh(self, term):
        return ["35100003"] if term == "Kidney Diseases" else []


def test_moderate_route_adds_graph_candidates_with_meSH_provenance():
    records = [
        {"pmid": "35100001", "title": "A", "abstract": "diabetes kidney", "year": 2023, "study_type": "Randomized Controlled Trial", "mesh_terms": []},
        {"pmid": "35100002", "title": "B", "abstract": "diabetes kidney", "year": 2024, "study_type": "Randomized Controlled Trial", "mesh_terms": []},
        {"pmid": "35100003", "title": "C", "abstract": "kidney disease", "year": 2023, "study_type": "Observational", "mesh_terms": ["Kidney Diseases"]},
    ]
    settings = SimpleNamespace(DENSE_TOP_K=10, SPARSE_TOP_K=10, RRF_K=60, MAX_SUBQUERIES=4)
    retriever = HybridRetriever(
        settings=settings,
        qdrant_service=FakeQdrant(),
        bm25_index=FakeBM25(),
        records=records,
        graph_retriever=FakeGraph(),
        query_encoder=FakeEncoder(),
    )
    results = retriever.search(make_plan(route="MODERATE"), top_k=10)
    graph_candidate = next(item for item in results if item.pmid == "35100003")
    assert graph_candidate.channel_ranks["mesh_graph"] == 1
    assert graph_candidate.graph_path == [
        "query:Diabetes Mellitus, Type 2",
        "mesh:Kidney Diseases",
        "paper:35100003",
    ]


def test_evidence_extractor_keeps_exact_spans_and_does_not_infer_pico_fields():
    abstract = (
        "Methods: Patients received background care. "
        "Results: Among patients with type 2 diabetes and chronic kidney disease, "
        "empagliflozin reduced kidney disease progression (hazard ratio, 0.72). "
        "Limitations: Follow-up was limited to two years."
    )
    plan = make_plan(pico=PICOModel(population="adults with heart failure", intervention="metformin"))
    evidence = EvidenceExtractor().extract(make_candidate(abstract=abstract), plan)
    assert evidence.supporting_text_spans
    assert all(span in abstract for span in evidence.supporting_text_spans)
    assert evidence.population is None
    assert evidence.intervention is None


class FakeQueryAnalysis:
    def build_query_plan(self, raw_query, user_filters=None, generate_embeddings=False):
        plan = make_plan(original_query=raw_query, clean_query=raw_query, canonical_query=raw_query)
        return plan, None


class FakeHybrid:
    last_trace = {"channels": {"bm25": {"accepted": 1}}}

    def search(self, plan, top_k):
        return [make_candidate()]

    def close(self):
        pass


class FakeReranker:
    def rerank(self, query, candidates, top_n=None):
        for item in candidates[:top_n]:
            item.reranker_score = 0.9
            item.reranker_mode = "medcpt"
        return list(candidates), {"mode": "medcpt", "reranked_count": min(len(candidates), top_n or len(candidates))}


class AlwaysPartialJudge:
    def judge(self, plan, candidates):
        return EvidenceGrade(
            grade="PARTIAL",
            missing_concepts=["comparative safety"],
            signals={"unique_studies": len(candidates)},
            rationale="The test judge stays partial to exercise the budget.",
        )


class AlwaysSufficientJudge:
    def judge(self, plan, candidates):
        return EvidenceGrade(
            grade="SUFFICIENT",
            missing_concepts=[],
            signals={"unique_studies": len(candidates)},
            rationale="The evidence is sufficient.",
        )


def make_test_service(judge=None, hybrid=None, synthesizer=None):
    settings = SimpleNamespace(
        MAX_CORRECTIVE_LOOPS=2,
        DENSE_TOP_K=10,
        RERANKER_TOP_N=2,
        MEDCPT_CROSS_ENCODER="unused",
        MODELS_CACHE_DIR="unused",
        DEVICE="cpu",
        MEDCPT_ALLOW_MOCK=False,
        TRACE_MAX_ENTRIES=10,
    )
    return ResearchService(
        settings=settings,
        query_analysis_service=FakeQueryAnalysis(),
        hybrid_retriever=hybrid or FakeHybrid(),
        reranker=FakeReranker(),
        evidence_judge=judge or AlwaysPartialJudge(),
        synthesizer=synthesizer,
    )


def test_research_corrective_loop_respects_budget_and_records_stages():
    service = make_test_service()
    result = service.research("Empagliflozin diabetes kidney outcomes", max_loops=1, request_id="budget-test")
    trace = service.get_trace("budget-test")
    assert trace["correction_attempts"] == 1
    assert len(trace["retrieval_iterations"]) == 2
    assert trace["stop_reason"] == "correction_budget_exhausted"
    assert result.citations_valid is True
    assert [stage["stage"] for stage in trace["stages"]][-5:] == [
        "evidence_extraction", "synthesize", "validate", "citation_verification", "done"
    ]


def test_research_graph_routes_sufficient_evidence_directly_to_synthesis():
    service = make_test_service(judge=AlwaysSufficientJudge())
    result = service.research("Empagliflozin diabetes kidney outcomes", max_loops=2, request_id="sufficient-test")
    trace = service.get_trace("sufficient-test")

    assert result.citations_valid is True
    assert len(trace["retrieval_iterations"]) == 1
    assert trace["corrective_queries"] == []
    assert trace["stop_reason"] == "evidence_sufficient"
    stage_names = [stage["stage"] for stage in trace["stages"]]
    assert stage_names.index("judge") < stage_names.index("evidence")
    assert "correct" not in stage_names


def test_corrective_query_stops_instead_of_adding_arbitrary_numbers():
    service = make_test_service()
    plan = make_plan()
    grade = EvidenceGrade("PARTIAL", [], {}, "still partial")
    used = [
        plan.original_query,
        f"{plan.canonical_query} clinical outcomes evidence",
        f"{plan.canonical_query} systematic review research findings",
        f"{plan.original_query} {' '.join(plan.mesh_terms[:3])}",
    ]
    assert service._corrective_query(plan, grade, used) is None


class EmptyHybrid(FakeHybrid):
    def search(self, plan, top_k):
        return []


class InsufficientJudge:
    def judge(self, plan, candidates):
        return EvidenceGrade("INSUFFICIENT", ["rare disease"], {"unique_studies": len(candidates)}, "No matching source abstracts.")


def test_research_gracefully_abstains_when_budget_is_zero_and_no_papers_exist():
    service = make_test_service(judge=InsufficientJudge(), hybrid=EmptyHybrid())
    result = service.research("rare disease treatment evidence", max_loops=0, request_id="abstain-test")
    trace = service.get_trace("abstain-test")
    assert result.consensus_level == "insufficient"
    assert result.citations_valid
    assert result.cited_pmids == []
    assert "insufficient" in result.synthesis.casefold()
    assert trace["correction_attempts"] == 0
    assert trace["stop_reason"] == "correction_disabled"


def test_hallucinated_pmid_from_synthesizer_is_rejected_and_replaced_with_grounded_spans():
    record = EvidenceExtractor().extract(make_candidate(), make_plan())
    fake_llm = lambda *args: "Empagliflozin cured every patient [PMID: 99999999]."
    synthesizer = EvidenceSynthesizer(client=fake_llm)
    result = synthesizer.synthesize("Empagliflozin in kidney disease", [record], [], insufficient=False)
    assert result.mode == "deterministic_spans"
    assert "99999999" not in result.text
    assert result.audit.valid
    assert result.audit.cited_pmids == [record.pmid]
    assert result.audit.hallucinated_pmids == []


def test_reranker_lexical_fallback_is_explicit_and_auditable():
    reranker = MedCPTReranker(model_name_or_path="unavailable")
    reranker._load = lambda: False
    reranker._load_error = "MedCPT Cross-Encoder checkpoint is unavailable"
    results, trace = reranker.rerank("empagliflozin kidney disease", [make_candidate()])
    assert results[0].reranker_mode == "lexical_fallback"
    assert results[0].fallback_reason == "MedCPT Cross-Encoder checkpoint is unavailable"
    assert trace["mode"] == "lexical_fallback"
