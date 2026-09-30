from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.evidence.extraction import EvidenceExtractor
from backend.app.models.request_response import (
    AnswerStatus,
    EvidenceRecord,
    RetrievalCandidate,
    RetrievalProvenance,
)
from backend.app.models.research_plan import CoverageStatus, SubquestionCoverage
from backend.app.conversation.models import CorrectiveResearchProposal, EvidenceGapContext
from backend.app.query.models import PICOModel, QueryPlan
from backend.app.query.query_service import QueryAnalysisService
from backend.app.query.router import AdaptiveComplexityRouter
from backend.app.retrieval.hybrid import HybridRetriever, reciprocal_rank_fusion
from backend.app.retrieval.reranker import MedCPTReranker
from backend.app.workflow.judge import EvidenceGrade, EvidenceSufficiencyJudge
from backend.app.workflow.planning import ResearchPlanner
from backend.app.workflow.service import ResearchService
from backend.app.workflow.synthesis import EvidenceSynthesizer, SynthesisResult


def test_benchmark_entry_uses_bounded_production_research_with_expected_route_and_hard_filter():
    service = object.__new__(ResearchService)
    response = SimpleNamespace(request_id="request-1")
    captured = {}
    service.research = lambda query, **kwargs: captured.update(query=query, **kwargs) or response
    service.get_trace = lambda request_id: {"request_id": request_id}
    entry = SimpleNamespace(query="benchmark query", study_type="Randomized Controlled Trial", expected_route="COMPLEX")

    result, trace = service.research_benchmark_entry(entry, max_loops=1)

    assert result is response
    assert trace == {"request_id": "request-1"}
    assert captured == {
        "query": "benchmark query",
        "user_filters": {"study_types": ["Randomized Controlled Trial"]},
        "max_loops": 1,
        "route_floor": "COMPLEX",
    }


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


class UnavailableSemanticVerifier:
    available = False

    def verify(self, synthesis, records):
        raise AssertionError("Unavailable semantic verifier must not be called")


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


def test_evidence_extractor_copies_exact_retrieval_and_reranker_provenance():
    candidate = make_candidate().model_copy(update={
        "channel_ranks": {"dense_original": 2, "bm25": 1},
        "channel_scores": {"dense_original": 0.82, "bm25": 7.5},
        "graph_path": ["query:diabetes", "paper:35100001"],
        "rrf_score": 0.041,
        "filter_satisfied": True,
        "reranker_score": 0.93,
        "reranker_mode": "medcpt",
        "retrieval_iteration": 1,
        "subquestion_ids": ["sq-1", "sq-2"],
    })

    evidence = EvidenceExtractor().extract(candidate, make_plan())

    assert evidence.retrieval_provenance == RetrievalProvenance(
        channel_ranks={"dense_original": 2, "bm25": 1},
        channel_scores={"dense_original": 0.82, "bm25": 7.5},
        graph_path=["query:diabetes", "paper:35100001"],
        rrf_score=0.041,
        filter_satisfied=True,
        retrieval_iteration=1,
    )
    assert evidence.reranker_score == 0.93
    assert evidence.reranker_mode == "medcpt"
    assert evidence.subquestion_ids == ["sq-1", "sq-2"]


def test_candidate_merge_retains_all_channels_subquestions_and_first_iteration():
    first = make_candidate().model_copy(update={
        "channel_ranks": {"dense_original": 1},
        "channel_scores": {"dense_original": 0.8},
        "subquestion_ids": ["sq-1"],
        "retrieval_iteration": 0,
        "reranker_score": 0.7,
    })
    second = make_candidate().model_copy(update={
        "channel_ranks": {"bm25": 2},
        "channel_scores": {"bm25": 6.0},
        "subquestion_ids": ["sq-2"],
        "retrieval_iteration": 1,
        "reranker_score": 0.9,
    })
    merged = {}

    ResearchService._merge_candidates(merged, [first], 0)
    ResearchService._merge_candidates(merged, [second], 1)

    result = merged[first.pmid]
    assert result.channel_ranks == {"dense_original": 1, "bm25": 2}
    assert result.channel_scores == {"dense_original": 0.8, "bm25": 6.0}
    assert result.subquestion_ids == ["sq-1", "sq-2"]
    assert result.retrieval_iteration == 0


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
    assert trace["timings_ms"]["total"] >= 0
    assert [item["iteration"] for item in trace["timings_ms"]["stages"] if item["stage"] == "retrieve"] == [0, 1]
    assert all(item["duration_ms"] >= 0 for item in trace["timings_ms"]["stages"])
    assert "timings_ms" in trace["retrieval_iterations"][0]
    assert [stage["stage"] for stage in trace["stages"]][-5:] == [
        "evidence_extraction", "synthesize", "validate", "citation_verification", "done"
    ]


def test_initial_and_corrective_plans_cross_enhancer_before_router():
    events = []

    class ObservedRouter(AdaptiveComplexityRouter):
        def route_query(self, query, clean_query, *args, **kwargs):
            events.append(("route", query))
            return super().route_query(query, clean_query, *args, **kwargs)

    class ObservedQueryAnalysis(QueryAnalysisService):
        def enhance_query(self, raw_query, **kwargs):
            events.append(("enhance", raw_query, kwargs.get("agent_rewrite")))
            return super().enhance_query(raw_query, **kwargs)

    analysis = ObservedQueryAnalysis(router=ObservedRouter())
    service = make_test_service()
    service._query_analysis_service = analysis

    service.research("Empagliflozin diabetes kidney outcomes", max_loops=1, request_id="enhancer-boundary")

    assert len([event for event in events if event[0] == "enhance"]) == 2
    assert len([event for event in events if event[0] == "route"]) == 2
    assert [event[0] for event in events] == ["enhance", "route", "enhance", "route"]
    assert events[0][1] == "Empagliflozin diabetes kidney outcomes"
    assert events[2][1] == events[0][1]
    assert events[2][2] != events[0][2]


def test_research_plan_forwards_agent_hint_and_prior_route_floor():
    service = make_test_service()
    service._query_analysis_service = QueryAnalysisService()

    raised_by_hint = service._build_plan("Sotorasib", agent_complexity_hint="COMPLEX")
    raised_by_floor = service._build_plan("Sotorasib", route_floor="MODERATE")

    assert raised_by_hint.route == "COMPLEX"
    assert raised_by_hint.agent_complexity_hint == "COMPLEX"
    assert raised_by_hint.rule_route == "SIMPLE"
    assert raised_by_hint.route_source == "agent_hint"
    assert raised_by_floor.route == "MODERATE"
    assert raised_by_floor.route_source == "route_floor"


def test_agent_gap_proposal_reenters_enhancer_router_retrieval_judge_with_route_floor():
    order = []
    plans = []

    class ObservedQueryAnalysis:
        def build_query_plan(self, raw_query, user_filters=None, generate_embeddings=False, **kwargs):
            order.append(("enhancer", raw_query))
            order.append(("router", kwargs.get("route_floor"), kwargs.get("agent_complexity_hint"), user_filters))
            plan = make_plan(original_query=raw_query, clean_query=raw_query, canonical_query=raw_query,
                             route="COMPLEX" if kwargs.get("agent_complexity_hint") == "COMPLEX" else "SIMPLE")
            plans.append(plan)
            return plan, None

    class ObservedHybrid(FakeHybrid):
        def search(self, plan, top_k):
            order.append(("retrieval", plan.original_query))
            return super().search(plan, top_k)

    class ObservedJudge:
        def judge(self, plan, candidates):
            order.append(("judge", plan.original_query))
            return EvidenceGrade("PARTIAL", ["comparative safety"], {"unique_studies": len(candidates)}, "missing safety")

    service = make_test_service(judge=ObservedJudge(), hybrid=ObservedHybrid())
    service._query_analysis_service = ObservedQueryAnalysis()
    reviewer_contexts = []

    def reviewer(context):
        order.append(("agent", context.standalone_question))
        reviewer_contexts.append(context)
        return CorrectiveResearchProposal(
            standalone_query="Empagliflozin comparative safety outcomes",
            complexity_hint="COMPLEX",
        )

    service.research(
        "Empagliflozin diabetes kidney outcomes",
        user_filters={"year_min": 2020},
        max_loops=1,
        route_floor="MODERATE",
        gap_reviewer=reviewer,
        request_id="agent-correction",
    )

    assert [item[0] for item in order] == [
        "enhancer", "router", "retrieval", "judge",
        "agent", "enhancer", "router", "retrieval", "judge",
    ]
    router_inputs = [item for item in order if item[0] == "router"]
    assert [item[1] for item in router_inputs] == ["MODERATE", "MODERATE"]
    assert router_inputs[1][2] == "COMPLEX"
    assert router_inputs[1][3] == {"year_min": 2020}
    assert reviewer_contexts[0].standalone_question == "Empagliflozin diabetes kidney outcomes"
    assert reviewer_contexts[0].prior_queries == ["empagliflozin diabetes kidney outcomes"]
    assert all(plan.original_query == "Empagliflozin diabetes kidney outcomes" for plan in plans)


def test_answer_from_evidence_revalidates_claims_without_retrieval_and_sets_status():
    service = make_test_service(judge=AlwaysSufficientJudge())
    service._search_plan = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retrieval called"))
    evidence = EvidenceRecord(
        pmid="12345", title="Study title", key_findings="Drug A reduced kidney disease progression.",
        supporting_text_spans=["Drug A reduced kidney disease progression."],
    )
    candidate = make_candidate(pmid="12345")

    response = service.answer_from_evidence(
        "Drug A kidney outcomes",
        candidates=[candidate], evidence=[evidence],
    )

    assert response.answer_status == AnswerStatus.SUPPORTED
    assert response.citations_valid is True
    assert response.cited_pmids == ["12345"]


def test_limited_research_explicitly_states_unresolved_question_and_gaps():
    response = make_test_service().research(
        "Empagliflozin diabetes kidney outcomes", max_loops=0, request_id="limited-caveat"
    )

    assert response.answer_status == AnswerStatus.LIMITED
    assert "The full question was not established by the available evidence." in response.synthesis
    assert "Evidence gaps are listed separately in the response." in response.synthesis
    assert "comparative safety" in response.evidence_gaps


def test_limited_evidence_only_answer_explicitly_reports_unresolved_parts():
    service = make_test_service(judge=AlwaysPartialJudge())
    evidence = EvidenceRecord(
        pmid="12345", key_findings="Drug A reduced kidney disease progression.",
        supporting_text_spans=["Drug A reduced kidney disease progression."],
    )

    response = service.answer_from_evidence(
        "Drug A kidney outcomes", candidates=[make_candidate(pmid="12345")], evidence=[evidence]
    )

    assert response.answer_status == AnswerStatus.LIMITED
    assert "The full question was not established by the available evidence." in response.synthesis
    assert "Evidence gaps are listed separately in the response." in response.synthesis
    assert "comparative safety" in response.evidence_gaps


def test_evidence_only_generated_prose_without_semantic_approval_uses_exact_span_fallback():
    source_span = "Drug A reduced kidney disease progression among adults with diabetes."
    generated_claim = "Drug A reduced kidney disease progression [PMID: 12345]."

    class UnverifiedGeneratedSynthesizer(EvidenceSynthesizer):
        def synthesize(self, query, records, gaps, insufficient=False):
            audit = self.validator.validate(generated_claim, records)
            assert audit.valid
            return SynthesisResult(generated_claim, "nvidia_nim", None, audit)

    service = make_test_service(judge=AlwaysSufficientJudge())
    service._synthesizer = UnverifiedGeneratedSynthesizer(
        semantic_verifier=UnavailableSemanticVerifier()
    )
    evidence = EvidenceRecord(
        pmid="12345", key_findings=source_span, supporting_text_spans=[source_span]
    )

    response = service.answer_from_evidence(
        "Drug A kidney outcomes", candidates=[make_candidate(pmid="12345")], evidence=[evidence]
    )

    assert response.answer_status == AnswerStatus.SUPPORTED
    assert generated_claim not in response.synthesis
    assert f"{source_span[:-1]} [PMID: 12345]." in response.synthesis


def test_evidence_only_exact_span_fallback_is_supported_without_semantic_service():
    source_span = "Drug A reduced kidney disease progression among adults with diabetes."
    service = make_test_service(judge=AlwaysSufficientJudge())
    service._synthesizer = EvidenceSynthesizer(
        semantic_verifier=UnavailableSemanticVerifier()
    )
    evidence = EvidenceRecord(
        pmid="12345", key_findings=source_span, supporting_text_spans=[source_span]
    )

    response = service.answer_from_evidence(
        "Drug A kidney outcomes", candidates=[make_candidate(pmid="12345")], evidence=[evidence]
    )

    assert response.answer_status == AnswerStatus.SUPPORTED
    assert f"{source_span[:-1]} [PMID: 12345]." in response.synthesis


def test_answer_from_evidence_with_no_safe_claim_is_insufficient():
    service = make_test_service(judge=InsufficientJudge(), hybrid=EmptyHybrid())

    response = service.answer_from_evidence("rare disease treatment", candidates=[], evidence=[])

    assert response.answer_status == AnswerStatus.INSUFFICIENT
    assert response.cited_pmids == []
    assert "insufficient" in response.synthesis.casefold()


def test_answer_from_evidence_releases_no_semantically_rejected_claim():
    class RejectAllSemanticClaims:
        available = True

        def verify(self, synthesis, records):
            from backend.app.models.request_response import ClaimVerification

            return [ClaimVerification(claim_index=0, supported=False, supporting_pmids=[], rationale="not established")]

    service = make_test_service(judge=AlwaysSufficientJudge())
    synthesizer = EvidenceSynthesizer(semantic_verifier=RejectAllSemanticClaims())
    service._synthesizer = synthesizer
    evidence = EvidenceRecord(
        pmid="12345", key_findings="Drug A reduced kidney disease progression.",
        supporting_text_spans=["Drug A reduced kidney disease progression."],
    )

    response = service.answer_from_evidence(
        "Drug A kidney outcomes", candidates=[make_candidate(pmid="12345")], evidence=[evidence]
    )

    assert response.answer_status == AnswerStatus.INSUFFICIENT
    assert response.cited_pmids == []
    assert "insufficient" in response.synthesis.casefold()


def test_research_semantic_release_rejection_adds_gap_and_audit_counts_it():
    from backend.app.models.request_response import ClaimVerification
    from backend.app.workflow.synthesis import EvidenceSynthesizer, _claims

    class TwoStudyHybrid(FakeHybrid):
        def search(self, plan, top_k):
            return [make_candidate(pmid="35100001"), make_candidate(pmid="35100002")]

    class RejectAllSemanticClaims:
        available = True

        def verify(self, synthesis, records):
            return [
                ClaimVerification(
                    claim_index=index, supported=False, supporting_pmids=[],
                    rationale="Claim failed release verification.",
                )
                for index, _claim in enumerate(_claims(synthesis))
            ]

    service = make_test_service(
        judge=AlwaysSufficientJudge(), hybrid=TwoStudyHybrid(),
        synthesizer=EvidenceSynthesizer(semantic_verifier=RejectAllSemanticClaims()),
    )
    events = []

    response = service.research(
        "Empagliflozin diabetes kidney outcomes", max_loops=0,
        request_id="semantic-rejection-gap", event_sink=lambda name, payload: events.append((name, payload)),
    )

    judge_event = next(payload for name, payload in events if name == "evidence_judged")
    release_event = next(payload for name, payload in events if name == "answer_released")
    assert judge_event["grade"] == "SUFFICIENT"
    assert judge_event["missing_count"] == 0 and judge_event["conflict_count"] == 0
    assert response.answer_status is AnswerStatus.INSUFFICIENT
    assert response.evidence_gaps
    assert "No retrieved claim passed the citation and semantic verification gates." in response.evidence_gaps
    assert release_event["status"] == "INSUFFICIENT"
    assert release_event["gap_count"] == len(response.evidence_gaps)
    repair_event = next(payload for name, payload in events if name == "claim_repair")
    assert repair_event["attempt_count"] == 1
    assert repair_event["pruned_claims"] >= 1
    assert service.get_trace("semantic-rejection-gap")["synthesis_metadata"]["repair"] == repair_event


def test_failed_gap_reviewer_uses_deterministic_correction_and_maps_limited():
    service = make_test_service()
    contexts = []

    def broken_reviewer(context):
        contexts.append(context)
        raise RuntimeError("agent unavailable")

    response = service.research(
        "Empagliflozin diabetes kidney outcomes", max_loops=1,
        gap_reviewer=broken_reviewer, request_id="agent-fallback",
    )
    trace = service.get_trace("agent-fallback")
    assert len(contexts) == 1
    assert trace["correction_attempts"] == 1
    assert trace["corrective_queries"][0]["query"] != "Empagliflozin diabetes kidney outcomes"
    assert trace["stop_reason"] == "correction_budget_exhausted"
    assert response.answer_status == AnswerStatus.LIMITED


def test_normalized_duplicate_agent_query_is_rejected_and_summaries_stay_bounded():
    service = make_test_service()
    events = []
    question = "Empagliflozin diabetes kidney outcomes"

    response = service.research(
        question,
        max_loops=1,
        gap_reviewer=lambda _context: CorrectiveResearchProposal(
            standalone_query="  EMPAGLIFLOZIN   diabetes kidney outcomes ",
            complexity_hint="SIMPLE",
        ),
        event_sink=lambda name, payload: events.append((name, payload)),
        request_id="duplicate-agent-query",
    )
    trace = service.get_trace("duplicate-agent-query")

    assert len(trace["corrective_queries"]) == 1
    assert " ".join(trace["corrective_queries"][0]["query"].casefold().split()) != " ".join(question.casefold().split())
    assert response.answer_status == AnswerStatus.LIMITED
    assert {name for name, _ in events} >= {
        "agent_decision", "query_enhanced", "route_arbitrated", "retrieval_attempt",
        "evidence_judged", "answer_released",
    }
    assert all("supporting_text_spans" not in str(payload) for _, payload in events)


def test_rewrite_is_recorded_as_the_initial_query_for_gap_context():
    service = make_test_service(judge=AlwaysPartialJudge())
    contexts = []
    raw_query = "Compare renal outcomes for adults with CKD taking SGLT2 inhibitors, 2019 onward"
    rewrite = "SGLT2 inhibitor kidney outcomes"

    service.research(
        raw_query,
        max_loops=1,
        agent_rewrite=rewrite,
        gap_reviewer=lambda context: contexts.append(context) or None,
        request_id="rewrite-gap-context",
    )

    assert contexts[0].standalone_question == raw_query
    assert contexts[0].prior_queries == [rewrite.casefold()]


def test_research_emits_claim_verification_summary_before_release():
    service = make_test_service(judge=AlwaysSufficientJudge())
    events = []
    raw_claim = "Among patients with type 2 diabetes and chronic kidney disease, empagliflozin reduced progression of kidney disease compared with placebo."

    service.research(
        "Empagliflozin diabetes kidney outcomes", max_loops=0,
        event_sink=lambda name, payload: events.append((name, payload)),
        request_id="claim-verification-event",
    )

    names = [name for name, _ in events]
    verified_index = names.index("claim_verified")
    release_index = names.index("answer_released")
    assert verified_index < release_index
    verified = events[verified_index][1]
    assert set(verified) == {"claim_count", "supported_count"}
    assert verified["claim_count"] == verified["supported_count"] >= 1
    assert raw_claim not in str(events)
    assert "supporting_text_spans" not in str(events)


def test_retrieval_provider_failure_is_failed_not_insufficient_evidence():
    class BrokenHybrid(FakeHybrid):
        def search(self, plan, top_k):
            raise RuntimeError("database unavailable")

    service = make_test_service(hybrid=BrokenHybrid())
    response = service.research(
        "Empagliflozin kidney outcomes", max_loops=1, request_id="retrieval-failure"
    )
    trace = service.get_trace("retrieval-failure")
    assert response.answer_status == AnswerStatus.FAILED
    assert "technical failure" in response.synthesis.casefold()
    assert "insufficient" not in response.synthesis.casefold()
    assert response.evidence_gaps == []
    assert trace["stop_reason"] == "retrieval_failed"


def test_unresolved_conflict_abstains_and_exposes_conflict_gap():
    class ConflictingJudge:
        def judge(self, plan, candidates):
            return EvidenceGrade("PARTIAL", [], {}, "opposing findings", conflicts=["Studies report opposite effects."])

    service = make_test_service(judge=ConflictingJudge())
    response = service.research(
        "Empagliflozin kidney outcomes", max_loops=2, request_id="conflicting-evidence"
    )

    assert response.answer_status == AnswerStatus.INSUFFICIENT
    assert "Studies report opposite effects." in response.evidence_gaps
    assert service.get_trace("conflicting-evidence")["stop_reason"] == "unresolved_conflict"


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


def test_failed_synthesis_has_accurate_durable_stage_events():
    class BrokenSynthesizer:
        def synthesize(self, *args, **kwargs):
            raise RuntimeError("provider failed")

    service = make_test_service(judge=AlwaysSufficientJudge(), synthesizer=BrokenSynthesizer())
    events = []
    with pytest.raises(RuntimeError, match="provider failed"):
        service.research("Empagliflozin kidney outcomes", max_loops=0, request_id="failed-synthesis", event_sink=lambda stage, payload: events.append((stage, payload)))
    synthesize = [payload for stage, payload in events if stage == "synthesize"]
    assert [event["status"] for event in synthesize] == ["started", "failed"]
    assert any(stage == "query_analysis" and payload.get("status") == "completed" and payload.get("query_plan") for stage, payload in events)
    assert any(stage == "retrieve" and payload.get("status") == "completed" and payload.get("candidate_pmids") for stage, payload in events)
    assert any(stage == "evidence" and payload.get("status") == "completed" and payload.get("evidence_count") for stage, payload in events)

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


def test_corrective_query_targets_ready_subquestion_before_generic_broadening():
    plan = make_plan(
        original_query="Compare empagliflozin with placebo for kidney outcomes",
        canonical_query="empagliflozin versus placebo kidney outcomes",
        route="COMPLEX",
        intent="comparison",
        pico=PICOModel(
            intervention="empagliflozin", comparator="placebo", outcome="kidney outcomes"
        ),
    )
    research_plan = ResearchPlanner().build(plan, max_subqueries=3)
    coverage = {
        "sq-1": SubquestionCoverage(subquestion_id="sq-1", status=CoverageStatus.COVERED),
        "sq-2": SubquestionCoverage(
            subquestion_id="sq-2", status=CoverageStatus.UNCOVERED,
            missing_concepts=["placebo"],
        ),
        "sq-3": SubquestionCoverage(subquestion_id="sq-3", status=CoverageStatus.BLOCKED),
    }
    service = make_test_service()

    target = service._corrective_query(
        plan, EvidenceGrade("PARTIAL", ["comparative safety"], {}, "partial"),
        [plan.original_query], research_plan, coverage,
    )

    assert target is not None
    subquestion_id, query = target
    assert subquestion_id == "sq-2"
    assert research_plan.subquestions[1].question in query
    assert "comparative safety" not in query


def test_complex_research_trace_exposes_dependency_ordered_coverage_and_targets():
    class ComplexQueryAnalysis:
        def build_query_plan(self, raw_query, user_filters=None, generate_embeddings=False, **kwargs):
            rewrite = kwargs.get("agent_rewrite")
            return make_plan(
                original_query=raw_query,
                clean_query=raw_query,
                canonical_query=rewrite or "empagliflozin versus placebo kidney outcomes",
                route="COMPLEX",
                intent="comparison",
                pico=PICOModel(
                    intervention="empagliflozin", comparator="placebo", outcome="kidney outcomes"
                ),
            ), None

    class TargetedHybrid(FakeHybrid):
        def search(self, plan, top_k):
            query = plan.canonical_query.casefold()
            if "direct evidence compares" in query:
                return [make_candidate(
                    pmid="1003",
                    abstract="Direct evidence compares empagliflozin with placebo for kidney outcomes.",
                )]
            if "what evidence reports kidney outcomes for placebo" in query:
                return [make_candidate(
                    pmid="1002", abstract="Placebo kidney outcomes were reported in the comparator arm."
                )]
            return [make_candidate(
                pmid="1001", abstract="Empagliflozin improved kidney outcomes in the intervention arm."
            )]

    service = make_test_service(judge=AlwaysSufficientJudge(), hybrid=TargetedHybrid())
    service._query_analysis_service = ComplexQueryAnalysis()

    service.research(
        "Compare empagliflozin with placebo for kidney outcomes",
        max_loops=2,
        request_id="coverage-order",
    )
    trace = service.get_trace("coverage-order")

    assert [item["subquestion_id"] for item in trace["retrieval_iterations"]] == [
        "sq-1", "sq-2", "sq-3"
    ]
    assert [item["subquestion_id"] for item in trace["corrective_queries"]] == [
        "sq-2", "sq-3"
    ]
    assert trace["research_plan"]["subquestions"][2]["dependencies"] == ["sq-1", "sq-2"]
    assert trace["coverage_history"][0]["coverage"][2]["status"] == "BLOCKED"
    assert all(
        item["status"] == "COVERED" for item in trace["coverage_history"][-1]["coverage"]
    )
    assert trace["stop_reason"] == "evidence_sufficient"


def test_complex_correction_does_not_repeat_the_initial_targeted_subquestion():
    class ComplexQueryAnalysis:
        def build_query_plan(self, raw_query, user_filters=None, generate_embeddings=False, **kwargs):
            return make_plan(
                original_query=raw_query,
                clean_query=raw_query,
                canonical_query=kwargs.get("agent_rewrite") or raw_query,
                route="COMPLEX",
                intent="comparison",
                pico=PICOModel(
                    intervention="empagliflozin", comparator="placebo", outcome="kidney outcomes"
                ),
            ), None

    service = make_test_service(judge=AlwaysPartialJudge(), hybrid=EmptyHybrid())
    service._query_analysis_service = ComplexQueryAnalysis()
    service.research(
        "Compare empagliflozin with placebo for kidney outcomes",
        max_loops=1,
        request_id="no-repeat-target",
    )
    trace = service.get_trace("no-repeat-target")

    assert trace["retrieval_iterations"][0]["subquestion_id"] == "sq-1"
    assert trace["corrective_queries"][0]["subquestion_id"] == "sq-2"
    assert trace["corrective_queries"][0]["query"] != trace["retrieval_iterations"][0]["query"]


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


def test_empty_candidate_judgement_never_calls_optional_model():
    def should_not_run(*_args):
        raise AssertionError("No evidence exists for model grading")

    grade = EvidenceSufficiencyJudge(llm_judge=should_not_run).judge(make_plan(), [])

    assert grade.grade == "INSUFFICIENT"
    assert grade.signals["candidate_count"] == 0


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
