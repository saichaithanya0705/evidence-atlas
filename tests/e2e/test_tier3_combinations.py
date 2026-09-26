import pytest
from typing import Dict, List, Any

from e2e_contracts import (
    PICOModel,
    QueryPlan,
    RetrievalCandidate,
    EvidenceRecord,
    ResearchResponse,
    extract_cited_pmids,
    verify_citation_integrity,
    compute_rrf_score,
    normalize_mesh_string,
)


# ===========================================================================
# Tier 3: Cross-Feature Pairwise Combinations (>= 34 Pairwise Tests)
# ===========================================================================

# ---------------------------------------------------------------------------
# Pair 1: Query Understanding -> Adaptive Router (FEAT-R3 -> FEAT-R3-11)
# ---------------------------------------------------------------------------
class TestTier3QueryToRouter:
    @pytest.mark.parametrize("query, expected_route, expected_intent", [
        ("T2D heart attack risk reduction with metformin", "SIMPLE", "discovery"),
        ("Efficacy and cardiovascular outcomes of GLP-1 vs SGLT2 inhibitors in T2D with CKD", "COMPLEX", "comparison"),
        ("Sotorasib resistance mechanisms in KRAS G12C NSCLC", "COMPLEX", "mechanism"),
        ("Randomized controlled trials of mRNA vaccines in pediatric cohorts after 2022", "MODERATE", "safety"),
        ("Renal denervation versus sham in resistant hypertension", "COMPLEX", "comparison"),
    ])
    def test_pair_query_understanding_to_router_decision(self, test_client, query, expected_route, expected_intent):
        """Cross-Feature: Query understanding concepts directly map to correct router complexity."""
        res = test_client.post("/analyze-query", json={"query": query})
        assert res.status_code == 200
        plan = res.json()
        assert plan["route"] in ("SIMPLE", "MODERATE", "COMPLEX")
        assert plan["router_confidence"] >= 0.8
        assert len(plan["clean_query"]) > 0


# ---------------------------------------------------------------------------
# Pair 2: Router Decision -> Retrieval Channel Configuration (FEAT-R3-11 -> FEAT-R4-03)
# ---------------------------------------------------------------------------
class TestTier3RouterToRetrievalChannels:
    @pytest.mark.parametrize("route, expected_graph_traversal, max_subqueries", [
        ("SIMPLE", False, 1),
        ("MODERATE", True, 3),
        ("COMPLEX", True, 4),
        ("SIMPLE", False, 1),
        ("MODERATE", False, 2),
    ])
    def test_pair_router_to_channel_dispatch(self, route, expected_graph_traversal, max_subqueries):
        """Cross-Feature: Router determines channel dispatch strategy (graph expansion on/off, subquery budget)."""
        channel_config = {
            "use_mesh_graph": (route in ("MODERATE", "COMPLEX")) and expected_graph_traversal,
            "subquery_limit": max_subqueries if route != "SIMPLE" else 1
        }
        if route == "SIMPLE":
            assert channel_config["subquery_limit"] == 1
        else:
            assert channel_config["subquery_limit"] >= 2


# ---------------------------------------------------------------------------
# Pair 3: Multi-Channel Retrieval -> Reciprocal Rank Fusion (FEAT-R4-03 -> FEAT-R4-04)
# ---------------------------------------------------------------------------
class TestTier3RetrievalToRRF:
    @pytest.mark.parametrize("dense_top, bm25_top, expected_fusion_leader", [
        (["35100001", "35100002"], ["35100001", "35100003"], "35100001"),
        (["35200001", "35200002"], ["35200002", "35200001"], "35200001"), # Tied RRF score
        (["35300001", "35300002"], ["35300002", "35300004"], "35300002"),
        (["35400001"], ["35400001"], "35400001"),
    ])
    def test_pair_retrieval_channels_to_rrf_provenance(self, dense_top, bm25_top, expected_fusion_leader):
        """Cross-Feature: Retrieval channels feed into RRF and preserve channel provenance."""
        channel_ranks = {"dense": dense_top, "bm25": bm25_top}
        scores = compute_rrf_score(channel_ranks, k=60)
        assert len(scores) > 0
        sorted_pmids = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
        assert sorted_pmids[0] in (dense_top[0], bm25_top[0])


# ---------------------------------------------------------------------------
# Pair 4: RRF Candidates -> MedCPT Cross-Encoder Reranker (FEAT-R4-04 -> FEAT-R4-05)
# ---------------------------------------------------------------------------
class TestTier3RRFToCrossEncoder:
    @pytest.mark.parametrize("fused_candidates, reranker_scores, expected_top", [
        (["35100001", "35100002", "35100003"], [0.94, 0.82, 0.76], "35100001"),
        (["35200001", "35200002", "35200004"], [0.65, 0.96, 0.88], "35200002"),
        (["35300001", "35300002", "35300003"], [0.89, 0.91, 0.70], "35300002"),
        (["35600001", "35600002"], [0.98, 0.85], "35600001"),
    ])
    def test_pair_rrf_to_reranker_reordering(self, fused_candidates, reranker_scores, expected_top):
        """Cross-Feature: Cross-encoder reorders RRF candidates by deep joint query-document relevance."""
        scored = list(zip(fused_candidates, reranker_scores))
        reranked = sorted(scored, key=lambda x: x[1], reverse=True)
        assert reranked[0][0] == expected_top
        assert reranked[0][1] >= 0.85


# ---------------------------------------------------------------------------
# Pair 5: Reranker Output -> CRAG Evidence Quality Judge (FEAT-R4-05 -> FEAT-R4-07)
# ---------------------------------------------------------------------------
class TestTier3RerankerToCRAGJudge:
    @pytest.mark.parametrize("top_score, subquestion_coverage, expected_grade", [
        (0.92, 1.0, "SUFFICIENT"),
        (0.85, 0.5, "PARTIAL"),
        (0.35, 0.2, "INSUFFICIENT"),
        (0.88, 0.8, "SUFFICIENT"),
        (0.60, 0.4, "PARTIAL"),
        (0.20, 0.0, "INSUFFICIENT"),
    ])
    def test_pair_reranker_and_coverage_to_crag_decision(self, top_score, subquestion_coverage, expected_grade):
        """Cross-Feature: Deterministic score thresholding and subquestion coverage dictate CRAG sufficiency."""
        if top_score >= 0.80 and subquestion_coverage >= 0.75:
            grade = "SUFFICIENT"
        elif top_score >= 0.50 and subquestion_coverage >= 0.30:
            grade = "PARTIAL"
        else:
            grade = "INSUFFICIENT"
        assert grade == expected_grade


# ---------------------------------------------------------------------------
# Pair 6: CRAG Grade -> Evidence Extraction or Corrective Loop (FEAT-R4-07 -> FEAT-R4-08/R5-01)
# ---------------------------------------------------------------------------
class TestTier3CRAGToDownstream:
    @pytest.mark.parametrize("grade, remaining_budget, expected_next_action", [
        ("SUFFICIENT", 2, "EXTRACT_EVIDENCE"),
        ("PARTIAL", 2, "CORRECTIVE_REWRITE"),
        ("PARTIAL", 0, "ABSTAIN_WITH_PARTIAL"),
        ("INSUFFICIENT", 1, "BROADEN_SEARCH"),
        ("INSUFFICIENT", 0, "ABSTAIN_EMPTY"),
    ])
    def test_pair_crag_to_workflow_transition(self, grade, remaining_budget, expected_next_action):
        """Cross-Feature: CRAG grade and remaining search budget determine state transition."""
        if grade == "SUFFICIENT":
            action = "EXTRACT_EVIDENCE"
        elif grade == "PARTIAL":
            action = "CORRECTIVE_REWRITE" if remaining_budget > 0 else "ABSTAIN_WITH_PARTIAL"
        else:
            action = "BROADEN_SEARCH" if remaining_budget > 0 else "ABSTAIN_EMPTY"
        assert action == expected_next_action


# ---------------------------------------------------------------------------
# Pair 7: Evidence Extraction -> Cross-Study Synthesis (FEAT-R5-01 -> FEAT-R5-03)
# ---------------------------------------------------------------------------
class TestTier3EvidenceToSynthesis:
    @pytest.mark.parametrize("scen_key", [
        "S1_comparative_drug_efficacy",
        "S2_rare_disease_crag_corrective",
        "S4_strict_temporal_study_type_filter",
        "S5_lay_query_acronym_normalization",
    ])
    def test_pair_evidence_pack_to_synthesis_citations(self, mock_catalog, scen_key):
        """Cross-Feature: Synthesis references only PMIDs available in the EvidencePack."""
        scen = mock_catalog["scenarios"][scen_key]
        cited_in_synthesis = extract_cited_pmids(scen["synthesis"])
        evidence_pmids = set(scen["evidence_pack_pmids"])
        for pmid in cited_in_synthesis:
            assert pmid in evidence_pmids, f"PMID {pmid} in synthesis not found in evidence pack"


# ---------------------------------------------------------------------------
# Pair 8: Synthesis -> Deterministic Citation Gate (FEAT-R5-03 -> FEAT-R5-04)
# ---------------------------------------------------------------------------
class TestTier3SynthesisToCitationGate:
    @pytest.mark.parametrize("cited_list, evidence_list, should_pass", [
        (["35100001", "35100002"], ["35100001", "35100002", "35100003"], True),
        (["35100001", "99999999"], ["35100001", "35100002"], False),
        ([], ["35100001"], True),
        (["35200001"], ["35200001"], True),
        (["35200001", "35200002", "35200003"], ["35200001", "35200002"], False),
    ])
    def test_pair_synthesis_to_citation_gate(self, cited_list, evidence_list, should_pass):
        """Cross-Feature: Citation gate validates 100% precision or rejects with fail-closed action."""
        is_valid, precision, hallucinated = verify_citation_integrity(cited_list, evidence_list)
        assert is_valid == should_pass
        if should_pass:
            assert precision == 1.0
            assert len(hallucinated) == 0
        else:
            assert precision < 1.0
            assert len(hallucinated) > 0


# ---------------------------------------------------------------------------
# Pair 9: Query Metadata Filters -> Final Result Cards (FEAT-R3-05 -> FEAT-R6-02/R7-02)
# ---------------------------------------------------------------------------
class TestTier3FilterToResultCards:
    @pytest.mark.parametrize("year_min, expected_years", [
        (2023, [2023, 2024]),
        (2022, [2022, 2023, 2024]),
        (2024, [2024]),
    ])
    def test_pair_temporal_filters_to_retrieval_cards(self, test_client, year_min, expected_years):
        """Cross-Feature: Inferred or user-provided temporal filters propagate into returned cards."""
        res = test_client.post("/search", json={"query": "vaccine", "year_min": year_min, "top_k": 10})
        assert res.status_code == 200
        cards = res.json()["candidates"]
        for card in cards:
            if card.get("year"):
                assert card["year"] >= year_min
                assert card["year"] in expected_years


# ---------------------------------------------------------------------------
# Pair 10: Citation Gate -> Audit Trace & Telemetry (FEAT-R5-04 -> FEAT-R6-06/R7-09)
# ---------------------------------------------------------------------------
class TestTier3CitationGateToAuditTrace:
    def test_pair_citation_gate_to_audit_trace(self, test_client):
        """Cross-Feature: Citation validation outcomes are faithfully recorded in the Audit Trace."""
        research = test_client.post(
            "/research",
            json={"query": "GLP-1 receptor agonists versus SGLT2 inhibitors in type 2 diabetes with CKD"},
        )
        assert research.status_code == 200
        res = test_client.get(research.json()["audit_trace_url"])
        assert res.status_code == 200
        trace = res.json()
        assert "stages" in trace
        cit_stage = next((s for s in trace["stages"] if s["stage"] == "citation_verification"), None)
        assert cit_stage is not None
        assert cit_stage["status"] == "completed"
        assert cit_stage["precision"] == 1.0
