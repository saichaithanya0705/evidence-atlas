"""
backend/app/query/embeddings.py
Dual Query Dense Embedding Generation Module (FEAT-R3-06).
Computes 768-dim float32 unit-normalized dense embeddings for both original user query
and canonical query formulation using ncbi/MedCPT-Query-Encoder.
"""
from typing import Optional, Tuple
import numpy as np

from backend.app.query.models import DualQueryEmbeddings
from backend.app.retrieval.medcpt import MedCPTQueryEncoder, EMBEDDING_DIM


class DualQueryEmbeddingGenerator:
    """
    Generates dual dense query vectors (original query and canonical query)
    using MedCPTQueryEncoder (FEAT-R3-06).
    """

    def __init__(self, encoder: Optional[MedCPTQueryEncoder] = None):
        # Loading MedCPT allocates hundreds of megabytes and may initialize a
        # native Torch runtime.  Query-plan construction normally runs with
        # ``generate_embeddings=False``, so doing that work in the constructor
        # made even ``GET /health`` load the model.  Keep injected encoders
        # unchanged for tests and initialize the production encoder on demand.
        self.encoder = encoder

    def _get_encoder(self) -> MedCPTQueryEncoder:
        if self.encoder is None:
            self.encoder = MedCPTQueryEncoder()
        return self.encoder

    def generate_embeddings(
        self, original_query: str, canonical_query: str
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Computes dual 768-dimensional L2-normalized float32 vectors.

        Args:
            original_query: Raw user query string.
            canonical_query: Standardized canonical query string.

        Returns:
            Tuple of:
            - original_vector: (768,) float32 unit-norm array.
            - canonical_vector: (768,) float32 unit-norm array.
        """
        matrix = self._get_encoder().encode_queries([original_query, canonical_query])
        orig_vec = matrix[0].astype(np.float32)
        canon_vec = matrix[1].astype(np.float32)

        # Enforce unit norm invariant
        orig_norm = np.linalg.norm(orig_vec)
        if orig_norm > 0:
            orig_vec = orig_vec / orig_norm

        canon_norm = np.linalg.norm(canon_vec)
        if canon_norm > 0:
            canon_vec = canon_vec / canon_norm

        return orig_vec, canon_vec

    def generate_dual_model(
        self, original_query: str, canonical_query: str
    ) -> DualQueryEmbeddings:
        """
        Returns embeddings wrapped in the Pydantic DualQueryEmbeddings model.
        """
        orig_vec, canon_vec = self.generate_embeddings(original_query, canonical_query)
        return DualQueryEmbeddings(
            original_query_embedding=orig_vec.tolist(),
            canonical_query_embedding=canon_vec.tolist(),
        )
