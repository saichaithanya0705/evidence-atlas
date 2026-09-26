"""
tests/unit/test_mesh_service.py
Unit tests for MeSH Dictionary service, synonym inverted index, and concept extraction.
Implements test coverage for FEAT-R2-04.
"""
import os
import tempfile
import json
import pytest

from backend.app.services.mesh_service import MeshDictionaryService
from pipelines.build_mesh_dict import build_mesh_dictionary


@pytest.fixture
def sample_mesh_dict():
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = os.path.join(tmpdir, "corpus.jsonl")
        dict_path = os.path.join(tmpdir, "mesh_dict.json")

        records = [
            {"pmid": "1", "mesh_terms": ["Diabetes Mellitus, Type 2", "Metformin"]},
            {"pmid": "2", "mesh_terms": ["Heart Failure", "Sodium-Glucose Transporter 2 Inhibitors"]},
            {"pmid": "3", "mesh_terms": ["Carcinoma, Non-Small-Cell Lung", "COVID-19 Vaccines"]},
        ]
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        build_mesh_dictionary(jsonl_path, dict_path)
        service = MeshDictionaryService(dict_path)
        yield service


def test_acronym_and_synonym_resolution(sample_mesh_dict):
    # Acronyms mapping to canonical inverted MeSH descriptors
    assert sample_mesh_dict.resolve_concept("t2dm") == "Diabetes Mellitus, Type 2"
    assert sample_mesh_dict.resolve_concept("T2DM") == "Diabetes Mellitus, Type 2"
    assert sample_mesh_dict.resolve_concept("type 2 diabetes") == "Diabetes Mellitus, Type 2"

    assert sample_mesh_dict.resolve_concept("sglt2i") == "Sodium-Glucose Transporter 2 Inhibitors"
    assert sample_mesh_dict.resolve_concept("sglt2 inhibitors") == "Sodium-Glucose Transporter 2 Inhibitors"

    assert sample_mesh_dict.resolve_concept("nsclc") == "Carcinoma, Non-Small-Cell Lung"
    assert sample_mesh_dict.resolve_concept("heart attack") == "Myocardial Infarction"
    assert sample_mesh_dict.resolve_concept("ckd") == "Renal Insufficiency, Chronic"


def test_concept_extraction_from_query(sample_mesh_dict):
    query = "Efficacy of metformin in t2dm patients with heart failure"
    matched_concepts = sample_mesh_dict.extract_mesh_concepts(query)

    assert "Metformin" in matched_concepts
    assert "Diabetes Mellitus, Type 2" in matched_concepts
    assert "Heart Failure" in matched_concepts


def test_unmatched_and_boundary_queries(sample_mesh_dict):
    assert sample_mesh_dict.resolve_concept("") is None
    assert sample_mesh_dict.resolve_concept(None) is None
    assert sample_mesh_dict.resolve_concept("unrelated_gibberish_12345") is None

    assert sample_mesh_dict.extract_mesh_concepts("") == []
    assert sample_mesh_dict.extract_mesh_concepts(None) == []
    assert sample_mesh_dict.extract_mesh_concepts("the and of in for") == []


def test_autocomplete_prefix_search(sample_mesh_dict):
    results = sample_mesh_dict.search_prefix("diab", limit=5)
    assert len(results) > 0
    assert any("Diabetes" in r for r in results)

    results_empty = sample_mesh_dict.search_prefix("xyznonexistent")
    assert results_empty == []


def test_descriptor_info_and_synonyms(sample_mesh_dict):
    info = sample_mesh_dict.get_descriptor_info("Diabetes Mellitus, Type 2")
    assert info is not None
    assert info["canonical_name"] == "Type 2 Diabetes Mellitus"

    synonyms = sample_mesh_dict.get_synonyms("Diabetes Mellitus, Type 2")
    assert "T2DM" in synonyms
    assert "Type 2 Diabetes" in synonyms
