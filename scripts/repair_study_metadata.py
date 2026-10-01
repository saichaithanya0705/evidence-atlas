"""Repair study labels without changing retrieval text or recomputing vectors.

Dry-run by default. Stop the API before --apply so embedded Qdrant is exclusive.
Backups allow rebuilding/restoring derived artifacts if a write is interrupted.
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from qdrant_client import QdrantClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipelines.preprocess import infer_study_type


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = Path("data/processed/cleaned_pubmed.parquet")
    frame = pd.read_parquet(source)
    old_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    labels = frame.apply(lambda row: infer_study_type(list(row.publication_types), row.title, row.abstract), axis=1)
    changed = frame.study_type != labels
    print(f"Study labels to repair: {int(changed.sum())} / {len(frame)}", flush=True)
    if not args.apply or not changed.any():
        return
    pmids = np.load("data/processed/article_pmids.npy")
    assert list(map(int, pmids)) == list(map(int, frame.pmid))
    meta_path = Path("data/processed/embeddings_meta.json")
    metadata = json.loads(meta_path.read_text())
    assert metadata["corpus_hash"] == old_hash
    before_text = frame[["pmid", "title", "abstract", "embedding_text"]].copy()
    frame["study_type"] = labels
    assert before_text.equals(frame[["pmid", "title", "abstract", "embedding_text"]])
    client = QdrantClient(path="data/qdrant_storage")
    try:
        backup = Path("data/index_backups") / datetime.now(timezone.utc).strftime("study-labels-%Y%m%dT%H%M%S%f")
        backup.mkdir(parents=True, exist_ok=False)
        files = [source, meta_path, Path("data/processed/cleaned_pubmed.jsonl"),
                 Path("data/manifests/index_manifest.json"), Path("data/manifests/preprocessing_manifest.json")]
        for path in files:
            shutil.copy2(path, backup / path.name)
        for label in labels[changed].unique():
            ids = frame.loc[changed & (labels == label), "pmid"].astype(int).tolist()
            for offset in range(0, len(ids), 256):
                client.set_payload("medical_abstracts", payload={"study_type": label}, points=ids[offset:offset + 256], wait=True)
        frame.to_parquet(source, index=False)
        with Path("data/processed/cleaned_pubmed.jsonl").open("w", encoding="utf-8") as handle:
            for row in frame.to_dict("records"):
                handle.write(json.dumps(row, ensure_ascii=False, default=lambda value: value.tolist()) + "\n")
        new_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        repair = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                  "changed_records": int(changed.sum()), "previous_corpus_sha256": old_hash,
                  "retrieval_text_unchanged": True, "backup_path": str(backup)}
        metadata["corpus_hash"] = new_hash
        metadata["metadata_repair"] = repair
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        for path in files[-2:]:
            manifest = json.loads(path.read_text())
            manifest["metadata_repair"] = repair
            if "corpus" in manifest:
                manifest["corpus"]["sha256"] = new_hash
                manifest["corpus"]["study_type_breakdown"] = {str(k): int(v) for k, v in labels.value_counts().items()}
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(repair, indent=2), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
