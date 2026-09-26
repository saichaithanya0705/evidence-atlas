"""
pipelines/index_qdrant.py
Builds the complete Qdrant embedded hybrid knowledge base and index manifest:
1. Connects to embedded Qdrant local disk store at data/qdrant_storage
2. Creates collection 'medical_abstracts' (768-dim, Cosine distance)
3. Configures payload indexes for 'year', 'study_type', 'mesh_terms'
4. Batch-inserts points with dense vectors and complete metadata payloads
5. Generates index manifest at data/manifests/index_manifest.json
Implements FEAT-R2-07, FEAT-R2-09.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from typing import Optional
import numpy as np
import pandas as pd
from qdrant_client import QdrantClient, models
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.retrieval.bm25 import BM25Index, build_qdrant_sparse_vector
from backend.app.retrieval.medcpt import EMBEDDING_DIM

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("index_qdrant")

COLLECTION_NAME = "medical_abstracts"
ARTICLE_ENCODER_MODEL = "ncbi/MedCPT-Article-Encoder"


def get_dir_size(path: Path) -> int:
    """Calculates recursive directory size in bytes."""
    total = 0
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def load_corpus(input_file: Path) -> pd.DataFrame:
    """Loads corpus from parquet or jsonl fallback."""
    if input_file.exists():
        if input_file.suffix == ".parquet":
            return pd.read_parquet(input_file)
        elif input_file.suffix == ".jsonl":
            return pd.read_json(input_file, lines=True)
        else:
            return pd.read_csv(input_file)

    jsonl_fallback = input_file.with_suffix(".jsonl")
    if jsonl_fallback.exists():
        logger.info("Parquet not found, using JSONL fallback: %s", jsonl_fallback)
        return pd.read_json(jsonl_fallback, lines=True)

    raise FileNotFoundError(f"Corpus file not found: {input_file} or {jsonl_fallback}")


def resolve_corpus_path(input_file: Path) -> Path:
    """Return the file load_corpus will read, including its JSONL fallback."""
    if input_file.exists():
        return input_file
    jsonl_fallback = input_file.with_suffix(".jsonl")
    if jsonl_fallback.exists():
        return jsonl_fallback
    raise FileNotFoundError(f"Corpus file not found: {input_file} or {jsonl_fallback}")


def compute_file_sha256(filepath: Path) -> str:
    """Hash file bytes so the manifest identifies the exact indexed corpus artifact."""
    digest = hashlib.sha256()
    with filepath.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_model_revision(model_name: str, cache_dir: Optional[Path] = None) -> Optional[str]:
    """Read a pinned revision from local Hugging Face cache metadata, if present."""
    if cache_dir is None:
        cache_dir = Path(os.getenv("MODELS_CACHE_DIR", "data/models_cache"))
    if not cache_dir.is_absolute():
        cache_dir = Path.cwd() / cache_dir
    model_cache = cache_dir / ("models--" + model_name.replace("/", "--"))
    refs_main = model_cache / "refs" / "main"
    if refs_main.is_file():
        revision = refs_main.read_text(encoding="utf-8").strip()
        if revision:
            return revision
    snapshots = model_cache / "snapshots"
    if snapshots.is_dir():
        revisions = sorted(path.name for path in snapshots.iterdir() if path.is_dir())
        if len(revisions) == 1:
            return revisions[0]
    return None


def resolve_encoder_revision(embeddings_file: Path, model_name: str) -> tuple[Optional[str], Optional[str]]:
    """Prefer revision recorded alongside embeddings, then use local model cache."""
    metadata_file = embeddings_file.parent / "embeddings_meta.json"
    if metadata_file.is_file():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            if metadata.get("model_name") in (None, model_name):
                revision = metadata.get("model_revision") or metadata.get("revision")
                if revision:
                    return str(revision), "embeddings_metadata"
        except (OSError, json.JSONDecodeError):
            logger.warning("Could not read embeddings metadata at %s", metadata_file)
    revision = discover_model_revision(model_name)
    return revision, "huggingface_cache" if revision else None


def index_qdrant_collection(
    corpus_file: Path,
    embeddings_file: Path,
    qdrant_path: Path,
    bm25_file: Path,
    manifest_output_file: Path,
    batch_size: int = 256,
):
    start_time = datetime.now(timezone.utc)

    # 1. Load Cleaned Corpus & Embeddings
    logger.info("Loading cleaned corpus: %s", corpus_file)
    actual_corpus_file = resolve_corpus_path(corpus_file)
    df = load_corpus(corpus_file)
    total_records = len(df)
    if total_records == 0:
        raise ValueError("Corpus is empty. Cannot index empty dataset.")

    logger.info("Loading dense embeddings: %s", embeddings_file)
    if not embeddings_file.exists():
        raise FileNotFoundError(f"Dense embeddings file not found: {embeddings_file}")
    embeddings = np.load(embeddings_file)
    if len(embeddings) != total_records:
        raise ValueError(
            f"Row count mismatch: df has {total_records} rows, embeddings has {len(embeddings)}"
        )

    # 2. Check / Build BM25 Index
    if not bm25_file.exists():
        logger.info("BM25 index not found at %s. Building now...", bm25_file)
        records = df.to_dict(orient="records")
        bm25_index = BM25Index.build_from_records(records)
        bm25_file.parent.mkdir(parents=True, exist_ok=True)
        bm25_index.save(bm25_file)
    else:
        logger.info("Loading existing BM25 index from %s", bm25_file)
        bm25_index = BM25Index.load(bm25_file)

    # 3. Setup Qdrant Embedded Collection
    logger.info("Connecting to embedded Qdrant at %s", qdrant_path)
    qdrant_path.mkdir(parents=True, exist_ok=True)
    client = QdrantClient(path=str(qdrant_path))

    try:
        existing_collections = [c.name for c in client.get_collections().collections]
        if COLLECTION_NAME in existing_collections:
            logger.info("Recreating existing collection '%s'", COLLECTION_NAME)
            client.delete_collection(COLLECTION_NAME)

        logger.info("Creating Qdrant collection '%s' with dense and BM25 sparse vectors", COLLECTION_NAME)
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(size=EMBEDDING_DIM, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "bm25": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False),
                    modifier=models.Modifier.IDF,
                ),
            },
        )

        # 4. Create Payload Indexes for High-Performance Filtering
        logger.info("Creating payload indexes: year (INTEGER), study_type (KEYWORD), mesh_terms (KEYWORD)")
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="year",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="study_type",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="mesh_terms",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

        # 5. Insert Points with Complete Payloads in Batches
        logger.info("Upserting %d points in batches of %d...", total_records, batch_size)
        for i in range(0, total_records, batch_size):
            batch_df = df.iloc[i : i + batch_size]
            batch_vectors = embeddings[i : i + batch_size]

            points = []
            for (_, row), vec in zip(batch_df.iterrows(), batch_vectors):
                pmid = int(row["pmid"])

                mesh_terms = row.get("mesh_terms", [])
                if isinstance(mesh_terms, np.ndarray):
                    mesh_terms = mesh_terms.tolist()
                elif not isinstance(mesh_terms, list):
                    mesh_terms = [str(mesh_terms)] if pd.notna(mesh_terms) and str(mesh_terms).strip() else []

                keywords = row.get("keywords", [])
                if isinstance(keywords, np.ndarray):
                    keywords = keywords.tolist()
                elif not isinstance(keywords, list):
                    keywords = [str(keywords)] if pd.notna(keywords) and str(keywords).strip() else []

                authors = row.get("authors", [])
                if isinstance(authors, np.ndarray):
                    authors = authors.tolist()
                elif not isinstance(authors, list):
                    authors = [str(authors)] if pd.notna(authors) and str(authors).strip() else []

                year_val = None
                if pd.notna(row.get("year")):
                    try:
                        year_val = int(row["year"])
                    except (ValueError, TypeError):
                        year_val = None

                payload = {
                    "pmid": pmid,
                    "title": str(row.get("title", "")),
                    "abstract": str(row.get("abstract", "") or ""),
                    "authors": authors,
                    "year": year_val,
                    "publication_date": str(row.get("publication_date", "") or ""),
                    "study_type": str(row.get("study_type", "Other") or "Other"),
                    "mesh_terms": mesh_terms,
                    "keywords": keywords,
                    "journal": str(row.get("journal", "") or ""),
                    "doi": str(row.get("doi", "") or ""),
                }

                sparse_text = " ".join(
                    [payload["title"], payload["title"], payload["abstract"], *mesh_terms, *keywords]
                )
                sparse_indices, sparse_values = build_qdrant_sparse_vector(sparse_text)

                points.append(
                    models.PointStruct(
                        id=pmid,
                        vector={
                            "dense": vec.tolist(),
                            "bm25": models.SparseVector(indices=sparse_indices, values=sparse_values),
                        },
                        payload=payload,
                    )
                )

            client.upsert(collection_name=COLLECTION_NAME, points=points)

        col_info = client.get_collection(COLLECTION_NAME)
        points_count = col_info.points_count
        logger.info("Qdrant collection populated successfully. Total points: %d", points_count)

    finally:
        client.close()
        logger.info("Qdrant client cleanly closed and unlocked.")

    # 6. Generate Index Manifest
    logger.info("Generating index manifest...")
    end_time = datetime.now(timezone.utc)
    corpus_sha256 = compute_file_sha256(actual_corpus_file)
    model_revision, model_revision_source = resolve_encoder_revision(
        embeddings_file, ARTICLE_ENCODER_MODEL
    )

    qdrant_size_bytes = get_dir_size(qdrant_path)
    bm25_size_bytes = bm25_file.stat().st_size if bm25_file.exists() else 0
    embs_size_bytes = embeddings_file.stat().st_size if embeddings_file.exists() else 0

    study_type_counts = df["study_type"].value_counts().to_dict() if "study_type" in df else {}
    valid_years = df["year"].dropna()
    min_year = int(valid_years.min()) if not valid_years.empty else None
    max_year = int(valid_years.max()) if not valid_years.empty else None
    min_pmid = int(df["pmid"].astype(int).min()) if "pmid" in df else None
    max_pmid = int(df["pmid"].astype(int).max()) if "pmid" in df else None

    manifest = {
        "manifest_version": "1.0.0",
        "build_timestamp_utc": end_time.isoformat(),
        "build_duration_seconds": round((end_time - start_time).total_seconds(), 2),
        "corpus": {
            "source_file": str(actual_corpus_file),
            "sha256": corpus_sha256,
            "total_records": total_records,
            "pmid_range": {"min": min_pmid, "max": max_pmid},
            "year_range": {"min": min_year, "max": max_year},
            "study_type_breakdown": {str(k): int(v) for k, v in study_type_counts.items()},
        },
        "dense_index": {
            "model_name": ARTICLE_ENCODER_MODEL,
            "model_revision": model_revision,
            "model_revision_source": model_revision_source,
            "dimension": EMBEDDING_DIM,
            "pooling": "cls",
            "normalized": True,
            "metric": "cosine",
            "embeddings_file": str(embeddings_file),
            "storage_size_bytes": embs_size_bytes,
            "storage_size_mb": round(embs_size_bytes / (1024 * 1024), 2),
        },
        "sparse_index": {
            "algorithm": "BM25Okapi",
            "index_file": str(bm25_file),
            "parameters": {"k1": 1.5, "b": 0.75},
            "vocabulary_size": bm25_index.vocab_size,
            "avg_document_length_tokens": round(bm25_index.avgdl, 2),
            "indexed_fields": ["title", "abstract", "mesh_terms", "keywords"],
            "qdrant_vector_name": "bm25",
            "qdrant_modifier": "idf",
            "storage_size_bytes": bm25_size_bytes,
            "storage_size_mb": round(bm25_size_bytes / (1024 * 1024), 2),
        },
        "vector_store": {
            "engine": "qdrant-client-embedded",
            "storage_path": str(qdrant_path),
            "collection_name": COLLECTION_NAME,
            "points_count": total_records,
            "vector_names": ["dense", "bm25"],
            "indexed_payload_fields": [
                {"field_name": "year", "schema_type": "integer"},
                {"field_name": "study_type", "schema_type": "keyword"},
                {"field_name": "mesh_terms", "schema_type": "keyword"},
            ],
            "storage_size_bytes": qdrant_size_bytes,
            "storage_size_mb": round(qdrant_size_bytes / (1024 * 1024), 2),
        },
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        },
    }

    manifest_output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_output_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Index manifest written to %s", manifest_output_file)
    logger.info("Hybrid knowledge base build completed successfully.")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Qdrant Knowledge Base & Manifest")
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/cleaned_pubmed.parquet"))
    parser.add_argument("--embeddings", type=Path, default=Path("data/processed/article_embeddings.npy"))
    parser.add_argument("--qdrant-path", type=Path, default=Path("data/qdrant_storage"))
    parser.add_argument("--bm25-file", type=Path, default=Path("data/processed/bm25_index.pkl"))
    parser.add_argument("--manifest-output", type=Path, default=Path("data/manifests/index_manifest.json"))
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args()

    index_qdrant_collection(
        corpus_file=args.corpus,
        embeddings_file=args.embeddings,
        qdrant_path=args.qdrant_path,
        bm25_file=args.bm25_file,
        manifest_output_file=args.manifest_output,
        batch_size=args.batch_size,
    )
