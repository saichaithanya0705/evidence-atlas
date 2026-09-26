"""
tests/unit/test_preprocessing.py
Unit tests for data preprocessing pipeline, text normalization, and date/MeSH extraction.
Implements test coverage for FEAT-R2-01, FEAT-R2-02, FEAT-R2-03.
"""
import os
import tempfile
import pandas as pd
import pytest

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


def test_unicode_and_whitespace_normalization():
    # Ligature \ufb03 ("ffi"), non-breaking space \u00a0, multiple spaces
    raw_text = "The  e\ufb03cacy\u00a0of   drug    X."
    normalized = normalize_unicode_and_whitespace(raw_text)
    assert normalized == "The efficacy of drug X."


def test_scientific_notation_preservation():
    # Preserves chemical formulas, hyphens, plus signs, math symbols
    sci_text = "Serum Ca2+ levels and IL-6 response in KRAS-G12C mutant cells (p < 0.001)."
    normalized = normalize_unicode_and_whitespace(sci_text)
    assert "Ca2+" in normalized
    assert "IL-6" in normalized
    assert "KRAS-G12C" in normalized
    assert "p < 0.001" in normalized


def test_parse_date_and_year_standard():
    year, iso = parse_date_and_year("2023 Jan 15")
    assert year == 2023
    assert iso == "2023-01-15"

    year, iso = parse_date_and_year("2021-08-29")
    assert year == 2021
    assert iso == "2021-08-29"

    year, iso = parse_date_and_year("2019")
    assert year == 2019
    assert iso == "2019-01-01"


def test_parse_date_and_year_boundary_fallbacks():
    # Malformed or fuzzy strings
    year, iso = parse_date_and_year("Spring 2022")
    assert year == 2022
    assert iso is not None

    # Completely invalid date
    year, iso = parse_date_and_year("invalid_date_string")
    assert year is None
    assert iso is None

    # Empty string
    year, iso = parse_date_and_year("")
    assert year is None
    assert iso is None


def test_parse_mesh_terms_and_qualifiers():
    mesh_str = "Diabetes Mellitus, Type 2; Metformin/*drug therapy; *Heart Failure/prevention & control"
    clean_desc, full_desc = parse_mesh_terms(mesh_str)

    assert "Diabetes Mellitus, Type 2" in clean_desc
    assert "Metformin" in clean_desc
    assert "Heart Failure" in clean_desc

    assert "Metformin/drug therapy" in full_desc
    assert "Heart Failure/prevention & control" in full_desc


def test_parse_keyword_array():
    kw_str = "SGLT2 inhibitors; dapagliflozin; Heart Failure; T2DM"
    keywords = parse_keyword_array(kw_str)
    assert len(keywords) == 4
    assert "SGLT2 inhibitors" in keywords
    assert "dapagliflozin" in keywords
    assert "Heart Failure" in keywords
    assert "T2DM" in keywords


def test_parse_authors_array():
    authors_str = "Wiviott SD; Raz I; Bonaca MP"
    authors = parse_authors_array(authors_str)
    assert len(authors) == 3
    assert authors[0] == "Wiviott SD"
    assert authors[1] == "Raz I"


def test_infer_study_type():
    assert infer_study_type(["Randomized Controlled Trial"], "Title", "Abstract") == StudyType.RCT.value
    assert infer_study_type([], "Systematic Review of Treatments", "We reviewed 30 trials.") == StudyType.SYSTEMATIC_REVIEW.value
    assert infer_study_type([], "Meta-Analysis of GLP1 and SGLT2", "Abstract") == StudyType.META_ANALYSIS.value
    assert infer_study_type(
        ["Systematic Review"],
        "Systematic review and network meta-analysis",
        "We analyzed 28 randomized controlled trials.",
    ) == StudyType.SYSTEMATIC_REVIEW.value
    assert infer_study_type([], "Retrospective cohort study", "We observed 1000 patients.") == StudyType.OBSERVATIONAL.value
    assert infer_study_type([], "General paper", "General description.") == StudyType.OTHER.value


def test_preprocess_corpus_pipeline_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        input_csv = os.path.join(tmpdir, "raw_sample.csv")
        output_parquet = os.path.join(tmpdir, "cleaned.parquet")
        output_jsonl = os.path.join(tmpdir, "cleaned.jsonl")
        manifest_path = os.path.join(tmpdir, "manifest.json")

        # Create sample data with: 1 valid, 1 duplicate PMID, 1 duplicate text, 1 corrupt empty
        df_raw = pd.DataFrame([
            {
                "pmid": "10001",
                "title": "Study on Metformin in T2DM",
                "abstract": "Metformin reduces HbA1c and CV risk.",
                "authors": "Smith J; Doe A",
                "journal": "JAMA",
                "pub_date": " 2023-05-01 ",
                "year": "2023",
                "mesh_terms": "Diabetes Mellitus, Type 2; Metformin",
                "keywords": "T2DM; Metformin",
                "publication_type": "Randomized Controlled Trial",
                "doi": "10.1001/jama.2023.1001"
            },
            {  # Duplicate PMID
                "pmid": "10001",
                "title": "Study on Metformin duplicate",
                "abstract": "Duplicate abstract text",
                "authors": "Smith J",
                "journal": "JAMA",
                "pub_date": "2023",
                "year": "2023",
                "mesh_terms": "",
                "keywords": "",
                "publication_type": "",
                "doi": ""
            },
            {  # Duplicate text with different PMID
                "pmid": "10002",
                "title": "Study on Metformin in T2DM",
                "abstract": "Metformin reduces HbA1c and CV risk.",
                "authors": "Another Author",
                "journal": "Lancet",
                "pub_date": "2023",
                "year": "2023",
                "mesh_terms": "",
                "keywords": "",
                "publication_type": "",
                "doi": ""
            },
            {  # Corrupt empty title and abstract
                "pmid": "10003",
                "title": "",
                "abstract": "",
                "authors": "",
                "journal": "",
                "pub_date": "",
                "year": "",
                "mesh_terms": "",
                "keywords": "",
                "publication_type": "",
                "doi": ""
            },
            {  # Second valid record
                "pmid": "10004",
                "title": "Empagliflozin in Chronic Kidney Disease",
                "abstract": "Empagliflozin reduces progression of renal disease.",
                "authors": "Wanner C",
                "journal": "NEJM",
                "pub_date": "2022-09-15",
                "year": "2022",
                "mesh_terms": "Renal Insufficiency, Chronic; Empagliflozin",
                "keywords": "CKD; SGLT2",
                "publication_type": "Randomized Controlled Trial",
                "doi": "10.1056/NEJMoa1515920"
            }
        ])
        df_raw.to_csv(input_csv, index=False)

        stats = preprocess_corpus(input_csv, output_parquet, output_jsonl, manifest_path)

        assert stats["total_raw_rows"] == 5
        assert stats["clean_records_count"] == 2
        assert stats["dropped_duplicate_pmids"] == 1
        assert stats["dropped_duplicate_content"] == 1
        assert stats["dropped_corrupt_or_empty"] == 1

        assert os.path.exists(output_jsonl)
        assert os.path.exists(manifest_path)

        processed_rows = pd.read_json(output_jsonl, lines=True).set_index("pmid")
        assert processed_rows.loc[10001, "pubdate_raw"] == " 2023-05-01 "
        assert processed_rows.loc[10001, "publication_date"] == "2023-05-01"
        assert int(processed_rows.loc[10001, "year"]) == 2023

        # Validate with canonical Pydantic model
        df_clean = pd.read_json(output_jsonl, lines=True)
        for _, row in df_clean.iterrows():
            paper = Paper(**row.to_dict())
            assert paper.pmid in ["10001", "10004"]
            assert paper.embedding_text != ""
            metadata = PaperMetadata(**row.to_dict())
            assert metadata.pmid in ["10001", "10004"]
