"""
tests/unit/test_graph_retrieval.py
Unit tests for NetworkX concept graph construction, traversal, and relation-based retrieval.
Implements test coverage for FEAT-R2-08.
"""
import os
import tempfile
import json
import pytest

from backend.app.retrieval.graph_retrieval import ConceptGraphRetriever
from pipelines.build_mesh_graph import build_concept_graph


@pytest.fixture
def sample_concept_graph():
    with tempfile.TemporaryDirectory() as tmpdir:
        jsonl_path = os.path.join(tmpdir, "corpus.jsonl")
        pickle_path = os.path.join(tmpdir, "mesh_graph.gpickle")
        json_path = os.path.join(tmpdir, "mesh_graph.json")
        manifest_path = os.path.join(tmpdir, "graph_manifest.json")

        records = [
            {
                "pmid": "1001",
                "title": "Study 1",
                "year": 2023,
                "study_type": "RCT",
                "mesh_terms": ["Diabetes Mellitus, Type 2", "Metformin", "Heart Failure"]
            },
            {
                "pmid": "1002",
                "title": "Study 2",
                "year": 2022,
                "study_type": "Observational",
                "mesh_terms": ["Diabetes Mellitus, Type 2", "Metformin", "Myocardial Infarction"]
            },
            {
                "pmid": "1003",
                "title": "Study 3",
                "year": 2021,
                "study_type": "RCT",
                "mesh_terms": ["Carcinoma, Non-Small-Cell Lung", "Sotorasib"]
            }
        ]
        with open(jsonl_path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        build_concept_graph(jsonl_path, pickle_path, json_path, manifest_path)
        retriever = ConceptGraphRetriever(pickle_path=pickle_path, json_path=json_path)
        yield retriever


def test_bipartite_paper_mesh_traversal(sample_concept_graph):
    # Paper -> MeSH terms
    mesh_terms_1001 = sample_concept_graph.get_mesh_terms_for_paper("1001")
    assert "Diabetes Mellitus, Type 2" in mesh_terms_1001
    assert "Metformin" in mesh_terms_1001
    assert "Heart Failure" in mesh_terms_1001

    # MeSH term -> Papers
    papers_for_metformin = sample_concept_graph.get_papers_for_mesh("Metformin")
    assert "1001" in papers_for_metformin
    assert "1002" in papers_for_metformin
    assert "1003" not in papers_for_metformin


def test_mesh_cooccurrence_and_expansion(sample_concept_graph):
    # In Study 1 and Study 2, Metformin co-occurs with Diabetes Mellitus, Type 2 twice
    cooccurring = sample_concept_graph.get_cooccurring_mesh_terms("Metformin")
    assert len(cooccurring) > 0
    top_term, weight = cooccurring[0]
    assert top_term == "Diabetes Mellitus, Type 2"
    assert weight >= 2.0

    # Expand query MeSH terms
    expanded = sample_concept_graph.expand_query_mesh_terms(["Metformin"], top_k=2)
    assert "Metformin" in expanded
    assert "Diabetes Mellitus, Type 2" in expanded


def test_related_papers_by_mesh(sample_concept_graph):
    # Paper 1001 and Paper 1002 share 'Diabetes Mellitus, Type 2' and 'Metformin'
    related = sample_concept_graph.get_related_papers_by_mesh("1001", top_k=5)
    assert len(related) > 0
    rel_pmid, sim_score = related[0]
    assert rel_pmid == "1002"
    assert sim_score > 0.0


def test_subgraph_extraction_for_ui(sample_concept_graph):
    subgraph_data = sample_concept_graph.extract_subgraph_for_papers(["1001"])
    assert "nodes" in subgraph_data
    assert "links" in subgraph_data
    node_ids = [n["id"] for n in subgraph_data["nodes"]]
    assert "paper:1001" in node_ids
    assert "mesh:Metformin" in node_ids


def test_missing_entities_graceful_handling(sample_concept_graph):
    assert sample_concept_graph.get_mesh_terms_for_paper("999999") == []
    assert sample_concept_graph.get_papers_for_mesh("NonExistentTerm") == []
    assert sample_concept_graph.get_cooccurring_mesh_terms("NonExistentTerm") == []
    assert sample_concept_graph.get_related_papers_by_mesh("999999") == []
