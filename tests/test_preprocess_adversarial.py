"""
tests/test_preprocess_adversarial.py
Adversarial stress-testing suite for PubMed preprocessing pipeline and normalization logic.
Tests:
1. Malformed CSV inputs (missing titles, corrupt abstracts, non-numeric years, future/ancient years).
2. Diacritics, Unicode RTL, zero-width characters, and biomedical punctuation.
3. Duplicate PMIDs and identical abstract deduplication.
4. Empty and massive MeSH term lists.
5. Downstream pipeline compatibility and Pydantic schema validation boundaries.
"""
import json
import os
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

# Ensure root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.paper import Paper, PaperMetadata, StudyType
from pipelines.preprocess import (
    normalize_unicode_and_whitespace,
    parse_date_and_year,
    parse_mesh_terms,
    parse_keyword_array,
    parse_authors_array,
    infer_study_type,
    preprocess_corpus,
)
from pipelines.build_mesh_dict import build_mesh_dictionary
from pipelines.build_mesh_graph import build_concept_graph
from pipelines.build_bm25 import build_bm25_from_corpus
from pipelines.index_qdrant import index_qdrant_collection


class TestAdversarialMalformedInputs:
    """Stress tests for malformed, corrupt, or boundary CSV inputs."""

    def test_missing_title_with_valid_abstract(self):
        """A paper with empty title but valid abstract must be handled without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([{
                "pmid": "90001",
                "title": "",
                "abstract": "This abstract is present and contains clinical trial details.",
                "publication_date": "2023-01-01",
            }])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["clean_records_count"] == 1
            assert stats["dropped_corrupt_or_empty"] == 0

            with open(jsonl_path, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            assert rec["pmid"] == "90001"
            assert rec["title"] == ""
            assert rec["abstract"] == "This abstract is present and contains clinical trial details."
            assert rec["embedding_text"] == rec["abstract"]

            # Validate against canonical Pydantic model
            paper = Paper(**rec)
            assert paper.pmid == "90001"

    def test_missing_abstract_with_valid_title(self):
        """A paper with valid title but empty abstract must be handled without crashing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([{
                "pmid": "90002",
                "title": "A Randomized Trial of Drug Z in Hypertension",
                "abstract": "",
                "publication_date": "2023-02-01",
            }])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["clean_records_count"] == 1
            assert stats["dropped_corrupt_or_empty"] == 0

            with open(jsonl_path, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            assert rec["pmid"] == "90002"
            assert rec["title"] == "A Randomized Trial of Drug Z in Hypertension"
            assert rec["abstract"] == ""
            assert rec["embedding_text"] == rec["title"]

            paper = Paper(**rec)
            assert paper.pmid == "90002"

    def test_missing_both_title_and_abstract_dropped(self):
        """A row missing both title and abstract must be dropped gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([
                {"pmid": "90003", "title": "", "abstract": ""},
                {"pmid": "90004", "title": "   \n\t  ", "abstract": "    "},
            ])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["clean_records_count"] == 0
            assert stats["dropped_corrupt_or_empty"] == 2

    def test_corrupt_abstract_with_control_characters(self):
        """Abstract containing ASCII control characters, null bytes, and bell/escape chars."""
        dirty_text = "Background:\x00 Null byte\x07 Bell\x1b Escape\x08 Backspace\x0c Form feed."
        cleaned = normalize_unicode_and_whitespace(dirty_text)
        assert "\x00" not in cleaned
        assert "\x07" not in cleaned
        assert "\x1b" not in cleaned
        assert "\x08" not in cleaned
        assert "\x0c" not in cleaned
        assert "Background: Null byte Bell Escape Backspace Form feed." in cleaned

    def test_non_numeric_and_boundary_years(self):
        """Test date parser against non-numeric, boundary, and garbage strings."""
        cases = [
            ("unknown", None, None),
            ("N/A", None, None),
            ("TBD", None, None),
            ("NaN", None, None),
            ("Fall 2021", 2021, "2021-09-01"),
            ("circa 2022", 2022, "2022-01-01"),
            ("2023-XX-XX", 2023, "2023-01-01"),
        ]
        for raw, expected_year, _ in cases:
            year, iso = parse_date_and_year(raw)
            if expected_year is not None:
                assert year == expected_year, f"Failed for raw='{raw}', got year={year}"
            else:
                assert year is None, f"Expected None year for raw='{raw}', got {year}"

    def test_future_years_greater_than_2030(self):
        """Future years > 2030 should not produce an unhandled exception and year should be bounded."""
        future_dates = ["2031", "2045-06-15", "2099", "9999", "Year 3000"]
        for fd in future_dates:
            year, iso = parse_date_and_year(fd)
            if year is not None:
                assert year <= 2030, f"Future year {year} exceeded boundary for input '{fd}'"

    def test_ancient_years_less_than_1900(self):
        """Ancient years < 1900 should not crash and year should be sanitized to None."""
        ancient_dates = ["1850", "1776-07-04", "0", "-100", "Year 1500", "BCE 400"]
        for ad in ancient_dates:
            year, iso = parse_date_and_year(ad)
            assert year is None, f"Ancient year was not sanitized to None for '{ad}', got {year}"

    def test_corrupt_pmids(self):
        """PMIDs with non-digit strings, whitespace, or prefixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([
                {"pmid": "PMID: 98765432", "title": "Valid Title 1", "abstract": "Valid Abstract 1"},
                {"pmid": "  12345678  ", "title": "Valid Title 2", "abstract": "Valid Abstract 2"},
                {"pmid": "NO_DIGITS_HERE", "title": "Corrupt PMID", "abstract": "Valid Abstract 3"},
                {"pmid": "", "title": "Empty PMID", "abstract": "Valid Abstract 4"},
            ])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["total_raw_rows"] == 4
            assert stats["clean_records_count"] == 2
            assert stats["dropped_corrupt_or_empty"] == 2

            with open(jsonl_path, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            pmids = {r["pmid"] for r in records}
            assert "98765432" in pmids
            assert "12345678" in pmids
            # Assert all output PMIDs are strict strings of digits
            for p in pmids:
                assert isinstance(p, str)
                assert p.isdigit()


class TestAdversarialUnicodeAndBiomedicalPunctuation:
    """Stress tests for Unicode handling, RTL, diacritics, zero-width, and biomedical symbols."""

    def test_diacritics_and_special_latin_characters(self):
        """Tests accents, umlauts, cedillas, ligatures across multiple languages."""
        sample = "München café with naïve François in København; Sjögren’s syndrome and Creutzfeldt–Jakob."
        cleaned = normalize_unicode_and_whitespace(sample)
        assert "München" in cleaned
        assert "café" in cleaned
        assert "naïve" in cleaned
        assert "François" in cleaned
        assert "København" in cleaned
        assert "Sjögren" in cleaned
        assert "Creutzfeldt" in cleaned

    def test_decomposed_combining_diacritics_normalization(self):
        """Decomposed characters (e + combining acute) should normalize under NFKC."""
        decomposed = "cafe\u0301 and Mu\u0308nchen"
        cleaned = normalize_unicode_and_whitespace(decomposed)
        assert cleaned == "café and München"

    def test_unicode_rtl_and_bidi_characters(self):
        """RTL text (Arabic, Hebrew) and directional override characters must not crash."""
        rtl_samples = [
            "Clinical evaluation of تجربة سريرية in diabetes.",
            "Study in Israel: ניסוי קליני מבוקר for hypertension.",
            "Text with \u202e Right-To-Left Override and \u202c Pop Directional.",
            "Mixed \u200f RTL Mark and \u200e LTR Mark.",
        ]
        for s in rtl_samples:
            cleaned = normalize_unicode_and_whitespace(s)
            assert isinstance(cleaned, str)
            assert len(cleaned) > 0

    def test_zero_width_characters(self):
        """Zero-width spaces (ZWSP, ZWNJ, ZWJ, BOM) must not break processing."""
        zw_sample = "\ufeffTitle with\u200b zero-width\u200c non-joiner\u200d and\u2060 word joiner."
        cleaned = normalize_unicode_and_whitespace(zw_sample)
        assert isinstance(cleaned, str)
        assert "Title" in cleaned
        assert "non-joiner" in cleaned

    def test_biomedical_punctuation_preservation(self):
        """Crucial biomedical punctuation must remain completely intact."""
        biomed_terms = [
            "GLP-1 receptor agonist",
            "SGLT2 inhibitors",
            "anti-PD-1 / anti-PD-L1 immunotherapy",
            "HER2/neu positive breast carcinoma",
            "KRAS-G12C mutant colorectal cancer",
            "Serum Ca2+ and Mg2+ concentrations",
            "Interleukin-6 (IL-6) and TNF-α expression",
            "1,25-(OH)2D3 vitamin D3 metabolite",
            "[18F]FDG PET/CT imaging",
            "p < 0.001; 95% CI: 0.85-0.95; HR = 0.78",
            "mRNA-1273 and BNT162b2 vaccines",
        ]
        for term in biomed_terms:
            cleaned = normalize_unicode_and_whitespace(term)
            assert cleaned == term, f"Biomedical term was altered: expected '{term}', got '{cleaned}'"


class TestAdversarialDeduplication:
    """Stress tests for duplicate PMIDs, identical abstracts, and subtle duplicate cases."""

    def test_duplicate_pmid_handling(self):
        """Identical PMIDs must be deduplicated, keeping first row."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([
                {"pmid": "11111", "title": "Original First Entry", "abstract": "Abstract One"},
                {"pmid": "11111", "title": "Duplicate Second Entry", "abstract": "Abstract Two"},
                {"pmid": "  11111  ", "title": "Duplicate Third Entry with Whitespace", "abstract": "Abstract Three"},
            ])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["total_raw_rows"] == 3
            assert stats["clean_records_count"] == 1
            assert stats["dropped_duplicate_pmids"] == 2

            with open(jsonl_path, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            assert rec["title"] == "Original First Entry"

    def test_identical_title_and_abstract_deduplication(self):
        """Identical content under different PMIDs must be dropped as duplicate text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([
                {"pmid": "22221", "title": "Phase 3 Trial of Pembrolizumab", "abstract": "Pembrolizumab showed significant PFS."},
                {"pmid": "22222", "title": "Phase 3 Trial of Pembrolizumab", "abstract": "Pembrolizumab showed significant PFS."},
                {"pmid": "22223", "title": "phase 3 trial of pembrolizumab  ", "abstract": "  Pembrolizumab showed significant PFS.  "},
            ])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["total_raw_rows"] == 3
            assert stats["clean_records_count"] == 1
            assert stats["dropped_duplicate_content"] == 2

    def test_identical_abstract_with_different_title_behavior(self):
        """
        Adversarial inspection:
        What happens if two papers have different titles but exactly identical abstracts?
        The pipeline defines text_signature as f'{title.lower()}|||{abstract[:100].lower()}'.
        This test documents the actual empirical behavior: both are preserved.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([
                {"pmid": "33331", "title": "Initial Report on Compound X", "abstract": "This is an identical 500-word clinical abstract..."},
                {"pmid": "33332", "title": "Follow-up Report on Compound X", "abstract": "This is an identical 500-word clinical abstract..."},
            ])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["clean_records_count"] == 2
            assert stats["dropped_duplicate_content"] == 0

    def test_truncation_collision_on_abstract_first_100_chars(self):
        """
        Adversarial inspection of abstract[:100] signature:
        If two papers share the EXACT same title AND have identical first 100 characters in abstract,
        the pipeline falsely drops the second paper even though the rest of the abstract differs.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            common_lead = "Background: Cardiovascular disease remains the leading cause of morbidity and mortality worldwide today."
            assert len(common_lead) >= 100

            df = pd.DataFrame([
                {
                    "pmid": "44441",
                    "title": "Clinical Trial in Cardiology",
                    "abstract": common_lead + " Study A investigated Drug Alpha in 500 patients with positive outcomes.",
                },
                {
                    "pmid": "44442",
                    "title": "Clinical Trial in Cardiology",
                    "abstract": common_lead + " Study B investigated Drug Beta in 5000 patients with negative outcomes.",
                },
            ])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            # Confirmed empirical finding: Study B was dropped due to [:100] prefix hash collision
            assert stats["dropped_duplicate_content"] == 1
            assert stats["clean_records_count"] == 1


class TestAdversarialMeSHTermLists:
    """Stress tests for empty, malformed, and massive MeSH term lists."""

    def test_empty_and_corrupt_mesh_strings(self):
        """Empty, whitespace-only, and delimiter-only MeSH strings must produce empty lists."""
        empty_cases = ["", "   ", "; ; ;", "\n\n", None, float("nan")]
        for case in empty_cases:
            clean, full = parse_mesh_terms(case)
            assert clean == [], f"Expected empty clean list for {repr(case)}, got {clean}"
            assert full == [], f"Expected empty full list for {repr(case)}, got {full}"

    def test_malformed_qualifier_slashes(self):
        """MeSH terms with multiple slashes, trailing slashes, or missing base descriptor."""
        mesh_str = "/*NoBase; Diabetes Mellitus//complications/; Heart Failure/*therapy/prevention & control/*mortality"
        clean, full = parse_mesh_terms(mesh_str)
        assert "Diabetes Mellitus" in clean
        assert "Heart Failure" in clean
        assert "*NoBase" not in clean
        assert len(clean) >= 2

    def test_massive_mesh_term_list_performance(self):
        """A paper with 5,000 MeSH terms should parse in < 1.0s without memory or stack failure."""
        terms = [f"MeSH Concept Descriptor Number {i}/*drug therapy/genetics" for i in range(5000)]
        massive_str = "; ".join(terms)

        t0 = time.perf_counter()
        clean, full = parse_mesh_terms(massive_str)
        elapsed = time.perf_counter() - t0

        assert len(clean) == 5000
        assert len(full) == 5000
        assert elapsed < 1.0, f"Massive MeSH parsing took too long: {elapsed:.2f}s"

    def test_extreme_mesh_string_payload_in_pipeline(self):
        """Pipeline must handle a record with massive MeSH payload without breaking Parquet/JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            terms = [f"Descriptor_{i}/*qualifier_{i % 5}" for i in range(1000)]
            massive_mesh = "; ".join(terms)

            df = pd.DataFrame([{
                "pmid": "55555",
                "title": "Paper with 1,000 MeSH terms",
                "abstract": "Testing pipeline with large MeSH payload.",
                "mesh_terms": massive_mesh,
                "publication_date": "2023-01-01",
            }])
            df.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)
            assert stats["clean_records_count"] == 1

            with open(jsonl_path, "r", encoding="utf-8") as f:
                rec = json.loads(f.readline())
            paper = Paper(**rec)
            assert len(paper.mesh_terms) == 1000
            assert len(paper.mesh_qualifiers) == 1000


class TestAdversarialHostileCorpusEndToEnd:
    """Stress test with hostile multi-vector adversarial dataset and downstream pipeline verification."""

    def test_hostile_corpus_execution_and_downstream_integration(self):
        """
        Executes preprocess_corpus on a dataset combining all adversarial dimensions:
        - Malformed/missing headers
        - Corrupt records
        - Unicode RTL and zero-width
        - Biomedical punctuation
        - Duplicate PMIDs and duplicate text
        - Long texts
        - Feeds sanitized output to MeSH dict, MeSH graph, BM25, and Qdrant indexing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "hostile_pubmed.csv")
            parquet_path = os.path.join(tmpdir, "cleaned.parquet")
            jsonl_path = os.path.join(tmpdir, "cleaned.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            rows = [
                # Row 0: Valid baseline
                {
                    "pmid": "100001",
                    "title": "Efficacy of GLP-1 and SGLT2 in T2DM Patients",
                    "abstract": "Randomized controlled trial of semaglutide vs empagliflozin.",
                    "publication_date": "2023-04-12",
                    "mesh_terms": "Diabetes Mellitus, Type 2; SGLT2 Inhibitors",
                    "study_type": "Randomized Controlled Trial",
                },
                # Row 1: Missing title, valid abstract
                {
                    "pmid": "100002",
                    "title": "",
                    "abstract": "Valid abstract without title discussing anti-PD-1 therapy.",
                    "publication_date": "2022",
                    "mesh_terms": "Immunotherapy; Neoplasms",
                },
                # Row 2: Missing abstract, valid title
                {
                    "pmid": "100003",
                    "title": "Phase 2 Study of KRAS-G12C Inhibitor Sotorasib",
                    "abstract": "",
                    "publication_date": "2021-11-04",
                    "mesh_terms": "Proto-Oncogene Proteins p21(ras)",
                },
                # Row 3: Both empty (must drop)
                {
                    "pmid": "100004",
                    "title": "",
                    "abstract": "   \n\t",
                    "publication_date": "2020",
                },
                # Row 4: Duplicate PMID of Row 0 (must drop)
                {
                    "pmid": "100001",
                    "title": "Another title with same PMID",
                    "abstract": "Different abstract text.",
                    "publication_date": "2024",
                },
                # Row 5: Duplicate title & abstract of Row 0 with different PMID (must drop)
                {
                    "pmid": "100005",
                    "title": "Efficacy of GLP-1 and SGLT2 in T2DM Patients",
                    "abstract": "Randomized controlled trial of semaglutide vs empagliflozin.",
                    "publication_date": "2023",
                },
                # Row 6: Non-numeric year
                {
                    "pmid": "100006",
                    "title": "Study with Non-numeric Year",
                    "abstract": "Assessing blood pressure in resistant hypertension.",
                    "publication_date": "circa late 2022",
                    "mesh_terms": "Hypertension",
                },
                # Row 7: Future year 2045
                {
                    "pmid": "100007",
                    "title": "Future Study",
                    "abstract": "Abstract discussing future therapeutic targets.",
                    "publication_date": "2045-01-01",
                },
                # Row 8: Ancient year 1888
                {
                    "pmid": "100008",
                    "title": "Historical 19th Century Observation",
                    "abstract": "Early observations of glycosuria.",
                    "publication_date": "1888",
                },
                # Row 9: Unicode RTL + Diacritics + Zero-Width
                {
                    "pmid": "100009",
                    "title": "München Trial \ufeff\u200b with naïve patients and تجربة سريرية",
                    "abstract": "Evaluation of α-synuclein and β-amyloid in Alzheimer's disease with \u202e RLO text.",
                    "publication_date": "2023-08-15",
                    "mesh_terms": "Alzheimer Disease; Amyloid beta-Peptides",
                },
                # Row 10: ASCII control characters
                {
                    "pmid": "100010",
                    "title": "Paper with Control Chars\x07\x08",
                    "abstract": "Abstract with \x00 null bytes and \x1b escape characters.",
                    "publication_date": "2022-05-10",
                },
                # Row 11: Empty MeSH with noisy semicolons
                {
                    "pmid": "100011",
                    "title": "Paper with Empty MeSH",
                    "abstract": "Abstract for empty mesh verification.",
                    "publication_date": "2021",
                    "mesh_terms": " ; ; ; ; \n\n ; ",
                },
                # Row 12: Very long title (2,000 chars) and abstract (10,000 chars)
                {
                    "pmid": "100012",
                    "title": "Long Title: " + ("Extremely long text segment. " * 70),
                    "abstract": "Long Abstract: " + ("Biomedical findings reported in detail with statistical metrics. " * 150),
                    "publication_date": "2024-01-10",
                    "mesh_terms": "Cardiovascular Diseases; Biomarkers",
                },
            ]

            df_hostile = pd.DataFrame(rows)
            df_hostile.to_csv(csv_path, index=False)

            stats = preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)

            assert stats["total_raw_rows"] == 13
            assert stats["dropped_corrupt_or_empty"] == 1
            assert stats["dropped_duplicate_pmids"] == 1
            assert stats["dropped_duplicate_content"] == 1
            assert stats["clean_records_count"] == 10

            # Validate all clean records from JSONL against Pydantic models
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    paper = Paper(**rec)
                    metadata = PaperMetadata(**rec)
                    assert paper.pmid != ""
                    assert paper.embedding_text != ""

            # Verify downstream: MeSH dictionary
            mesh_dict_out = os.path.join(tmpdir, "mesh_dict.json")
            dict_res = build_mesh_dictionary(jsonl_path, mesh_dict_out)
            assert os.path.exists(mesh_dict_out)
            assert dict_res["total_descriptors"] > 0

            # Verify downstream: MeSH Graph
            graph_gp = os.path.join(tmpdir, "graph.gpickle")
            graph_json = os.path.join(tmpdir, "graph.json")
            gman = os.path.join(tmpdir, "graph_manifest.json")
            G = build_concept_graph(jsonl_path, graph_gp, graph_json, gman)
            assert os.path.exists(graph_gp)
            assert os.path.exists(graph_json)
            assert G.number_of_nodes() > 0

            # Verify downstream: BM25 Sparse Index
            bm25_pkl = Path(tmpdir) / "bm25.pkl"
            bm25 = build_bm25_from_corpus(Path(parquet_path), bm25_pkl)
            assert os.path.exists(bm25_pkl)
            assert len(bm25.pmids) == 10

            # Verify downstream: Qdrant Indexing
            embs = np.random.randn(10, 768).astype(np.float32)
            embs_path = Path(tmpdir) / "embs.npy"
            np.save(embs_path, embs)
            qdrant_dir = Path(tmpdir) / "qdrant"
            qman = Path(tmpdir) / "qman.json"
            index_qdrant_collection(Path(parquet_path), embs_path, qdrant_dir, bm25_pkl, qman)
            assert os.path.exists(qman)

    def test_pandas_dataframe_nan_deserialization_hazard(self):
        """
        Documents the empirical vulnerability:
        When converting a DataFrame with null year/doi/pubdate into dicts (e.g. df.to_dict(orient='records')),
        Pydantic v2 rejects year=float('nan') and coerces string fields to 'nan'.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "input.csv")
            parquet_path = os.path.join(tmpdir, "output.parquet")
            jsonl_path = os.path.join(tmpdir, "output.jsonl")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            df = pd.DataFrame([
                {"pmid": "70001", "title": "Valid Study", "abstract": "Abstract", "publication_date": "2023"},
                {"pmid": "70002", "title": "No Year Study", "abstract": "Abstract", "publication_date": "unknown"},
            ])
            df.to_csv(csv_path, index=False)
            preprocess_corpus(csv_path, parquet_path, jsonl_path, manifest_path)

            # Load into DataFrame (e.g., as test_preprocessing.py does)
            df_clean = pd.read_json(jsonl_path, lines=True)
            row_clean_0 = df_clean.iloc[0].to_dict()
            row_clean_1 = df_clean.iloc[1].to_dict()

            # Row 0 has finite year -> succeeds
            p0 = Paper(**row_clean_0)
            assert p0.year == 2023

            # Row 1 has year=NaN -> Pydantic raises ValidationError
            with pytest.raises(Exception) as exc_info:
                Paper(**row_clean_1)
            assert "Input should be a finite number" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main(["-s", "-v", __file__])
