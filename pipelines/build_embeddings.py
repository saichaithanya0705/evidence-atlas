"""
pipelines/build_embeddings.py
Offline batch generator for MedCPT article dense embeddings with disk caching.
Input: data/processed/cleaned_pubmed.parquet (or .jsonl)
Outputs:
  - data/processed/article_embeddings.npy (shape: (N, 768), float32)
  - data/processed/article_pmids.npy (shape: (N,), int64)
  - data/processed/embeddings_meta.json (build metadata & hash validation)
Implements FEAT-R2-05.
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.retrieval.medcpt import MedCPTArticleEncoder, EMBEDDING_DIM

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_embeddings")


def compute_file_hash(filepath: Path) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_corpus(input_file: Path) -> pd.DataFrame:
    """Loads corpus from parquet or jsonl/csv."""
    if input_file.exists():
        if input_file.suffix == ".parquet":
            return pd.read_parquet(input_file)
        elif input_file.suffix == ".jsonl":
            return pd.read_json(input_file, lines=True)
        else:
            return pd.read_csv(input_file)

    # If parquet doesn't exist, try jsonl fallback in same dir
    jsonl_fallback = input_file.with_suffix(".jsonl")
    if jsonl_fallback.exists():
        logger.info("Parquet not found, using JSONL fallback: %s", jsonl_fallback)
        return pd.read_json(jsonl_fallback, lines=True)

    raise FileNotFoundError(f"Corpus file not found: {input_file} or {jsonl_fallback}")


def atomic_write_json(path: Path, payload: dict) -> None:
    """Persist checkpoint metadata without exposing a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(payload, temporary, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def resumable_encode(
    encoder: MedCPTArticleEncoder,
    titles: list[str],
    abstracts: list[str],
    output_path: Path,
    checkpoint_path: Path,
    corpus_hash: str,
    batch_size: int,
    checkpoint_every: int,
) -> np.ndarray:
    """Encode into a durable NumPy memmap and resume matching checkpoints."""
    from tqdm import tqdm

    total_records = len(titles)
    in_progress_path = output_path.with_name(f"{output_path.stem}.inprogress.npy")
    completed_records = 0
    embeddings = None

    if in_progress_path.is_file() and checkpoint_path.is_file():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            embeddings = np.load(in_progress_path, mmap_mode="r+")
            valid_checkpoint = (
                checkpoint.get("corpus_hash") == corpus_hash
                and checkpoint.get("model_name") == "ncbi/MedCPT-Article-Encoder"
                and int(checkpoint.get("total_records", -1)) == total_records
                and tuple(embeddings.shape) == (total_records, EMBEDDING_DIM)
            )
            if valid_checkpoint:
                completed_records = min(int(checkpoint.get("completed_records", 0)), total_records)
                logger.info("Resuming durable embedding checkpoint at record %d/%d", completed_records, total_records)
            else:
                logger.warning("Embedding checkpoint does not match this corpus; starting a clean resumable build")
                memory_map = getattr(embeddings, "_mmap", None)
                if memory_map is not None:
                    memory_map.close()
                embeddings = None
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Could not load embedding checkpoint (%s); starting a clean resumable build", exc)
            memory_map = getattr(embeddings, "_mmap", None)
            if memory_map is not None:
                memory_map.close()
            embeddings = None

    if embeddings is None:
        in_progress_path.unlink(missing_ok=True)
        checkpoint_path.unlink(missing_ok=True)
        embeddings = np.lib.format.open_memmap(
            in_progress_path,
            mode="w+",
            dtype=np.float32,
            shape=(total_records, EMBEDDING_DIM),
        )
        atomic_write_json(
            checkpoint_path,
            {
                "corpus_hash": corpus_hash,
                "model_name": "ncbi/MedCPT-Article-Encoder",
                "total_records": total_records,
                "completed_records": 0,
                "embedding_dimension": EMBEDDING_DIM,
            },
        )

    checkpoint_every = max(1, checkpoint_every)
    progress = tqdm(total=total_records, initial=completed_records, desc="Encoding MedCPT Articles", unit="records")
    try:
        batch_number = completed_records // batch_size
        for start in range(completed_records, total_records, batch_size):
            end = min(start + batch_size, total_records)
            batch_embeddings = encoder.encode_articles(
                titles=titles[start:end],
                abstracts=abstracts[start:end],
                show_progress=False,
            )
            embeddings[start:end] = batch_embeddings
            progress.update(end - start)
            batch_number += 1
            if batch_number % checkpoint_every == 0 or end == total_records:
                embeddings.flush()
                atomic_write_json(
                    checkpoint_path,
                    {
                        "corpus_hash": corpus_hash,
                        "model_name": "ncbi/MedCPT-Article-Encoder",
                        "total_records": total_records,
                        "completed_records": end,
                        "embedding_dimension": EMBEDDING_DIM,
                    },
                )
    except BaseException:
        embeddings.flush()
        memory_map = getattr(embeddings, "_mmap", None)
        if memory_map is not None:
            memory_map.close()
        raise
    finally:
        progress.close()

    embeddings.flush()
    memory_map = getattr(embeddings, "_mmap", None)
    if memory_map is not None:
        memory_map.close()
    del embeddings
    os.replace(in_progress_path, output_path)
    checkpoint_path.unlink(missing_ok=True)
    return np.load(output_path)


def build_embeddings(
    input_file: Path,
    output_dir: Path,
    batch_size: int = 32,
    force_rebuild: bool = False,
    limit: Optional[int] = None,
    resume: bool = False,
    checkpoint_every: int = 10,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    embeddings_path = output_dir / "article_embeddings.npy"
    pmids_path = output_dir / "article_pmids.npy"
    meta_path = output_dir / "embeddings_meta.json"
    checkpoint_path = output_dir / "embeddings_checkpoint.json"

    # Step 1: Ingest preprocessed corpus
    logger.info("Reading processed corpus from %s", input_file)
    df = load_corpus(input_file)

    if limit:
        logger.info("Limiting corpus to %d records for quick build", limit)
        df = df.head(limit)

    total_records = len(df)
    logger.info("Loaded %d clean records", total_records)
    current_hash = compute_file_hash(input_file) if input_file.exists() else "dynamic_hash"

    # Step 2: Validate existing cache
    if not force_rebuild and embeddings_path.exists() and pmids_path.exists() and meta_path.exists():
        cached_embs = None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            cached_pmids = np.load(pmids_path)
            cached_embs = np.load(embeddings_path, mmap_mode="r")

            if (
                meta.get("corpus_hash") == current_hash
                and len(cached_pmids) == total_records
                and cached_embs.shape == (total_records, EMBEDDING_DIM)
            ):
                logger.info("Cache is valid and matches corpus hash. Skipping embedding computation.")
                return
            else:
                logger.warning("Cache is stale or dimension mismatch. Rebuilding...")
        except Exception as e:
            logger.warning("Error inspecting cache (%s). Rebuilding...", e)
        finally:
            # A NumPy memmap keeps the file handle open.  Windows will reject
            # the subsequent np.save overwrite unless the mapping is closed.
            memory_map = getattr(cached_embs, "_mmap", None)
            if memory_map is not None:
                memory_map.close()

    # Step 3: Run MedCPT encoder
    titles = df["title"].fillna("").astype(str).tolist()
    abstracts = df["abstract"].fillna("").astype(str).tolist()
    pmids = df["pmid"].astype(np.int64).to_numpy()

    encoder = MedCPTArticleEncoder(batch_size=batch_size)
    if resume:
        embeddings = resumable_encode(
            encoder=encoder,
            titles=titles,
            abstracts=abstracts,
            output_path=embeddings_path,
            checkpoint_path=checkpoint_path,
            corpus_hash=current_hash,
            batch_size=batch_size,
            checkpoint_every=checkpoint_every,
        )
    else:
        embeddings = encoder.encode_articles(titles=titles, abstracts=abstracts, show_progress=True)

    # Step 4: Persist embeddings and metadata
    logger.info("Saving embeddings array (shape: %s) to %s", embeddings.shape, embeddings_path)
    np.save(embeddings_path, embeddings)
    np.save(pmids_path, pmids)

    meta_info = {
        "corpus_file": str(input_file),
        "corpus_hash": current_hash,
        "total_records": total_records,
        "embedding_dimension": EMBEDDING_DIM,
        "model_name": "ncbi/MedCPT-Article-Encoder",
        "pooling": "cls",
        "normalized": True,
        "batch_size": batch_size,
        "device": str(getattr(encoder, "device", "unknown")),
        "is_mock": bool(getattr(encoder, "is_mock", False)),
        "torch_version": str(__import__("torch").__version__),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_info, f, indent=2)

    logger.info("Embeddings build complete. Cached to disk.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate MedCPT Article Embeddings")
    parser.add_argument("--input", type=Path, default=Path("data/processed/cleaned_pubmed.parquet"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--force", action="store_true", help="Force rebuild cache")
    parser.add_argument("--limit", type=int, default=None, help="Process first N records")
    parser.add_argument("--resume", action="store_true", help="Checkpoint batches and resume a matching interrupted build")
    parser.add_argument("--checkpoint-every", type=int, default=10, help="Flush resumable progress every N batches")
    args = parser.parse_args()

    build_embeddings(
        input_file=args.input,
        output_dir=args.output_dir,
        batch_size=args.batch_size,
        force_rebuild=args.force,
        limit=args.limit,
        resume=args.resume,
        checkpoint_every=args.checkpoint_every,
    )
