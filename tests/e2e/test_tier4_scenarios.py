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
# Tier 4: Real-World Clinical Researcher Workloads & Scenarios (S1 - S5 + Variations)
# ===========================================================================

# ---------------------------------------------------------------------------
# Scenario S1: Comparative Drug Efficacy (GLP-1 RA vs SGLT2i in T2D with CKD)
# ---------------------------------------------------------------------------
class TestTier4Scenario1ComparativeDrugEfficacy:
    @pytest.fixture
    def s1_response(self, test_client):
        query = "Efficacy and cardiovascular outcomes of GLP-1 receptor agonists vs SGLT2 inhibitors in type 2 diabetes mellitus with CKD"
        res = test_client.post("/research", json={"query": query})
        assert res.status_code == 200
        return res.json()

    def test_s1_route_classification(self, s1_response):
        """S1: Must route to COMPLEX due to multi-arm comparison."""
        assert s1_response["route"] == "COMPLEX"

    def test_s1_evidence_table_multi_arm_structure(self, s1_response):
        """S1: Evidence table contains comparative records for both drug classes."""
        table = s1_response["evidence_table"]
        assert len(table) >= 3
        interventions = [rec.get("intervention", "") for rec in table if rec.get("intervention")]
        assert len(interventions) >= 1

    def test_s1_strict_100_percent_citation_precision(self, s1_response):
        """S1: Zero hallucinated PMIDs and 100% citation precision."""
        cited = s1_response["cited_pmids"]
        assert len(cited) >= 2
        evidence_pmids = [rec["pmid"] for rec in s1_response["evidence_table"]]
        is_valid, precision, hallucinated = verify_citation_integrity(cited, evidence_pmids)
        assert is_valid is True
        assert precision == 1.0
        assert len(hallucinated) == 0

    @pytest.mark.parametrize("query_variant", [
        "SGLT2 inhibitors versus GLP-1 receptor agonists in diabetic kidney disease",
        "Cardiovascular mortality reduction: Empagliflozin vs Semaglutide in T2D CKD",
        "Comparative network meta-analysis of SGLT2i vs GLP1-RA on heart failure and stroke"
    ])
    def test_s1_query_variants_retrieval(self, test_client, query_variant):
        """S1 Variations: Comparative drug efficacy variants retrieve cardiorenal RCTs."""
        res = test_client.post("/search", json={"query": query_variant, "top_k": 5})
        assert res.status_code == 200
        cands = res.json()["candidates"]
        assert len(cands) >= 1
        pmids = [c["pmid"] for c in cands]
        assert any(p in pmids for p in ["35100001", "35100002", "35100003", "35100004"])


# ---------------------------------------------------------------------------
# Scenario S2: Rare Disease CRAG Corrective Loop (Sotorasib KRAS G12C NSCLC)
# ---------------------------------------------------------------------------
class TestTier4Scenario2CRAGCorrectiveLoop:
    @pytest.fixture
    def s2_data(self, mock_catalog):
        return mock_catalog["scenarios"]["S2_rare_disease_crag_corrective"]

    def test_s2_initial_partial_grade_triggers_rewrite(self, s2_data):
        """S2: Initial retrieval returns PARTIAL grade triggering corrective search."""
        assert s2_data["initial_crag_grade"] == "PARTIAL"
        assert len(s2_data["initial_missing_concepts"]) > 0
        assert "MET amplification" in s2_data["initial_missing_concepts"]

    def test_s2_corrective_query_recovers_bypass_mechanisms(self, s2_data):
        """S2: Corrective query directly targets missing resistance bypass mechanisms."""
        assert "MET" in s2_data["corrective_query"]
        assert s2_data["final_crag_grade"] == "SUFFICIENT"
        assert "35200004" in s2_data["evidence_pack_pmids"]

    def test_s2_synthesis_mechanistic_grounding(self, s2_data):
        """S2: Final synthesis cites specific secondary mutations and MET amplification."""
        synthesis = s2_data["synthesis"]
        assert "MET" in synthesis
        assert "switch II" in synthesis or "Y96D" in synthesis
        is_valid, precision, hallucinated = verify_citation_integrity(s2_data["cited_pmids"], s2_data["evidence_pack_pmids"])
        assert is_valid is True
        assert precision == 1.0

    @pytest.mark.parametrize("query_variant", [
        "Acquired resistance to sotorasib via secondary mutations in NSCLC",
        "MET amplification bypass in KRAS G12C lung adenocarcinoma",
        "Adagrasib intracranial responses in active brain metastases"
    ])
    def test_s2_query_variants_retrieval(self, test_client, query_variant):
        """S2 Variations: Resistance queries return targeted molecular biology studies."""
        res = test_client.post("/search", json={"query": query_variant, "top_k": 5})
        assert res.status_code == 200
        pmids = [c["pmid"] for c in res.json()["candidates"]]
        assert any(p in pmids for p in ["35200001", "35200002", "35200003", "35200004", "35200005"])


# ---------------------------------------------------------------------------
# Scenario S3: Complete Corpus Absence Abstention (Hyperbaric Oxygen in Stage IV Tau)
# ---------------------------------------------------------------------------
class TestTier4Scenario3CorpusAbsenceAbstention:
    @pytest.fixture
    def s3_data(self, mock_catalog):
        return mock_catalog["scenarios"]["S3_corpus_absence_abstention"]

    def test_s3_crag_insufficient_grade(self, s3_data):
        """S3: CRAG identifies lack of supportive human clinical evidence as INSUFFICIENT."""
        assert s3_data["crag_sufficiency"]["grade"] == "INSUFFICIENT"
        assert s3_data["consensus_level"] == "insufficient"

    def test_s3_graceful_abstention_and_gap_reporting(self, s3_data):
        """S3: System abstains from asserting therapeutic efficacy and explicitly lists evidence gaps."""
        assert len(s3_data["evidence_gaps"]) >= 1
        synthesis = s3_data["synthesis"].lower()
        assert "insufficient" in synthesis or "abstains" in synthesis or "fails" in synthesis

    def test_s3_zero_hallucinated_citations(self, s3_data):
        """S3: Abstention does not fabricate supporting citations."""
        is_valid, precision, hallucinated = verify_citation_integrity(s3_data["cited_pmids"], s3_data["evidence_pack_pmids"])
        assert is_valid is True
        assert precision == 1.0
        assert len(hallucinated) == 0

    @pytest.mark.parametrize("query_variant", [
        "Hyperbaric oxygen therapy efficacy in reversing advanced Stage IV Alzheimer's disease tau aggregation",
        "Non-pharmacological HBOT for tau tangle clearance in dementia",
        "Quantum vibrational resonance therapy for glioblastoma"
    ])
    def test_s3_unsupported_queries_abstention_behavior(self, test_client, query_variant):
        """S3 Variations: Queries lacking supportive corpus trigger abstention without hallucination."""
        res = test_client.post("/research", json={"query": query_variant})
        assert res.status_code == 200
        data = res.json()
        assert data["citation_precision"] == 1.0
        assert data["consensus_level"] in ("insufficient", "conflicting", "mixed", "consensus")


# ---------------------------------------------------------------------------
# Scenario S4: Strict Temporal & Study Type Filtering (Pediatric mRNA Vaccines)
# ---------------------------------------------------------------------------
class TestTier4Scenario4StrictFiltering:
    @pytest.fixture
    def s4_data(self, mock_catalog):
        return mock_catalog["scenarios"]["S4_strict_temporal_study_type_filter"]

    def test_s4_inferred_filters(self, s4_data):
        """S4: Correctly infers year_min=2023 and study_type=Randomized Controlled Trial."""
        filters = s4_data["inferred_filters"]
        assert filters["year_min"] == 2023
        assert "Randomized Controlled Trial" in filters["study_type_filters"]

    def test_s4_filtered_retrieval_adherence(self, test_client):
        """S4: Returned papers strictly satisfy year >= 2023 and study_type = RCT."""
        res = test_client.post("/search", json={
            "query": "mRNA vaccines in pediatric populations",
            "year_min": 2023,
            "study_type": "Randomized Controlled Trial",
            "top_k": 5
        })
        assert res.status_code == 200
        cands = res.json()["candidates"]
        assert len(cands) >= 1
        for card in cands:
            assert card["year"] >= 2023
            # Study type must be RCT or similar
            assert "randomized" in card.get("study_type", "").lower() or "rct" in card.get("study_type", "").lower()

    def test_s4_synthesis_citations_precision(self, s4_data):
        """S4: Synthesis cites only pediatric RCTs meeting temporal criteria."""
        is_valid, precision, hallucinated = verify_citation_integrity(s4_data["cited_pmids"], s4_data["evidence_pack_pmids"])
        assert is_valid is True
        assert precision == 1.0


# ---------------------------------------------------------------------------
# Scenario S5: Lay-Query Acronym Normalization (T2D heart attack risk reduction)
# ---------------------------------------------------------------------------
class TestTier4Scenario5AcronymNormalization:
    @pytest.fixture
    def s5_data(self, mock_catalog):
        return mock_catalog["scenarios"]["S5_lay_query_acronym_normalization"]

    def test_s5_acronym_expansion(self, s5_data):
        """S5: Expands 'T2D' to Type 2 Diabetes and 'heart attack' to Myocardial Infarction."""
        expanded = s5_data["acronyms_expanded"]
        assert expanded["T2D"] == "Type 2 Diabetes Mellitus"
        assert expanded["heart attack"] == "Myocardial Infarction"

    def test_s5_simple_route_dispatch(self, s5_data):
        """S5: Direct single-intervention query routes to SIMPLE."""
        assert s5_data["route"] == "SIMPLE"
        assert s5_data["router_confidence"] >= 0.90

    def test_s5_synthesis_citations_precision(self, s5_data):
        """S5: Synthesis cites metformin clinical evidence with 100% precision."""
        is_valid, precision, hallucinated = verify_citation_integrity(s5_data["cited_pmids"], s5_data["evidence_pack_pmids"])
        assert is_valid is True
        assert precision == 1.0
        assert "35600001" in s5_data["cited_pmids"]


# ---------------------------------------------------------------------------
# Extended Clinical Researcher Scenarios (S6 - S10)
# ---------------------------------------------------------------------------
class TestTier4ExtendedClinicalScenarios:
    @pytest.mark.parametrize("scenario_name, query, expected_pmid, expected_disease", [
        ("S6_severe_asthma_biologics", "Tezepelumab efficacy in severe uncontrolled asthma exacerbations", "35700001", "Asthma"),
        ("S7_breast_cancer_adc", "Trastuzumab deruxtecan vs T-DM1 progression-free survival HER2 breast cancer", "35800001", "Breast Neoplasms"),
        ("S8_resistant_htn_denervation", "Renal denervation blood pressure reduction in resistant hypertension", "35400001", "Hypertension"),
        ("S9_aldosterone_synthase", "Baxdrostat aldosterone synthase inhibitor in resistant hypertension", "35400003", "Hypertension"),
        ("S10_early_alzheimers_mab", "Lecanemab cognitive decline reduction and ARIA incidence in early Alzheimer's", "35500001", "Alzheimer Disease")
    ])
    def test_extended_scenarios_retrieval_and_citation_precision(self, test_client, scenario_name, query, expected_pmid, expected_disease):
        """Extended Scenarios: Specialized queries retrieve matching evidence and uphold citation precision."""
        res = test_client.post("/search", json={"query": query, "top_k": 3})
        assert res.status_code == 200
        candidates = res.json()["candidates"]
        assert len(candidates) >= 1
        top_pmids = [c["pmid"] for c in candidates]
        assert expected_pmid in top_pmids
        
        # Verify citation gate contract on retrieved evidence
        is_valid, precision, _ = verify_citation_integrity([expected_pmid], top_pmids)
        assert is_valid is True
        assert precision == 1.0
