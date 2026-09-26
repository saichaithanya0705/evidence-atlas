"""Low-memory lifecycle regression tests for MedCPT retrieval stages."""

from types import SimpleNamespace

from backend.app.retrieval.hybrid import HybridRetriever
from backend.app.retrieval.reranker import MedCPTReranker


def test_hybrid_retriever_releases_only_owned_query_encoder():
    owned = SimpleNamespace(model=object(), tokenizer=object())
    retriever = HybridRetriever()
    retriever._query_encoder = owned

    retriever.release_query_encoder()

    assert retriever._query_encoder is None
    assert owned.model is None
    assert owned.tokenizer is None

    injected = object()
    retriever = HybridRetriever(query_encoder=injected)
    retriever.release_query_encoder()
    assert retriever._query_encoder is injected


def test_reranker_release_resets_lazy_loader_state():
    reranker = MedCPTReranker(model=object(), tokenizer=object())

    reranker.release()

    assert reranker._model is None
    assert reranker._tokenizer is None
    assert reranker._load_attempted is False
