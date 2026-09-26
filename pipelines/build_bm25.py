"""
pipelines/build_bm25.py
Builds and serializes the BM25 sparse index from cleaned PubMed records.
Outputs: data/processed/bm25_index.pkl
Implements FEAT-R2-06.
"""

import argparse
import logging
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.retrieval.bm25 import BM25Index

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_bm25")


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


def build_bm25_from_corpus(corpus_path: Path, output_path: Path) -> BM25Index:
    """Builds and serializes BM25 sparse index."""
    logger.info("Loading corpus from %s for BM25 indexing...", corpus_path)
    df = load_corpus(corpus_path)
    records = df.to_dict(orient="records")
    logger.info("Building BM25Index from %d records...", len(records))

    bm25_index = BM25Index.build_from_records(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bm25_index.save(output_path)
    logger.info("Successfully built and saved BM25 index to %s (vocab: %d, avgdl: %.2f)",
                output_path, bm25_index.vocab_size, bm25_index.avgdl)
    return bm25_index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build BM25 sparse index.")
    parser.add_argument("--corpus", type=Path, default=Path("data/processed/cleaned_pubmed.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/bm25_index.pkl"))
    args = parser.parse_args()

    build_bm25_from_corpus(args.corpus, args.output)
