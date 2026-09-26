"""Regression test for stale embedding cache rebuilds on Windows."""

import json

import numpy as np
import pandas as pd

from pipelines import build_embeddings as module


def test_stale_memmapped_cache_is_closed_before_overwrite(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.csv"
    pd.DataFrame([{"pmid": 1, "title": "Title", "abstract": "Abstract"}]).to_csv(
        corpus, index=False
    )
    np.save(tmp_path / "article_embeddings.npy", np.zeros((1, module.EMBEDDING_DIM), dtype=np.float32))
    np.save(tmp_path / "article_pmids.npy", np.array([1], dtype=np.int64))
    (tmp_path / "embeddings_meta.json").write_text(
        json.dumps({"corpus_hash": "stale"}), encoding="utf-8"
    )

    class FakeEncoder:
        def __init__(self, batch_size):
            self.batch_size = batch_size

        def encode_articles(self, titles, abstracts, show_progress=False):
            return np.ones((1, module.EMBEDDING_DIM), dtype=np.float32)

    monkeypatch.setattr(module, "MedCPTArticleEncoder", FakeEncoder)

    module.build_embeddings(corpus, tmp_path)

    rebuilt = np.load(tmp_path / "article_embeddings.npy")
    assert rebuilt.shape == (1, module.EMBEDDING_DIM)
    assert float(rebuilt[0, 0]) == 1.0
