"""
tests/unit/test_indexing.py
Unit tests for MedCPT dense embeddings, BM25 sparse index, Qdrant embedded collection,
payload filtering, and index manifest generation.
Implements test coverage for FEAT-R2-05, FEAT-R2-06, FEAT-R2-07, FEAT-R2-09.
"""
import os
import tempfile
import json
import hashlib
from pathlib import Path
import numpy as np
import pytest

from backend.app.retrieval.medcpt import MedCPTArticleEncoder, MedCPTQueryEncoder, EMBEDDING_DIM
from backend.app.retrieval.bm25 import BM25Index, tokenize_biomedical_text
from backend.app.services.qdrant_service import QdrantService
from pipelines.index_qdrant import (
    discover_model_revision,
    index_qdrant_collection,
    resolve_encoder_revision,
)


def test_model_revision_discovery_uses_local_cache_ref(tmp_path):
    model_cache = tmp_path / "models--ncbi--MedCPT-Article-Encoder"
    refs = model_cache / "refs"
    snapshot = model_cache / "snapshots" / "abc123revision"
    refs.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (refs / "main").write_text("abc123revision\n", encoding="utf-8")

    assert discover_model_revision("ncbi/MedCPT-Article-Encoder", tmp_path) == "abc123revision"


def test_embeddings_metadata_revision_takes_precedence(tmp_path, monkeypatch):
    embeddings_file = tmp_path / "article_embeddings.npy"
    metadata_file = tmp_path / "embeddings_meta.json"
    metadata_file.write_text(json.dumps({
        "model_name": "ncbi/MedCPT-Article-Encoder",
        "model_revision": "pinned-commit",
    }), encoding="utf-8")
    monkeypatch.setattr("pipelines.index_qdrant.discover_model_revision", lambda *_args: "cached-commit")

    assert resolve_encoder_revision(embeddings_file, "ncbi/MedCPT-Article-Encoder") == (
        "pinned-commit", "embeddings_metadata"
    )


def test_bm25_tokenization_preserves_hyphens_and_biomedical_terms():
    text = "Efficacy of SGLT-2 inhibitors and GLP-1 receptor agonists in COVID-19 and KRAS-G12C mutant cells."
    tokens = tokenize_biomedical_text(text)
    assert "sglt-2" in tokens
    assert "glp-1" in tokens
    assert "covid-19" in tokens
    assert "kras-g12c" in tokens
    # Common stopwords removed
    assert "of" not in tokens
    assert "and" not in tokens
    assert "in" not in tokens


def test_bm25_exact_match_and_ranking():
    records = [
        {
            "pmid": 101,
            "title": "Empagliflozin in Diabetes",
            "abstract": "Empagliflozin reduces cardiovascular death in type 2 diabetes.",
            "mesh_terms": ["Diabetes Mellitus, Type 2", "Empagliflozin"],
            "keywords": ["SGLT2", "empagliflozin"]
        },
        {
            "pmid": 102,
            "title": "Sotorasib in Lung Cancer",
            "abstract": "Sotorasib inhibits KRAS G12C in advanced non-small cell lung cancer.",
            "mesh_terms": ["Carcinoma, Non-Small-Cell Lung", "Sotorasib"],
            "keywords": ["KRAS G12C", "sotorasib"]
        },
        {
            "pmid": 103,
            "title": "Pediatric mRNA Vaccines",
            "abstract": "Safety and immunogenicity of BNT162b2 mRNA vaccine in young children.",
            "mesh_terms": ["COVID-19 Vaccines", "mRNA Vaccines"],
            "keywords": ["BNT162b2", "pediatric"]
        }
    ]
    bm25 = BM25Index.build_from_records(records)

    # Search for sotorasib
    results = bm25.search("sotorasib KRAS-G12C", top_k=2)
    assert len(results) > 0
    top_pmid, score = results[0]
    assert top_pmid == 102
    assert score > 0.0

    # Search for diabetes
    results_dm = bm25.search("empagliflozin", top_k=2)
    assert len(results_dm) > 0
    assert results_dm[0][0] == 101


def test_bm25_serialization_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        pkl_path = os.path.join(tmpdir, "bm25.pkl")
        records = [
            {"pmid": 201, "title": "Dapagliflozin and Heart Failure", "abstract": "Dapagliflozin reduces hospitalization."},
            {"pmid": 202, "title": "Semaglutide and Stroke", "abstract": "Semaglutide reduces stroke incidence."},
            {"pmid": 203, "title": "Placebo Control Trial", "abstract": "Placebo control group comparison."}
        ]
        bm25_orig = BM25Index.build_from_records(records)
        bm25_orig.save(pkl_path)

        bm25_loaded = BM25Index.load(pkl_path)
        assert bm25_loaded.vocab_size == bm25_orig.vocab_size
        assert bm25_loaded.avgdl == bm25_orig.avgdl
        assert bm25_loaded.pmids == [201, 202, 203]

        results = bm25_loaded.search("dapagliflozin", top_k=1)
        assert len(results) == 1
        assert results[0][0] == 201


def test_bm25_all_stopwords_query():
    records = [{"pmid": 301, "title": "Title", "abstract": "Abstract"}]
    bm25 = BM25Index.build_from_records(records)
    results = bm25.search("the and of in for", top_k=5)
    assert results == []


def test_medcpt_article_and_query_encoders():
    article_encoder = MedCPTArticleEncoder(batch_size=2)
    titles = ["Study on Metformin", "Study on Sotorasib"]
    abstracts = ["Metformin in diabetes.", "Sotorasib in NSCLC."]

    embeddings = article_encoder.encode_articles(titles, abstracts)
    assert embeddings.shape == (2, EMBEDDING_DIM)
    norms = np.linalg.norm(embeddings, axis=1)
    for n in norms:
        assert 0.99 <= n <= 1.01

    # Empty abstract fallback
    empty_abs_embs = article_encoder.encode_articles(["Title only"], [""])
    assert empty_abs_embs.shape == (1, EMBEDDING_DIM)
    assert not np.isnan(empty_abs_embs).any()

    # Query encoder
    query_encoder = MedCPTQueryEncoder()
    q_vec = query_encoder.encode_query("metformin cardiovascular outcomes")
    assert q_vec.shape == (EMBEDDING_DIM,)
    assert 0.99 <= np.linalg.norm(q_vec) <= 1.01


def test_qdrant_indexing_and_service_filters():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        qdrant_dir = tmp_path / "qdrant_storage"
        bm25_file = tmp_path / "bm25.pkl"
        manifest_file = tmp_path / "index_manifest.json"
        jsonl_file = tmp_path / "cleaned_pubmed.jsonl"
        embs_file = tmp_path / "article_embeddings.npy"

        records = [
            {
                "pmid": 401,
                "title": "Empagliflozin RCT",
                "abstract": "Renal protection in T2DM.",
                "year": 2023,
                "study_type": "Randomized Controlled Trial",
                "mesh_terms": ["Diabetes Mellitus, Type 2", "Empagliflozin"],
                "keywords": ["SGLT2", "renal"],
                "authors": ["Author A"],
                "journal": "NEJM",
                "publication_date": "2023-01-15",
                "doi": "10.1056/NEJMoa1515920"
            },
            {
                "pmid": 402,
                "title": "Semaglutide Observational",
                "abstract": "Cardiovascular risk reduction in real world.",
                "year": 2021,
                "study_type": "Observational",
                "mesh_terms": ["Diabetes Mellitus, Type 2", "Semaglutide"],
                "keywords": ["GLP-1", "MACE"],
                "authors": ["Author B"],
                "journal": "Lancet",
                "publication_date": "2021-06-20",
                "doi": "10.1016/S0140-6736(21)00823-1"
            },
            {
                "pmid": 403,
                "title": "Sotorasib Clinical Trial",
                "abstract": "KRAS G12C inhibition in NSCLC.",
                "year": 2022,
                "study_type": "Clinical Trial",
                "mesh_terms": ["Carcinoma, Non-Small-Cell Lung", "Sotorasib"],
                "keywords": ["KRAS", "NSCLC"],
                "authors": ["Author C"],
                "journal": "Nature Medicine",
                "publication_date": "2022-09-10",
                "doi": "10.1038/s41591-022-01923-4"
            }
        ]

        with open(jsonl_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        # Mock normalized embeddings for testing
        rng = np.random.RandomState(42)
        vectors = rng.randn(3, EMBEDDING_DIM).astype(np.float32)
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        np.save(embs_file, vectors)

        manifest = index_qdrant_collection(
            corpus_file=jsonl_file,
            embeddings_file=embs_file,
            qdrant_path=qdrant_dir,
            bm25_file=bm25_file,
            manifest_output_file=manifest_file,
            batch_size=10,
        )

        assert manifest["corpus"]["total_records"] == 3
        assert manifest["dense_index"]["dimension"] == 768
        assert manifest["corpus"]["sha256"] == hashlib.sha256(jsonl_file.read_bytes()).hexdigest()
        assert manifest["corpus"]["source_file"] == str(jsonl_file)
        assert manifest["build_timestamp_utc"]
        assert "model_revision" in manifest["dense_index"]
        assert manifest["vector_store"]["vector_names"] == ["dense", "bm25"]
        assert os.path.exists(manifest_file)

        # Query QdrantService
        service = QdrantService(storage_path=str(qdrant_dir), collection_name="medical_abstracts")
        try:
            # 1. Dense search without filter
            all_res = service.search_dense(vectors[0], limit=3)
            assert len(all_res) == 3
            assert all_res[0]["pmid"] == 401

            # 2. Year range filter (year >= 2022)
            filtered_year = service.search_dense(vectors[0], limit=3, year_min=2022)
            pmids_year = [r["pmid"] for r in filtered_year]
            assert 401 in pmids_year
            assert 403 in pmids_year
            assert 402 not in pmids_year

            # 3. Study type filter (Randomized Controlled Trial)
            filtered_st = service.search_dense(vectors[0], limit=3, study_types=["Randomized Controlled Trial"])
            assert len(filtered_st) == 1
            assert filtered_st[0]["pmid"] == 401

            # 4. MeSH term filter
            filtered_mesh = service.search_dense(vectors[0], limit=3, mesh_terms=["Sotorasib"])
            assert len(filtered_mesh) == 1
            assert filtered_mesh[0]["pmid"] == 403

            # 5. Get paper by PMID
            paper_payload = service.get_paper_by_pmid(401)
            assert paper_payload is not None
            assert paper_payload["title"] == "Empagliflozin RCT"

            # 6. Unmatched filter
            empty_res = service.search_dense(vectors[0], limit=3, year_min=2099)
            assert empty_res == []

            # 7. Qdrant-resident sparse representation is searchable and filtered.
            sparse_res = service.search_sparse("empagliflozin renal", limit=3)
            assert sparse_res[0]["pmid"] == 401
            assert service.search_sparse("empagliflozin", limit=3, year_min=2099) == []

        finally:
            service.close()
