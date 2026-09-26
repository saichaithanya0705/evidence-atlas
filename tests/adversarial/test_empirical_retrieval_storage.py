"""
tests/adversarial/test_empirical_retrieval_storage.py
Empirical challenge test suite for Milestone 1 retrieval and storage subsystems:
1. Direct Qdrant embedded collection queries (768-dim, cosine range, payload filters).
2. Direct BM25 sparse queries (exact drug keywords: Semaglutide, Sotorasib, Empagliflozin, hyphenation, stopwords).
3. Direct NetworkX graph queries (bipartite traversal, co-occurrence, Jaccard similarity math).
"""

import os
import sys
import json
import pickle
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from qdrant_client import QdrantClient, models
from networkx.readwrite import json_graph

# Ensure workspace root in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.retrieval.bm25 import BM25Index, tokenize_biomedical_text
from backend.app.retrieval.graph_retrieval import ConceptGraphRetriever
from backend.app.services.qdrant_service import QdrantService


# ============================================================================
# 1. EMPIRICAL CHALLENGE: Qdrant Embedded Collection (data/qdrant_storage)
# ============================================================================

class TestEmpiricalQdrantStorage:
    STORAGE_PATH = PROJECT_ROOT / "data" / "qdrant_storage"
    COLLECTION_NAME = "medical_abstracts"

    @classmethod
    def setup_class(cls):
        assert cls.STORAGE_PATH.exists(), f"Qdrant storage path missing: {cls.STORAGE_PATH}"

    def test_direct_qdrant_client_connection_and_stats(self):
        """Challenge direct QdrantClient embedded connection and collection existence."""
        client = QdrantClient(path=str(self.STORAGE_PATH))
        try:
            collections = client.get_collections().collections
            names = [c.name for c in collections]
            assert self.COLLECTION_NAME in names, f"Collection '{self.COLLECTION_NAME}' not in {names}"

            col_info = client.get_collection(self.COLLECTION_NAME)
            print(f"\n[Qdrant] Collection: {self.COLLECTION_NAME}, Points: {col_info.points_count}")
            assert col_info.points_count == 30, f"Expected 30 points, found {col_info.points_count}"
        finally:
            client.close()

    def test_qdrant_vector_dimensions_and_norm_invariants(self):
        """Verify EVERY point stored in Qdrant has exact 768-dim vector and unit norm."""
        client = QdrantClient(path=str(self.STORAGE_PATH))
        try:
            # Scroll all points with vectors
            points, _ = client.scroll(
                collection_name=self.COLLECTION_NAME,
                limit=100,
                with_vectors=True,
                with_payload=True
            )
            assert len(points) == 30, f"Expected 30 points in scroll, got {len(points)}"

            for pt in points:
                assert isinstance(pt.vector, dict), "Hybrid collection must expose named vectors"
                assert "dense" in pt.vector and "bm25" in pt.vector
                vec = np.array(pt.vector["dense"], dtype=np.float32)
                # Invariant 1: dimension must be 768
                assert vec.shape == (768,), f"PMID {pt.id} vector dimension mismatch: {vec.shape} != (768,)"
                # Invariant 2: values must be finite floats
                assert np.isfinite(vec).all(), f"PMID {pt.id} vector contains NaN/Inf"
                # Invariant 3: L2 unit norm check (MedCPT article encoder normalizes vectors)
                norm = np.linalg.norm(vec)
                assert abs(norm - 1.0) < 1e-3, f"PMID {pt.id} vector not unit normalized: norm={norm}"
            print(f"[Qdrant] Verified all {len(points)} points have exact 768 dimensions and L2 unit norm.")
        finally:
            client.close()

    def test_qdrant_cosine_similarity_range_and_identity_match(self):
        """Verify cosine similarity behaves correctly: self-query ~ 1.0, random vectors in [-1, 1]."""
        client = QdrantClient(path=str(self.STORAGE_PATH))
        try:
            # Retrieve point 0 vector
            points, _ = client.scroll(collection_name=self.COLLECTION_NAME, limit=1, with_vectors=True)
            target_pt = points[0]
            assert isinstance(target_pt.vector, dict) and "dense" in target_pt.vector
            target_vec = target_pt.vector["dense"]

            # Search with exact vector of target_pt
            res_identity = client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=target_vec,
                using="dense",
                limit=5
            ).points

            assert len(res_identity) > 0
            top_hit = res_identity[0]
            print(f"[Qdrant] Identity search top hit: PMID={top_hit.id}, score={top_hit.score:.6f}")
            assert top_hit.id == target_pt.id, f"Expected top hit to be {target_pt.id}, got {top_hit.id}"
            assert top_hit.score >= 0.999, f"Identity cosine similarity should be ~1.0, got {top_hit.score}"

            # Search with synthetic random unit vector
            rng = np.random.default_rng(42)
            random_vec = rng.normal(size=768)
            random_vec = (random_vec / np.linalg.norm(random_vec)).tolist()

            res_random = client.query_points(
                collection_name=self.COLLECTION_NAME,
                query=random_vec,
                using="dense",
                limit=30
            ).points

            for pt in res_random:
                assert -1.0001 <= pt.score <= 1.0001, f"Cosine score out of bounds [-1, 1]: {pt.score}"

            print(f"[Qdrant] Verified cosine similarity bounds for all {len(res_random)} hits against random vector.")
        finally:
            client.close()

    def test_qdrant_payload_filters_year_and_study_type(self):
        """Empirically test hard payload filters: year >= 2022, study_type == 'Randomized Controlled Trial'."""
        client = QdrantClient(path=str(self.STORAGE_PATH))
        try:
            # 1. Filter: year >= 2022
            filter_year = models.Filter(
                must=[models.FieldCondition(key="year", range=models.Range(gte=2022))]
            )
            pts_year, _ = client.scroll(
                collection_name=self.COLLECTION_NAME,
                scroll_filter=filter_year,
                limit=100,
                with_payload=True
            )
            assert len(pts_year) > 0, "No records found for year >= 2022"
            for pt in pts_year:
                yr = pt.payload.get("year")
                assert yr is not None and yr >= 2022, f"PMID {pt.id} leaked through filter with year={yr}"
            print(f"[Qdrant] Filter `year >= 2022` passed: {len(pts_year)} compliant records.")

            # 2. Filter: study_type == 'Randomized Controlled Trial'
            filter_rct = models.Filter(
                must=[models.FieldCondition(key="study_type", match=models.MatchValue(value="Randomized Controlled Trial"))]
            )
            pts_rct, _ = client.scroll(
                collection_name=self.COLLECTION_NAME,
                scroll_filter=filter_rct,
                limit=100,
                with_payload=True
            )
            manifest_path = PROJECT_ROOT / "data" / "manifests" / "index_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_rct = manifest["corpus"]["study_type_breakdown"]["Randomized Controlled Trial"]
            assert len(pts_rct) == expected_rct, (
                f"Expected {expected_rct} RCTs per manifest, got {len(pts_rct)}"
            )
            for pt in pts_rct:
                st = pt.payload.get("study_type")
                assert st == "Randomized Controlled Trial", f"PMID {pt.id} leaked through RCT filter: {st}"
            print(f"[Qdrant] Filter `study_type == RCT` passed: {len(pts_rct)} compliant records.")

            # 3. Combined Filter: year >= 2022 AND study_type == 'Randomized Controlled Trial'
            filter_combined = models.Filter(
                must=[
                    models.FieldCondition(key="year", range=models.Range(gte=2022)),
                    models.FieldCondition(key="study_type", match=models.MatchValue(value="Randomized Controlled Trial")),
                ]
            )
            pts_combined, _ = client.scroll(
                collection_name=self.COLLECTION_NAME,
                scroll_filter=filter_combined,
                limit=100,
                with_payload=True
            )
            assert len(pts_combined) > 0, "No records found for combined filter"
            for pt in pts_combined:
                assert pt.payload["year"] >= 2022
                assert pt.payload["study_type"] == "Randomized Controlled Trial"
            print(f"[Qdrant] Combined Filter passed: {len(pts_combined)} strictly compliant records.")

            # 4. Adversarial empty filters (future year, past year, bogus study type)
            filter_future = models.Filter(
                must=[models.FieldCondition(key="year", range=models.Range(gte=2099))]
            )
            pts_empty, _ = client.scroll(collection_name=self.COLLECTION_NAME, scroll_filter=filter_future, limit=10)
            assert len(pts_empty) == 0

            filter_bogus = models.Filter(
                must=[models.FieldCondition(key="study_type", match=models.MatchValue(value="NonExistentType_999"))]
            )
            pts_bogus, _ = client.scroll(collection_name=self.COLLECTION_NAME, scroll_filter=filter_bogus, limit=10)
            assert len(pts_bogus) == 0
            print("[Qdrant] Adversarial non-matching filters correctly yielded 0 records.")
        finally:
            client.close()


# ============================================================================
# 2. EMPIRICAL CHALLENGE: BM25 Sparse Index (data/processed/bm25_index.pkl)
# ============================================================================

class TestEmpiricalBM25Index:
    BM25_PATH = PROJECT_ROOT / "data" / "processed" / "bm25_index.pkl"
    CORPUS_PATH = PROJECT_ROOT / "data" / "processed" / "cleaned_pubmed.parquet"

    @classmethod
    def setup_class(cls):
        assert cls.BM25_PATH.exists(), f"BM25 index path missing: {cls.BM25_PATH}"
        assert cls.CORPUS_PATH.exists(), f"Cleaned parquet missing: {cls.CORPUS_PATH}"
        cls.df = pd.read_parquet(cls.CORPUS_PATH)
        cls.bm25_index = BM25Index.load(cls.BM25_PATH)

    def test_direct_bm25_unpickling_and_attributes(self):
        """Directly verify deserialized BM25 properties and token vocabulary."""
        with open(self.BM25_PATH, "rb") as f:
            raw_data = pickle.load(f)
        assert "bm25" in raw_data
        assert "pmids" in raw_data
        assert "avgdl" in raw_data
        assert "vocab_size" in raw_data

        assert len(raw_data["pmids"]) == 30
        assert raw_data["vocab_size"] > 1000
        assert raw_data["avgdl"] > 100
        print(f"\n[BM25] Index stats: {len(raw_data['pmids'])} documents, {raw_data['vocab_size']} vocabulary terms, avgdl={raw_data['avgdl']:.2f}")

    def test_exact_drug_keyword_matching_semaglutide(self):
        """Query 'Semaglutide' and verify top hit contains Semaglutide in text."""
        hits = self.bm25_index.search("Semaglutide", top_k=5)
        assert len(hits) > 0, "No BM25 hits for 'Semaglutide'"
        top_pmid, top_score = hits[0]
        assert top_score > 0.0

        row = self.df[self.df["pmid"].astype(str) == str(top_pmid)].iloc[0]
        text_content = f"{row['title']} {row['abstract']} {' '.join(row['mesh_terms'])}".lower()
        print(f"[BM25] 'Semaglutide' Top 1 hit: PMID {top_pmid} (score: {top_score:.3f}) - '{row['title']}'")
        assert "semaglutide" in text_content, f"PMID {top_pmid} does not contain 'semaglutide'"

    def test_exact_drug_keyword_matching_sotorasib(self):
        """Query 'Sotorasib' and verify top hit contains Sotorasib in text."""
        hits = self.bm25_index.search("Sotorasib", top_k=5)
        assert len(hits) > 0, "No BM25 hits for 'Sotorasib'"
        top_pmid, top_score = hits[0]
        assert top_score > 0.0

        row = self.df[self.df["pmid"].astype(str) == str(top_pmid)].iloc[0]
        text_content = f"{row['title']} {row['abstract']} {' '.join(row['mesh_terms'])}".lower()
        print(f"[BM25] 'Sotorasib' Top 1 hit: PMID {top_pmid} (score: {top_score:.3f}) - '{row['title']}'")
        assert "sotorasib" in text_content, f"PMID {top_pmid} does not contain 'sotorasib'"

    def test_exact_drug_keyword_matching_empagliflozin(self):
        """Query 'Empagliflozin' and verify top hit contains Empagliflozin in text."""
        hits = self.bm25_index.search("Empagliflozin", top_k=5)
        assert len(hits) > 0, "No BM25 hits for 'Empagliflozin'"
        top_pmid, top_score = hits[0]
        assert top_score > 0.0

        row = self.df[self.df["pmid"].astype(str) == str(top_pmid)].iloc[0]
        text_content = f"{row['title']} {row['abstract']} {' '.join(row['mesh_terms'])}".lower()
        print(f"[BM25] 'Empagliflozin' Top 1 hit: PMID {top_pmid} (score: {top_score:.3f}) - '{row['title']}'")
        assert "empagliflozin" in text_content, f"PMID {top_pmid} does not contain 'empagliflozin'"

    def test_bm25_adversarial_queries_and_tokenization(self):
        """Challenge BM25 with case variation, hyphenated entities, stopwords, and gibberish."""
        # Case variation: semaglutide vs Semaglutide vs SEMAGLUTIDE
        h1 = self.bm25_index.search("semaglutide")
        h2 = self.bm25_index.search("Semaglutide")
        h3 = self.bm25_index.search("SEMAGLUTIDE")
        assert h1 == h2 == h3, "Case variation produced differing BM25 rankings or scores"

        # Hyphenated and multi-token biomedical entity preservation
        for term in ["GLP-1", "COVID-19", "KRAS G12C", "SGLT2"]:
            h = self.bm25_index.search(term, top_k=3)
            assert len(h) > 0, f"Biomedical term '{term}' yielded zero BM25 hits"
            assert h[0][1] > 0.0

        # Stopwords only: returns empty list cleanly
        h_stop = self.bm25_index.search("the and of in for with on at to by")
        assert h_stop == [], f"Stopwords query should return empty, got {h_stop}"

        # Empty / whitespace queries
        assert self.bm25_index.search("") == []
        assert self.bm25_index.search("    ") == []

        # Out-of-vocabulary / gibberish: returns empty list cleanly
        h_gibberish = self.bm25_index.search("xyzzygibberishdrugnotfound9999")
        assert h_gibberish == [], f"Gibberish query should return empty, got {h_gibberish}"

        print("[BM25] All adversarial queries (case, hyphens, stopwords, blanks, OOV) passed gracefully.")


# ============================================================================
# 3. EMPIRICAL CHALLENGE: NetworkX Concept Graph (mesh_graph.gpickle / json)
# ============================================================================

class TestEmpiricalNetworkXGraph:
    PICKLE_PATH = PROJECT_ROOT / "data" / "processed" / "mesh_graph.gpickle"
    JSON_PATH = PROJECT_ROOT / "data" / "processed" / "mesh_graph.json"

    @classmethod
    def setup_class(cls):
        assert cls.PICKLE_PATH.exists(), f"Graph pickle missing: {cls.PICKLE_PATH}"
        assert cls.JSON_PATH.exists(), f"Graph JSON missing: {cls.JSON_PATH}"
        cls.retriever = ConceptGraphRetriever(pickle_path=str(cls.PICKLE_PATH), json_path=str(cls.JSON_PATH))

    def test_direct_graph_loading_and_isomorphism(self):
        """Verify graph loading from both binary pickle and node-link JSON."""
        # 1. Load pickle directly
        with open(self.PICKLE_PATH, "rb") as f:
            g_pkl = pickle.load(f)
        # 2. Load JSON directly
        with open(self.JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        g_json = json_graph.node_link_graph(data)

        print(f"\n[Graph] Pickle Graph: {g_pkl.number_of_nodes()} nodes, {g_pkl.number_of_edges()} edges")
        print(f"[Graph] JSON Graph: {g_json.number_of_nodes()} nodes, {g_json.number_of_edges()} edges")

        assert g_pkl.number_of_nodes() == 127
        assert g_json.number_of_nodes() == 127
        assert g_pkl.number_of_edges() == 413
        assert g_json.number_of_edges() == 413

        # Node partitioning: exactly 30 papers and 97 MeSH descriptors
        paper_nodes = [n for n in g_pkl.nodes if str(n).startswith("paper:")]
        mesh_nodes = [n for n in g_pkl.nodes if str(n).startswith("mesh:")]
        assert len(paper_nodes) == 30, f"Expected 30 paper nodes, got {len(paper_nodes)}"
        assert len(mesh_nodes) == 97, f"Expected 97 MeSH nodes, got {len(mesh_nodes)}"

    def test_neighbor_queries_paper_and_mesh(self):
        """Challenge neighbor lookups: paper->mesh and mesh->paper."""
        # Known paper PMID 35100001 (Empagliflozin RCT)
        terms = self.retriever.get_mesh_terms_for_paper("35100001")
        assert len(terms) > 0, "No MeSH terms returned for paper 35100001"
        assert "Diabetes Mellitus, Type 2" in terms
        print(f"[Graph] MeSH terms for paper 35100001: {terms}")

        # Known MeSH term: Diabetes Mellitus, Type 2
        papers = self.retriever.get_papers_for_mesh("Diabetes Mellitus, Type 2")
        assert len(papers) > 0, "No papers found for 'Diabetes Mellitus, Type 2'"
        assert "35100001" in papers
        print(f"[Graph] Papers linked to 'Diabetes Mellitus, Type 2': {len(papers)} papers")

        # MeSH co-occurrence queries
        cooccur = self.retriever.get_cooccurring_mesh_terms("Diabetes Mellitus, Type 2", top_k=5)
        assert len(cooccur) > 0
        for name, weight in cooccur:
            assert weight >= 1.0
        print(f"[Graph] Top co-occurring MeSH for 'Diabetes Mellitus, Type 2': {cooccur}")

    def test_jaccard_similarity_calculation_mathematics(self):
        """Directly verify mathematical correctness of Jaccard similarity across MeSH sets."""
        pmid_a = "35100001"
        terms_a = set(self.retriever.get_mesh_terms_for_paper(pmid_a))
        assert len(terms_a) > 0

        related = self.retriever.get_related_papers_by_mesh(pmid_a, top_k=10)
        assert len(related) > 0, f"No related papers found for {pmid_a}"

        for pmid_b, score in related:
            terms_b = set(self.retriever.get_mesh_terms_for_paper(pmid_b))
            intersection = len(terms_a & terms_b)
            union = len(terms_a | terms_b)
            expected_jaccard = intersection / union if union > 0 else 0.0

            assert 0.0 <= score <= 1.0, f"Jaccard score out of bounds [0, 1]: {score}"
            assert abs(score - expected_jaccard) < 1e-6, (
                f"Jaccard mismatch between paper {pmid_a} and {pmid_b}: computed={score}, expected={expected_jaccard}"
            )
        print(f"[Graph] Verified mathematical exactness of Jaccard similarity for all top-{len(related)} related papers.")

    def test_graph_adversarial_queries(self):
        """Challenge graph with non-existent PMIDs, non-existent MeSH terms, and empty sets."""
        # Non-existent paper
        assert self.retriever.get_mesh_terms_for_paper("99999999") == []
        assert self.retriever.get_related_papers_by_mesh("99999999") == []

        # Non-existent MeSH
        assert self.retriever.get_papers_for_mesh("NonExistentDescriptor_XYZ") == []
        assert self.retriever.get_cooccurring_mesh_terms("NonExistentDescriptor_XYZ") == []

        # Subgraph extraction for non-existent paper
        sub = self.retriever.extract_subgraph_for_papers(["99999999"])
        assert sub["nodes"] == []
        print("[Graph] Non-existent entities and boundary conditions handled safely.")


# ============================================================================
# Standalone Execution Runner
# ============================================================================

def run_all_empirical_challenges():
    print("=" * 80)
    print("STARTING EMPIRICAL CHALLENGE SUITE: M1 STORAGE & RETRIEVAL SUBSYSTEMS")
    print("=" * 80)

    # 1. Qdrant
    q = TestEmpiricalQdrantStorage()
    q.setup_class()
    q.test_direct_qdrant_client_connection_and_stats()
    q.test_qdrant_vector_dimensions_and_norm_invariants()
    q.test_qdrant_cosine_similarity_range_and_identity_match()
    q.test_qdrant_payload_filters_year_and_study_type()

    # 2. BM25
    b = TestEmpiricalBM25Index()
    b.setup_class()
    b.test_direct_bm25_unpickling_and_attributes()
    b.test_exact_drug_keyword_matching_semaglutide()
    b.test_exact_drug_keyword_matching_sotorasib()
    b.test_exact_drug_keyword_matching_empagliflozin()
    b.test_bm25_adversarial_queries_and_tokenization()

    # 3. NetworkX Graph
    g = TestEmpiricalNetworkXGraph()
    g.setup_class()
    g.test_direct_graph_loading_and_isomorphism()
    g.test_neighbor_queries_paper_and_mesh()
    g.test_jaccard_similarity_calculation_mathematics()
    g.test_graph_adversarial_queries()

    print("\n" + "=" * 80)
    print("ALL EMPIRICAL CHALLENGES COMPLETED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    run_all_empirical_challenges()
