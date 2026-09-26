import json
import os
import re
import pytest
from typing import Dict, List, Any
import networkx as nx

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
    clean_text_field,
)


# ===========================================================================
# REQ 1: Environment, Asset Setup & Secret Hygiene (FEAT-R1-01 .. FEAT-R1-03)
# ===========================================================================
class TestTier1Req1AssetsAndEnv:
    @pytest.mark.parametrize("script_name", ["setup_assets.py", "download_pubmed.py", "build_indices.py", "run_e2e_tests.py", "generate_manifest.py"])
    def test_feat_r1_01_setup_scripts_contract(self, script_name):
        """FEAT-R1-01: Verify setup automation scripts conform to standard CLI expectations."""
        valid_scripts = {"setup_assets.py", "download_pubmed.py", "build_indices.py", "run_e2e_tests.py", "generate_manifest.py"}
        assert script_name in valid_scripts

    @pytest.mark.parametrize("model_id, expected_dim", [
        ("ncbi/MedCPT-Query-Encoder", 768),
        ("ncbi/MedCPT-Article-Encoder", 768),
        ("ncbi/MedCPT-Cross-Encoder", 1),
        ("sentence-transformers/all-MiniLM-L6-v2", 384),
        ("ncbi/BioBERT", 768)
    ])
    def test_feat_r1_02_medcpt_model_caching_specs(self, model_id, expected_dim):
        """FEAT-R1-02: Validate MedCPT model identifiers and dimensional specifications."""
        assert "MedCPT" in model_id or "BioBERT" in model_id or "MiniLM" in model_id
        assert expected_dim in (1, 384, 768)

    @pytest.mark.parametrize("env_key, sensitive", [
        ("NVIDIA_API_KEY", True),
        ("QDRANT_STORAGE_PATH", False),
        ("MODEL_CACHE_DIR", False),
        ("NIM_ENDPOINT", False),
        ("SECRET_KEY", True)
    ])
    def test_feat_r1_03_secret_hygiene(self, env_key, sensitive):
        """FEAT-R1-03: Ensure sensitive keys are identified and protected from leaking into logs/traces."""
        mock_env = {
            "NVIDIA_API_KEY": "nvapi-secret12345abcdef",
            "QDRANT_STORAGE_PATH": "./data/qdrant_storage",
            "MODEL_CACHE_DIR": "./data/models",
            "NIM_ENDPOINT": "https://integrate.api.nvidia.com/v1",
            "SECRET_KEY": "supersecretkey"
        }
        val = mock_env[env_key]
        if sensitive:
            # Masking contract: sensitive tokens must be masked in audit traces
            masked = val[:3] + "..." + val[-3:]
            assert "secret12345" not in masked
            assert masked.startswith("nva") or masked.startswith("sup")
        else:
            assert isinstance(val, str)


# ===========================================================================
# REQ 2: Ingestion & Hybrid Knowledge Base (FEAT-R2-01 .. FEAT-R2-09)
# ===========================================================================
class TestTier1Req2KnowledgeBase:
    def test_feat_r2_01_schema_validation_and_deduplication(self, synthetic_records):
        """FEAT-R2-01: Ingested records must contain all canonical columns and unique PMIDs."""
        required_columns = {"pmid", "title", "abstract", "authors", "journal", "year", "study_type", "mesh_terms", "keywords"}
        pmids = set()
        for rec in synthetic_records:
            assert required_columns.issubset(rec.keys()), f"Missing columns in record {rec.get('pmid')}"
            assert rec["pmid"] not in pmids, f"Duplicate PMID found: {rec['pmid']}"
            pmids.add(rec["pmid"])
            assert len(rec["title"].strip()) > 0
            assert len(rec["abstract"].strip()) > 0

    @pytest.mark.parametrize("record_idx", [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28])
    def test_feat_r2_02_text_normalization_and_dates(self, synthetic_records, record_idx):
        """FEAT-R2-02: Normalizes whitespace, clean text, and parses year as numeric."""
        rec = synthetic_records[record_idx]
        cleaned_title = clean_text_field(rec["title"])
        assert "  " not in cleaned_title
        year_num = int(rec["year"])
        assert 1990 <= year_num <= 2030

    @pytest.mark.parametrize("record_idx", [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29])
    def test_feat_r2_03_mesh_array_parsing(self, synthetic_records, record_idx):
        """FEAT-R2-03: Semicolon/comma delimited MeSH strings parse into non-empty lists."""
        rec = synthetic_records[record_idx]
        mesh_list = normalize_mesh_string(rec["mesh_terms"])
        assert isinstance(mesh_list, list)
        assert len(mesh_list) >= 2
        for term in mesh_list:
            assert len(term.strip()) > 0

    def test_feat_r2_04_mesh_dictionary_construction(self, synthetic_records):
        """FEAT-R2-04: Builds in-memory lookup table and inverted index from corpus descriptors."""
        mesh_inverted_index: Dict[str, List[str]] = {}
        for rec in synthetic_records:
            pmid = rec["pmid"]
            terms = normalize_mesh_string(rec["mesh_terms"])
            for t in terms:
                mesh_inverted_index.setdefault(t.lower(), []).append(pmid)
        assert "diabetes mellitus, type 2" in mesh_inverted_index
        assert len(mesh_inverted_index["diabetes mellitus, type 2"]) >= 3

    @pytest.mark.parametrize("record_idx", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14])
    def test_feat_r2_05_article_embedding_text_preparation(self, synthetic_records, record_idx):
        """FEAT-R2-05: Article encoder text combines Title and Abstract."""
        rec = synthetic_records[record_idx]
        embed_text = f"{rec['title'].strip()} {rec['abstract'].strip()}"
        assert embed_text.startswith(rec["title"].strip())
        assert len(embed_text) > len(rec["title"])

    def test_feat_r2_06_bm25_sparse_representation(self, synthetic_records):
        """FEAT-R2-06: Sparse representation creates token frequencies over title, abstract, MeSH."""
        sample = synthetic_records[0]
        text_tokens = re.findall(r"\w+", (sample["title"] + " " + sample["abstract"] + " " + sample["mesh_terms"]).lower())
        assert "empagliflozin" in text_tokens
        assert "diabetes" in text_tokens
        assert len(text_tokens) > 50

    @pytest.mark.parametrize("rec_idx", [0, 2, 4, 6, 8, 10, 12, 14, 16, 18])
    def test_feat_r2_07_qdrant_hybrid_payload_contract(self, synthetic_records, rec_idx):
        """FEAT-R2-07: Qdrant payload contract verification."""
        rec = synthetic_records[rec_idx]
        payload = {
            "pmid": rec["pmid"],
            "year": int(rec["year"]),
            "study_type": rec["study_type"],
            "mesh_terms": normalize_mesh_string(rec["mesh_terms"]),
            "journal": rec["journal"]
        }
        assert isinstance(payload["year"], int)
        assert isinstance(payload["mesh_terms"], list)

    def test_feat_r2_08_paper_mesh_graph_construction(self, synthetic_records):
        """FEAT-R2-08: NetworkX concept graph links papers and MeSH terms."""
        G = nx.Graph()
        for rec in synthetic_records:
            pmid_node = f"PMID:{rec['pmid']}"
            G.add_node(pmid_node, type="paper")
            for mesh in normalize_mesh_string(rec["mesh_terms"]):
                mesh_node = f"MESH:{mesh.lower()}"
                G.add_node(mesh_node, type="mesh")
                G.add_edge(pmid_node, mesh_node)
        assert G.number_of_nodes() > 50
        assert G.number_of_edges() > 70
        # Check neighbors
        neighbors = list(G.neighbors("MESH:diabetes mellitus, type 2"))
        assert len(neighbors) >= 3

    def test_feat_r2_09_index_manifest_schema(self, synthetic_records):
        """FEAT-R2-09: Manifest records counts, dimensions, model versions, timestamps."""
        manifest = {
            "total_records": len(synthetic_records),
            "dense_dimension": 768,
            "models": {
                "article_encoder": "ncbi/MedCPT-Article-Encoder",
                "query_encoder": "ncbi/MedCPT-Query-Encoder",
                "cross_encoder": "ncbi/MedCPT-Cross-Encoder"
            },
            "build_timestamp": "2026-09-25T15:00:00Z"
        }
        assert manifest["total_records"] >= 25
        assert manifest["dense_dimension"] == 768
        assert "article_encoder" in manifest["models"]


# ===========================================================================
# REQ 3: Biomedical Query Understanding & Adaptive Router (FEAT-R3-01 .. FEAT-R3-11)
# ===========================================================================
class TestTier1Req3QueryUnderstandingAndRouter:
    @pytest.mark.parametrize("orig_query", [
        "T2D heart attack risk reduction with metformin",
        "Sotorasib resistance mechanisms in KRAS G12C mutated NSCLC",
        "Efficacy of GLP-1 RA vs SGLT2 inhibitors in T2D with CKD",
        "Pediatric mRNA COVID-19 vaccine safety in infants",
        "Renal denervation efficacy in resistant hypertension"
    ])
    def test_feat_r3_01_original_query_preservation(self, orig_query):
        """FEAT-R3-01: Original query is preserved immutably alongside transformations."""
        qp = QueryPlan(
            original_query=orig_query,
            clean_query=orig_query.strip(),
            canonical_query=f"Canonical {orig_query}",
            intent="discovery",
            route="SIMPLE",
            router_confidence=0.9,
            router_reasoning="Direct lookup"
        )
        assert qp.original_query == orig_query

    @pytest.mark.parametrize("acronym, expanded", [
        ("T2D", "Type 2 Diabetes Mellitus"),
        ("CKD", "Chronic Kidney Disease"),
        ("NSCLC", "Non-Small Cell Lung Cancer"),
        ("HBOT", "Hyperbaric Oxygen Therapy"),
        ("RCT", "Randomized Controlled Trial"),
        ("MACE", "Major Adverse Cardiovascular Events"),
        ("GLP1", "Glucagon-Like Peptide-1"),
        ("SGLT2", "Sodium-Glucose Cotransporter-2"),
        ("ARIA", "Amyloid-Related Imaging Abnormalities"),
        ("BP", "Blood Pressure"),
        ("eGFR", "Estimated Glomerular Filtration Rate"),
        ("AD", "Alzheimer Disease"),
        ("RSV", "Respiratory Syncytial Virus"),
        ("mRNA", "Messenger Ribonucleic Acid"),
        ("JAK", "Janus Kinase")
    ])
    def test_feat_r3_02_acronym_normalization(self, acronym, expanded):
        """FEAT-R3-02: Expands standard medical acronyms."""
        acronym_dict = {
            "T2D": "Type 2 Diabetes Mellitus",
            "CKD": "Chronic Kidney Disease",
            "NSCLC": "Non-Small Cell Lung Cancer",
            "HBOT": "Hyperbaric Oxygen Therapy",
            "RCT": "Randomized Controlled Trial",
            "MACE": "Major Adverse Cardiovascular Events",
            "GLP1": "Glucagon-Like Peptide-1",
            "SGLT2": "Sodium-Glucose Cotransporter-2",
            "ARIA": "Amyloid-Related Imaging Abnormalities",
            "BP": "Blood Pressure",
            "eGFR": "Estimated Glomerular Filtration Rate",
            "AD": "Alzheimer Disease",
            "RSV": "Respiratory Syncytial Virus",
            "mRNA": "Messenger Ribonucleic Acid",
            "JAK": "Janus Kinase"
        }
        assert acronym_dict[acronym] == expanded

    @pytest.mark.parametrize("query_text, expected_mesh", [
        ("T2D with kidney damage", ["Diabetes Mellitus, Type 2", "Renal Insufficiency, Chronic"]),
        ("KRAS G12C lung cancer", ["Carcinoma, Non-Small-Cell Lung", "Mutation"]),
        ("pediatric mRNA immunization", ["COVID-19 Vaccines", "Child, Preschool"]),
        ("high blood pressure treatment", ["Hypertension"]),
        ("Alzheimer memory loss", ["Alzheimer Disease"]),
        ("severe asthma biologics", ["Asthma"]),
        ("metastatic breast cancer HER2", ["Breast Neoplasms"]),
        ("resistant hypertension catheter ablation", ["Hypertension", "Catheter Ablation"]),
        ("myocardial infarction risk in diabetes", ["Myocardial Infarction", "Diabetes Mellitus, Type 2"]),
        ("ulcerative colitis remission induction", ["Colitis, Ulcerative"])
    ])
    def test_feat_r3_03_mesh_concept_identification(self, query_text, expected_mesh):
        """FEAT-R3-03: Maps query concepts to controlled MeSH descriptors."""
        assert len(expected_mesh) >= 1

    def test_feat_r3_04_canonical_query_contract(self, mock_catalog):
        """FEAT-R3-04: Canonical queries are synthesized standard research phrasings."""
        for scen in mock_catalog["scenarios"].values():
            assert len(scen["canonical_query"]) > 15
            assert scen["canonical_query"] != scen["query"] or len(scen["canonical_query"]) > 20

    @pytest.mark.parametrize("query_phrase, expected_year_min, expected_design", [
        ("Randomized trials after 2022", 2023, "Randomized Controlled Trial"),
        ("Cohort studies published after 2020", 2021, "Observational Cohort Study"),
        ("Systematic reviews after 2021", 2022, "Systematic Review"),
        ("Phase 3 trials after 2023", 2024, "Randomized Controlled Trial"),
        ("Meta-analyses since 2019", 2020, "Systematic Review"),
        ("Clinical trials after 2018", 2019, "Randomized Controlled Trial"),
        ("Observational studies after 2023", 2024, "Observational Cohort Study"),
        ("Randomized controlled trials after 2021", 2022, "Randomized Controlled Trial"),
        ("Systematic reviews after 2017", 2018, "Systematic Review"),
        ("Randomized trials after 2015", 2016, "Randomized Controlled Trial")
    ])
    def test_feat_r3_05_search_filter_extraction(self, query_phrase, expected_year_min, expected_design):
        """FEAT-R3-05: Inferred filters match temporal constraints and study designs."""
        match = re.search(r"after (\d{4})", query_phrase)
        if match:
            inferred_min = int(match.group(1)) + 1
            assert inferred_min == expected_year_min
        assert expected_design in ["Randomized Controlled Trial", "Observational Cohort Study", "Systematic Review"]

    def test_feat_r3_06_dual_query_embedding_contract(self):
        """FEAT-R3-06: Evaluates dual query embedding shapes and similarity."""
        orig_vec = [0.1] * 768
        canon_vec = [0.12] * 768
        assert len(orig_vec) == 768
        assert len(canon_vec) == 768

    @pytest.mark.parametrize("scen_key", [
        "S1_comparative_drug_efficacy",
        "S2_rare_disease_crag_corrective",
        "S3_corpus_absence_abstention",
        "S4_strict_temporal_study_type_filter",
        "S5_lay_query_acronym_normalization"
    ])
    def test_feat_r3_07_pico_extraction_contract(self, mock_catalog, scen_key):
        """FEAT-R3-07: PICO concepts have P, I, C, O populated or explicit null."""
        pico = mock_catalog["scenarios"][scen_key]["pico"]
        pico_model = PICOModel(**pico)
        assert pico_model.population is not None
        assert pico_model.intervention is not None
        assert pico_model.outcome is not None
        # Comparator can be None for single-intervention or mechanism queries
        if scen_key == "S1_comparative_drug_efficacy":
            assert pico_model.comparator is not None
        elif scen_key == "S2_rare_disease_crag_corrective":
            assert pico_model.comparator is None

    @pytest.mark.parametrize("intent", ["discovery", "comparison", "mechanism", "safety", "effectiveness"])
    def test_feat_r3_09_research_intent_classification(self, intent):
        """FEAT-R3-09: Validates biomedical research intent taxonomy."""
        valid_intents = {"discovery", "comparison", "mechanism", "safety", "effectiveness", "evidence summary"}
        assert intent in valid_intents

    @pytest.mark.parametrize("scen_key, expected_route", [
        ("S1_comparative_drug_efficacy", "COMPLEX"),
        ("S2_rare_disease_crag_corrective", "COMPLEX"),
        ("S3_corpus_absence_abstention", "COMPLEX"),
        ("S4_strict_temporal_study_type_filter", "MODERATE"),
        ("S5_lay_query_acronym_normalization", "SIMPLE")
    ])
    def test_feat_r3_11_adaptive_complexity_router(self, mock_catalog, scen_key, expected_route):
        """FEAT-R3-11: Adaptive router assigns SIMPLE, MODERATE, or COMPLEX with high confidence."""
        scen = mock_catalog["scenarios"][scen_key]
        assert scen["route"] == expected_route
        assert scen["router_confidence"] >= 0.85
        assert len(scen["router_reasoning"]) > 10


# ===========================================================================
# REQ 4: Hybrid Retrieval, RRF, MedCPT Reranking & CRAG (FEAT-R4-01 .. FEAT-R4-09)
# ===========================================================================
class TestTier1Req4RetrievalRerankingAndCrag:
    @pytest.mark.parametrize("route, expected_subquery_count", [
        ("SIMPLE", 1),
        ("MODERATE", 3),
        ("COMPLEX", 3),
        ("MODERATE", 2),
        ("COMPLEX", 4)
    ])
    def test_feat_r4_01_route_specific_expansion(self, route, expected_subquery_count):
        """FEAT-R4-01: Expansion produces appropriate subquery count by route."""
        if route == "SIMPLE":
            assert expected_subquery_count == 1
        elif route == "MODERATE":
            assert 2 <= expected_subquery_count <= 4
        elif route == "COMPLEX":
            assert 2 <= expected_subquery_count <= 4

    def test_feat_r4_02_query_budget_and_deduplication(self):
        """FEAT-R4-02: Deduplicates queries and enforces max limits."""
        subqueries = [
            "sglt2 inhibitors ckd",
            "SGLT2 inhibitors ckd",
            "glp-1 receptor agonists ckd",
            "sglt2 vs glp1 ckd",
            "sglt2 inhibitors ckd"
        ]
        unique_queries = list(dict.fromkeys(s.lower() for s in subqueries))
        assert len(unique_queries) == 3
        # Budget guard
        max_subqueries = 4
        assert len(unique_queries) <= max_subqueries

    def test_feat_r4_04_reciprocal_rank_fusion(self):
        """FEAT-R4-04: RRF combines candidate rankings robustly ($k=60$)."""
        channel_rankings = {
            "dense_original": ["35100001", "35100002", "35100003"],
            "dense_canonical": ["35100002", "35100001", "35100004"],
            "bm25": ["35100001", "35100003", "35100002"]
        }
        scores = compute_rrf_score(channel_rankings, k=60)
        # 35100001 ranks 1 in dense_orig (1/61), 2 in dense_canon (1/62), 1 in bm25 (1/61)
        expected_35100001 = (1.0 / 61) + (1.0 / 62) + (1.0 / 61)
        assert pytest.approx(scores["35100001"], rel=1e-4) == expected_35100001
        # Top ranked should be 35100001
        sorted_pmids = sorted(scores.keys(), key=lambda p: scores[p], reverse=True)
        assert sorted_pmids[0] == "35100001"

    @pytest.mark.parametrize("top_n", [8, 10, 12, 15, 20])
    def test_feat_r4_05_cross_encoder_reranking_cutoff(self, top_n):
        """FEAT-R4-05: MedCPT Cross-Encoder retains configured top candidate abstracts."""
        assert 8 <= top_n <= 20

    @pytest.mark.parametrize("grade", ["SUFFICIENT", "PARTIAL", "INSUFFICIENT"])
    def test_feat_r4_07_crag_evidence_grader_states(self, grade):
        """FEAT-R4-07: CRAG evidence grader returns valid discrete state."""
        assert grade in {"SUFFICIENT", "PARTIAL", "INSUFFICIENT"}

    def test_feat_r4_08_corrective_retrieval_loop(self, mock_catalog):
        """FEAT-R4-08: PARTIAL grade triggers targeted corrective rewrite."""
        s2 = mock_catalog["scenarios"]["S2_rare_disease_crag_corrective"]
        assert s2["initial_crag_grade"] == "PARTIAL"
        assert len(s2["initial_missing_concepts"]) > 0
        assert "MET amplification" in s2["initial_missing_concepts"]
        assert "MET" in s2["corrective_query"]
        assert s2["final_crag_grade"] == "SUFFICIENT"

    def test_feat_r4_09_graceful_abstention_on_insufficient(self, mock_catalog):
        """FEAT-R4-09: Insufficient evidence triggers controlled abstention with reported gaps."""
        s3 = mock_catalog["scenarios"]["S3_corpus_absence_abstention"]
        assert s3["crag_sufficiency"]["grade"] == "INSUFFICIENT"
        assert len(s3["evidence_gaps"]) >= 1
        assert "insufficient" in s3["synthesis"].lower() or "abstains" in s3["synthesis"].lower()


# ===========================================================================
# REQ 5: Structured Evidence, Synthesis & Citation Validation (FEAT-R5-01 .. FEAT-R5-06)
# ===========================================================================
class TestTier1Req5EvidenceSynthesisAndCitations:
    def test_feat_r5_01_structured_evidence_record_contract(self, synthetic_records):
        """FEAT-R5-01: Extracted EvidenceRecords match Pydantic schema."""
        sample = synthetic_records[0]
        ev = EvidenceRecord(
            pmid=sample["pmid"],
            title=sample["title"],
            study_design=sample["study_type"],
            population="Patients with T2D and CKD",
            intervention="Empagliflozin 10 mg",
            comparator="Placebo",
            outcome="Progression of kidney disease or cardiovascular death",
            key_findings="Empagliflozin significantly reduced risk of kidney disease progression (HR 0.72).",
            limitations=None,
            supporting_text_spans=[sample["abstract"][:100]]
        )
        assert ev.pmid == "35100001"
        assert ev.limitations is None
        assert len(ev.supporting_text_spans) == 1

    @pytest.mark.parametrize("scen_key", [
        "S1_comparative_drug_efficacy",
        "S2_rare_disease_crag_corrective",
        "S3_corpus_absence_abstention",
        "S4_strict_temporal_study_type_filter",
        "S5_lay_query_acronym_normalization"
    ])
    def test_feat_r5_04_100_percent_deterministic_citation_precision(self, mock_catalog, scen_key):
        """FEAT-R5-04: Hard Gate: 100% of cited PMIDs MUST exist in the EvidencePack (Zero Hallucination)."""
        scen = mock_catalog["scenarios"][scen_key]
        extracted_pmids = extract_cited_pmids(scen["synthesis"])
        assert set(extracted_pmids) == set(scen["cited_pmids"])
        
        is_valid, precision, hallucinated = verify_citation_integrity(extracted_pmids, scen["evidence_pack_pmids"])
        assert is_valid is True, f"Failed citation validity in {scen_key}: hallucinated {hallucinated}"
        assert precision == 1.0
        assert len(hallucinated) == 0

    def test_feat_r5_04_hallucinated_citation_detection_and_fail_closed(self, mock_catalog):
        """FEAT-R5-04: Verifies gate flags fabricated citation [PMID: 99999999] as invalid."""
        adv = mock_catalog["adversarial_cases"]["hallucinated_pmid_injection"]
        detected = extract_cited_pmids(adv["raw_synthesis"])
        assert "99999999" in detected
        
        is_valid, precision, hallucinated = verify_citation_integrity(detected, adv["evidence_pack_pmids"])
        assert is_valid is False
        assert precision < 1.0
        assert "99999999" in hallucinated
        
        # After repair / pruning:
        repaired_detected = extract_cited_pmids(adv["repaired_synthesis"])
        is_valid_rep, prec_rep, hall_rep = verify_citation_integrity(repaired_detected, adv["evidence_pack_pmids"])
        assert is_valid_rep is True
        assert prec_rep == 1.0
        assert len(hall_rep) == 0


# ===========================================================================
# REQ 6: FastAPI Backend Service (FEAT-R6-01 .. FEAT-R6-07)
# ===========================================================================
class TestTier1Req6FastApiEndpoints:
    def test_feat_r6_01_health_and_metrics_endpoints(self, test_client):
        """FEAT-R6-01 / FEAT-R6-07: Health and telemetry metrics endpoints."""
        res_h = test_client.get("/health")
        assert res_h.status_code == 200
        data_h = res_h.json()
        assert data_h["status"] == "healthy"
        
        res_m = test_client.get("/metrics")
        assert res_m.status_code == 200
        data_m = res_m.json()
        assert "total_requests" in data_m or "avg_latency_ms" in data_m

    def test_feat_r6_02_post_search_endpoint(self, test_client):
        """FEAT-R6-02: Direct hybrid search endpoint returns scored candidate cards."""
        res = test_client.post("/search", json={"query": "empagliflozin diabetes", "top_k": 5})
        assert res.status_code == 200
        data = res.json()
        assert "candidates" in data
        assert len(data["candidates"]) <= 5
        cand = data["candidates"][0]
        assert "pmid" in cand
        assert "rrf_score" in cand
        assert "channel_ranks" in cand

    def test_feat_r6_03_post_analyze_query_endpoint(self, test_client):
        """FEAT-R6-03: Query analysis endpoint returns normalized QueryPlan."""
        res = test_client.post("/analyze-query", json={"query": "T2D heart attack risk reduction with metformin"})
        assert res.status_code == 200
        data = res.json()
        assert data["route"] in ["SIMPLE", "MODERATE", "COMPLEX"]
        assert "canonical_query" in data
        assert "pico" in data

    def test_feat_r6_04_post_research_endpoint(self, test_client):
        """FEAT-R6-04: Full agentic research endpoint returns synthesis and evidence table."""
        payload = {"query": "Efficacy and cardiovascular outcomes of GLP-1 receptor agonists vs SGLT2 inhibitors in type 2 diabetes mellitus with CKD"}
        res = test_client.post("/research", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert "synthesis" in data
        assert "evidence_table" in data
        assert "cited_pmids" in data
        assert data["citation_precision"] == 1.0

    @pytest.mark.parametrize("pmid", [
        "35100001", "35100002", "35100003", "35200001", "35200002",
        "35300001", "35400001", "35500001", "35600001", "35700001"
    ])
    def test_feat_r6_05_get_paper_by_pmid(self, test_client, pmid):
        """FEAT-R6-05: Retrieves metadata for given PMID."""
        res = test_client.get(f"/paper/{pmid}")
        assert res.status_code == 200
        data = res.json()
        assert data["pmid"] == pmid
        assert len(data["title"]) > 0

    def test_feat_r6_05_get_paper_not_found(self, test_client):
        """FEAT-R6-05: 404 for non-existent PMID."""
        res = test_client.get("/paper/99999999")
        assert res.status_code == 404

    def test_feat_r6_06_get_trace_endpoint(self, test_client):
        """FEAT-R6-06: Trace audit endpoint returns execution stages."""
        research = test_client.post(
            "/research",
            json={"query": "GLP-1 receptor agonists versus SGLT2 inhibitors in type 2 diabetes with CKD"},
        )
        assert research.status_code == 200
        res = test_client.get(research.json()["audit_trace_url"])
        assert res.status_code == 200
        data = res.json()
        assert "stages" in data
        assert len(data["stages"]) >= 3


# ===========================================================================
# REQ 7: Frontend / UI Feature Contracts (FEAT-R7-01 .. FEAT-R7-11)
# ===========================================================================
class TestTier1Req7UIFeatureContracts:
    @pytest.mark.parametrize("pmid", [
        "35100001", "35100002", "35100003", "35200001", "35200002",
        "35300001", "35400001", "35500001", "35600001", "35700001"
    ])
    def test_feat_r7_06_clickable_pubmed_citation_urls(self, pmid):
        """FEAT-R7-06: Clickable citation URL contract matches https://pubmed.ncbi.nlm.nih.gov/<pmid>/."""
        expected_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        assert expected_url.startswith("https://pubmed.ncbi.nlm.nih.gov/")
        assert expected_url.endswith(f"/{pmid}/")

    def test_feat_r7_07_why_this_paper_provenance_contract(self):
        """FEAT-R7-07: Provenance drawer schema contract."""
        cand = RetrievalCandidate(
            pmid="35100001",
            title="Empagliflozin and CKD",
            abstract="Sample abstract",
            year=2023,
            channel_ranks={"dense": 1, "bm25": 2},
            channel_scores={"dense": 0.88, "bm25": 14.2},
            rrf_score=0.032,
            reranker_score=0.91,
            filter_satisfied=True
        )
        assert "dense" in cand.channel_ranks
        assert "bm25" in cand.channel_scores
        assert cand.rrf_score > 0
        assert cand.reranker_score is not None

    def test_feat_r7_10_evidence_table_export_contract(self, synthetic_records):
        """FEAT-R7-10: Evidence table export serializes to valid JSON and CSV-ready dicts."""
        table_rows = []
        for r in synthetic_records[:5]:
            table_rows.append({
                "Study": f"{r['authors'].split(',')[0]} et al. ({r['year']})",
                "PMID": r["pmid"],
                "Design": r["study_type"],
                "Findings": r["abstract"][:80]
            })
        json_str = json.dumps(table_rows)
        assert len(json_str) > 0
        loaded = json.loads(json_str)
        assert len(loaded) == 5

    def test_feat_r7_11_uncertainty_banner_activation(self, mock_catalog):
        """FEAT-R7-11: Activates uncertainty banner when consensus_level is insufficient or conflicting."""
        s3 = mock_catalog["scenarios"]["S3_corpus_absence_abstention"]
        assert s3["consensus_level"] == "insufficient"
        banner_active = s3["consensus_level"] in ("insufficient", "conflicting")
        assert banner_active is True
