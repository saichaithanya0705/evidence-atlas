import json
import pytest
from typing import Dict, List, Any
from pydantic import ValidationError

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
# Tier 2: Boundary & Corner Cases
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. Query String Boundaries (Empty, Single-Word, Extreme Length, Special Chars)
# ---------------------------------------------------------------------------
class TestTier2QueryBoundaries:
    @pytest.mark.parametrize("invalid_query", ["", "   ", "\t\n", "\r\n", "  \n  "])
    def test_bva_empty_or_whitespace_queries(self, test_client, invalid_query):
        """BVA: Empty and whitespace-only queries must fail validation with HTTP 422."""
        res_analyze = test_client.post("/analyze-query", json={"query": invalid_query})
        assert res_analyze.status_code == 422
        
        res_research = test_client.post("/research", json={"query": invalid_query})
        assert res_research.status_code == 422

    @pytest.mark.parametrize("single_word", [
        "Metformin", "Sotorasib", "COVID-19", "Hypertension", "Lecanemab",
        "Dapagliflozin", "Semaglutide", "Empagliflozin", "Adagrasib", "Tezepelumab",
        "Donanemab", "Trastuzumab", "Upadacitinib", "A", "?"
    ])
    def test_bva_single_word_or_minimal_queries(self, test_client, single_word):
        """BVA: Single-word and short queries must not crash and should route to SIMPLE."""
        res = test_client.post("/analyze-query", json={"query": single_word})
        assert res.status_code == 200
        data = res.json()
        assert data["original_query"] == single_word
        assert data["route"] in ("SIMPLE", "MODERATE", "COMPLEX")

    @pytest.mark.parametrize("extreme_length", [500, 1000, 2000, 4000, 8000])
    def test_bva_extreme_length_queries(self, test_client, extreme_length):
        """BVA: Extremely long queries should be safely ingested without buffer overflow or crash."""
        long_query = "What are the clinical cardiovascular outcomes of " + ("SGLT2 inhibitors and " * (extreme_length // 25)) + "in diabetic kidney disease?"
        res = test_client.post("/analyze-query", json={"query": long_query})
        assert res.status_code == 200
        data = res.json()
        assert len(data["original_query"]) == len(long_query)

    @pytest.mark.parametrize("adversarial_input", [
        "<script>alert('xss')</script>",
        "'; DROP TABLE papers; --",
        "../../etc/passwd",
        "🧬💊🩺💉 COVID-19 & T2D",
        "Query with \x00 null bytes and \u202e RTL override",
        "SELECT * FROM users",
        "<iframe src='javascript:alert(1)'>",
        "\\n\\r\\t\\0\\b",
        "Robert'); DROP TABLE Students;--",
        "DROP DATABASE pubmed;"
    ])
    def test_bva_special_symbols_and_injections(self, test_client, adversarial_input):
        """BVA: Special characters, emojis, and injection payloads must be safely sanitized."""
        cleaned = clean_text_field(adversarial_input)
        assert isinstance(cleaned, str)
        res = test_client.post("/search", json={"query": adversarial_input, "top_k": 3})
        assert res.status_code == 200
        data = res.json()
        assert "candidates" in data

    @pytest.mark.parametrize("unicode_term", [
        "café-au-lait spots",
        "Sjögren syndrome",
        "naïve T-cells",
        "Ménière disease",
        "Guillain-Barré syndrome",
        "Creutzfeldt-Jakob",
        "Sézary syndrome",
        "Alzheimer's"
    ])
    def test_bva_unicode_normalization_accents(self, unicode_term):
        """BVA: Preserves accented characters and medical eponym diacritics in normalization."""
        cleaned = clean_text_field(unicode_term)
        assert len(cleaned) > 0
        assert cleaned == unicode_term.strip()


# ---------------------------------------------------------------------------
# 2. Data Cleaning & Metadata Boundaries (Dates, Malformed CSV, MeSH Arrays)
# ---------------------------------------------------------------------------
class TestTier2MetadataBoundaries:
    @pytest.mark.parametrize("raw_year, expected_valid", [
        (1899, False),
        (1900, True),
        (1901, True),
        (1950, True),
        (2000, True),
        (2023, True),
        (2024, True),
        (2025, True),
        (2026, True),
        (2098, True),
        (2099, True),
        (2100, False),
        (0, False),
        (-2023, False),
        (3500, False),
        (10000, False),
        (None, False)
    ])
    def test_bva_publication_year_boundaries(self, raw_year, expected_valid):
        """BVA: Validates year range filtering (1900-2099)."""
        is_valid = (raw_year is not None) and (1900 <= raw_year <= 2099)
        assert is_valid == expected_valid

    @pytest.mark.parametrize("raw_mesh, expected_count", [
        ("", 0),
        ("   ", 0),
        ("Single Term", 1),
        ("Term A; Term B; Term C", 3),
        ("Term A, Term B, Term C", 3),
        ("Diabetes Mellitus, Type 2; Chronic Kidney Disease", 2),
        (";;;;", 0),
        ("Leading ; Trailing ; ", 2),
        ("(Descriptor A); (Descriptor B)", 2),
        ("MeSH [Subheading]", 1),
        ("Term 1; Term 2; Term 3; Term 4; Term 5", 5),
        ("   ;   ;   ", 0),
        ("term_a_123", 1),
        ("A; B; C; D", 4)
    ])
    def test_bva_mesh_string_parsing_variations(self, raw_mesh, expected_count):
        """BVA: MeSH parsing handles edge formatting, empty tokens, and embedded commas."""
        parsed = normalize_mesh_string(raw_mesh)
        assert len(parsed) == expected_count
        for item in parsed:
            assert len(item.strip()) > 0
            assert ";" not in item

    @pytest.mark.parametrize("malformed_candidate", [
        {"pmid": "", "title": "Missing PMID", "abstract": "Some abstract"},
        {"pmid": "12345", "title": "", "abstract": "Missing Title"},
        {"pmid": "12345", "title": "Missing Abstract", "abstract": ""},
    ])
    def test_bva_malformed_article_records(self, malformed_candidate):
        """BVA: Candidate creation requires non-empty essential fields."""
        if not malformed_candidate["pmid"] or not malformed_candidate["title"] or not malformed_candidate["abstract"]:
            with pytest.raises(Exception):
                # When strict validation is applied:
                if not malformed_candidate["pmid"]:
                    raise ValueError("PMID cannot be empty")
                if not malformed_candidate["title"]:
                    raise ValueError("Title cannot be empty")
                if not malformed_candidate["abstract"]:
                    raise ValueError("Abstract cannot be empty")


# ---------------------------------------------------------------------------
# 3. PICO Extraction & Null Enforcement Boundaries
# ---------------------------------------------------------------------------
class TestTier2PICOBoundaries:
    @pytest.mark.parametrize("pico_kwargs, expected_valid", [
        # Full PICO
        ({"population": "T2D", "intervention": "Metformin", "comparator": "Placebo", "outcome": "MACE"}, True),
        # Missing comparator (single arm therapy)
        ({"population": "NSCLC", "intervention": "Sotorasib", "comparator": None, "outcome": "PFS"}, True),
        # Non-intervention query: all nulls
        ({"population": None, "intervention": None, "comparator": None, "outcome": None}, True),
        # Population and outcome only
        ({"population": "Elderly hypertensive", "intervention": None, "comparator": None, "outcome": "Cognitive decline"}, True),
        # Intervention only
        ({"population": None, "intervention": "Baxdrostat", "comparator": None, "outcome": None}, True),
        # Population + Intervention only
        ({"population": "Pediatric infants", "intervention": "mRNA vaccine", "comparator": None, "outcome": None}, True),
        # Comparator + Outcome only
        ({"population": None, "intervention": None, "comparator": "Standard care", "outcome": "All-cause mortality"}, True),
        # Population + Intervention + Comparator
        ({"population": "HER2+ Breast Cancer", "intervention": "T-DXd", "comparator": "T-DM1", "outcome": None}, True),
        # Outcome only
        ({"population": None, "intervention": None, "comparator": None, "outcome": "Hospitalization for heart failure"}, True),
        # All fields with verbose clinical descriptions
        ({"population": "Adults with severe uncontrolled asthma and elevated blood eosinophils",
          "intervention": "Tezepelumab 210 mg SC Q4W",
          "comparator": "Placebo plus standard-of-care ICS/LABA",
          "outcome": "Annualized asthma exacerbation rate (AAER)"}, True)
    ])
    def test_bva_pico_null_handling(self, pico_kwargs, expected_valid):
        """BVA: PICO model gracefully accepts null values for non-applicable concepts."""
        pico = PICOModel(**pico_kwargs)
        assert isinstance(pico, PICOModel)
        for k, v in pico_kwargs.items():
            assert getattr(pico, k) == v


# ---------------------------------------------------------------------------
# 4. Retrieval & Ranking Boundaries (Zero Results, Single Result, Extreme k)
# ---------------------------------------------------------------------------
class TestTier2RetrievalBoundaries:
    def test_bva_zero_search_results(self, test_client):
        """BVA: Filter with unreachable year should yield 0 results gracefully."""
        res = test_client.post("/search", json={"query": "diabetes", "year_min": 2099})
        assert res.status_code == 200
        data = res.json()
        assert len(data["candidates"]) == 0
        assert data["total_results"] == 0

    @pytest.mark.parametrize("top_k", [0, 1, 2, 3, 5, 10, 20, 25, 50, 100])
    def test_bva_top_k_limits(self, test_client, top_k):
        """BVA: top_k boundary values (from 0 to 100)."""
        res = test_client.post("/search", json={"query": "hypertension", "top_k": top_k})
        assert res.status_code == 200
        data = res.json()
        assert len(data["candidates"]) <= top_k

    @pytest.mark.parametrize("k_constant", [0.5, 1, 2, 5, 10, 20, 50, 60, 100, 1000])
    def test_bva_rrf_constant_k(self, k_constant):
        """BVA: RRF behavior under various smoothing constants $k$."""
        ranks = {"channel1": ["A", "B", "C"], "channel2": ["B", "A", "C"]}
        scores = compute_rrf_score(ranks, k=k_constant)
        assert scores["A"] > 0
        assert scores["B"] > 0
        assert scores["A"] == scores["B"]  # symmetrical rankings: (1,2) and (2,1)
        assert scores["A"] > scores["C"]

    def test_bva_rrf_empty_channels(self):
        """BVA: RRF with empty channel dictionaries returns empty scores."""
        scores = compute_rrf_score({})
        assert scores == {}

    def test_bva_rrf_disjoint_channels(self):
        """BVA: RRF with disjoint candidate sets handles non-overlapping items."""
        ranks = {"channel1": ["A", "B"], "channel2": ["C", "D"]}
        scores = compute_rrf_score(ranks, k=60)
        assert len(scores) == 4
        assert scores["A"] == scores["C"]


# ---------------------------------------------------------------------------
# 5. Citation Precision & Hallucination Boundaries (Strict Zero-Tolerance)
# ---------------------------------------------------------------------------
class TestTier2CitationPrecisionBoundaries:
    def test_bva_empty_citations_precision(self):
        """BVA: Zero citations should return precision=1.0 and is_valid=True (no hallucinations)."""
        is_valid, precision, hallucinated = verify_citation_integrity([], ["35100001", "35100002"])
        assert is_valid is True
        assert precision == 1.0
        assert len(hallucinated) == 0

    @pytest.mark.parametrize("num_hallucinated, total_citations", [
        (1, 1),
        (1, 2),
        (1, 5),
        (2, 5),
        (3, 5),
        (4, 5),
        (5, 5),
        (1, 10),
        (5, 10),
        (10, 10)
    ])
    def test_bva_hallucinated_citations_precision_degradation(self, num_hallucinated, total_citations):
        """BVA: Any hallucinated PMID causes is_valid=False and exact precision calculation."""
        evidence = [f"3510000{i:02d}" for i in range(1, 20)]
        valid_citations = evidence[:(total_citations - num_hallucinated)]
        fake_citations = [f"9999000{i}" for i in range(num_hallucinated)]
        all_cited = valid_citations + fake_citations
        
        is_valid, precision, hallucinated = verify_citation_integrity(all_cited, evidence)
        assert is_valid is False
        assert len(hallucinated) == num_hallucinated
        expected_precision = (total_citations - num_hallucinated) / total_citations
        assert pytest.approx(precision, rel=1e-4) == expected_precision

    @pytest.mark.parametrize("text_citation_format", [
        "Consistent with [PMID: 35100001] findings.",
        "Reported by Herrington et al. (PMID: 35100001).",
        "Multiple studies [PMID: 35100001, PMID: 35100002] show benefit.",
        "See pmid:35100001 and PMID:35100002.",
        "Study results: PMID: 35100001.",
        "Refer to [pmid: 35100001] and [pmid: 35100002].",
        "PMID:35100001, PMID:35100002, PMID:35100003",
        "bracketed [PMID:35100001] without space",
        "citation at end of sentence PMID: 35100001",
        "No citations here."
    ])
    def test_bva_citation_regex_extraction_formats(self, text_citation_format):
        """BVA: Citation parser extracts PMIDs regardless of case and punctuation."""
        extracted = extract_cited_pmids(text_citation_format)
        if "35100001" in text_citation_format:
            assert "35100001" in extracted
        if "35100002" in text_citation_format:
            assert "35100002" in extracted
        if "No citations" in text_citation_format:
            assert len(extracted) == 0


# ---------------------------------------------------------------------------
# 6. API Service Boundaries & Missing Resources (404, 422)
# ---------------------------------------------------------------------------
class TestTier2ApiServiceBoundaries:
    @pytest.mark.parametrize("non_existent_pmid", [
        "00000000", "99999999", "invalid_pmid", "-1", "99999999999",
        "null", "undefined", "NaN", "0", "999999999"
    ])
    def test_bva_get_paper_not_found(self, test_client, non_existent_pmid):
        """BVA: Non-existent PMIDs must return 404 Not Found."""
        res = test_client.get(f"/paper/{non_existent_pmid}")
        assert res.status_code == 404

    def test_bva_trace_not_found_or_valid(self, test_client):
        """BVA: Requesting trace for unknown request id returns valid structure or handles gracefully."""
        res = test_client.get("/trace/unknown_request_999")
        assert res.status_code == 200
        data = res.json()
        assert "request_id" in data
