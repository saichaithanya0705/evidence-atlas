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


def test_resumable_build_continues_after_interrupted_batch(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.csv"
    pd.DataFrame(
        [
            {"pmid": index, "title": f"Title {index}", "abstract": f"Abstract {index}"}
            for index in range(1, 6)
        ]
    ).to_csv(corpus, index=False)

    calls = []
    should_interrupt = {"value": True}

    class FakeEncoder:
        def __init__(self, batch_size):
            self.batch_size = batch_size

        def encode_articles(self, titles, abstracts, show_progress=False):
            calls.append(list(titles))
            if should_interrupt["value"] and len(calls) == 2:
                raise KeyboardInterrupt
            rows = []
            for title in titles:
                value = float(title.rsplit(" ", 1)[-1])
                rows.append(np.full(module.EMBEDDING_DIM, value, dtype=np.float32))
            return np.vstack(rows)

    monkeypatch.setattr(module, "MedCPTArticleEncoder", FakeEncoder)

    try:
        module.build_embeddings(
            corpus,
            tmp_path,
            batch_size=2,
            resume=True,
            checkpoint_every=1,
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("The first resumable pass should have been interrupted")

    checkpoint = json.loads((tmp_path / "embeddings_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["completed_records"] == 2

    should_interrupt["value"] = False
    module.build_embeddings(
        corpus,
        tmp_path,
        batch_size=2,
        resume=True,
        checkpoint_every=1,
    )

    embeddings = np.load(tmp_path / "article_embeddings.npy")
    assert embeddings.shape == (5, module.EMBEDDING_DIM)
    assert embeddings[:, 0].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert calls[2][0] == "Title 3"
    assert not (tmp_path / "embeddings_checkpoint.json").exists()
    assert not (tmp_path / "article_embeddings.inprogress.npy").exists()


def test_resumable_build_buckets_by_text_length_and_restores_original_order(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.csv"
    pd.DataFrame(
        [
            {"pmid": 1, "title": "Title 1", "abstract": "x" * 100},
            {"pmid": 2, "title": "Title 2", "abstract": "x" * 10},
            {"pmid": 3, "title": "Title 3", "abstract": "x" * 50},
            {"pmid": 4, "title": "Title 4", "abstract": "x"},
        ]
    ).to_csv(corpus, index=False)
    calls = []

    class FakeEncoder:
        def __init__(self, batch_size):
            self.batch_size = batch_size

        def encode_articles(self, titles, abstracts, show_progress=False):
            calls.append(list(titles))
            return np.vstack([
                np.full(module.EMBEDDING_DIM, float(title.rsplit(" ", 1)[-1]), dtype=np.float32)
                for title in titles
            ])

    monkeypatch.setattr(module, "MedCPTArticleEncoder", FakeEncoder)

    module.build_embeddings(
        corpus,
        tmp_path,
        batch_size=2,
        resume=True,
        checkpoint_every=1,
    )

    embeddings = np.load(tmp_path / "article_embeddings.npy")
    assert calls == [["Title 4", "Title 2"], ["Title 3", "Title 1"]]
    assert embeddings[:, 0].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_checkpoint_write_retries_transient_windows_file_lock(tmp_path, monkeypatch):
    checkpoint = tmp_path / "embeddings_checkpoint.json"
    checkpoint.write_text("{}", encoding="utf-8")
    original_replace = module.os.replace
    attempts = {"count": 0}

    def occasionally_locked(source, destination):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError("transient checkpoint file lock")
        return original_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", occasionally_locked)
    module.atomic_write_json(checkpoint, {"completed_records": 2})

    assert attempts["count"] == 2
    assert json.loads(checkpoint.read_text(encoding="utf-8")) == {"completed_records": 2}
