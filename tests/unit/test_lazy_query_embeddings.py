"""Regression coverage for lightweight FastAPI/query-service startup."""

from backend.app.query.embeddings import DualQueryEmbeddingGenerator


def test_encoder_is_not_constructed_until_embeddings_are_requested(monkeypatch):
    constructed = []

    class FakeEncoder:
        def __init__(self):
            constructed.append(True)

    monkeypatch.setattr("backend.app.query.embeddings.MedCPTQueryEncoder", FakeEncoder)

    generator = DualQueryEmbeddingGenerator()

    assert generator.encoder is None
    assert constructed == []

    assert generator._get_encoder() is generator._get_encoder()
    assert constructed == [True]
