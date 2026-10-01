"""Read-only full alignment audit; run while the API releases embedded Qdrant."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.retrieval.bm25 import BM25Index


def main():
    source = Path("data/processed/cleaned_pubmed.parquet")
    corpus = pd.read_parquet(source)
    embeddings = np.load("data/processed/article_embeddings.npy", mmap_mode="r")
    pmids = np.load("data/processed/article_pmids.npy")
    bm25 = BM25Index.load("data/processed/bm25_index.pkl")
    expected = [int(value) for value in corpus.pmid]
    assert len(expected) == len(set(expected))
    assert embeddings.shape == (len(expected), 768)
    assert np.isfinite(embeddings).all()
    assert list(map(int, pmids)) == expected
    assert list(map(int, bm25.pmids)) == expected
    manifest = json.loads(Path("data/manifests/index_manifest.json").read_text())
    corpus_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["corpus"]["sha256"] == corpus_hash
    assert manifest["vector_store"]["points_count"] == len(expected)
    index_by_pmid = {pmid: index for index, pmid in enumerate(expected)}
    seen = set()
    client = QdrantClient(path="data/qdrant_storage")
    try:
        offset = None
        while True:
            points, offset = client.scroll(
                "medical_abstracts", limit=256, offset=offset,
                with_payload=True, with_vectors=True,
            )
            for point in points:
                pmid = int(point.id)
                assert pmid not in seen and pmid in index_by_pmid
                index = index_by_pmid[pmid]
                row = corpus.iloc[index]
                assert int(point.payload["pmid"]) == pmid
                assert point.payload["title"] == row.title
                assert point.payload["abstract"] == row.abstract
                assert int(point.payload["year"]) == int(row.year)
                assert point.payload["study_type"] == row.study_type
                assert np.allclose(point.vector["dense"], embeddings[index], atol=1e-6)
                assert "bm25" in point.vector
                seen.add(pmid)
            if offset is None:
                break
        assert seen == set(expected)
    finally:
        client.close()
    report = {
        "corpus_sha256": corpus_hash, "clean_records": len(expected),
        "embedding_shape": list(embeddings.shape), "bm25_records": len(bm25.pmids),
        "qdrant_records": len(seen), "all_ids_payloads_dense_vectors_match": True,
    }
    output = Path("data/manifests/corpus_alignment_report.json")
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
