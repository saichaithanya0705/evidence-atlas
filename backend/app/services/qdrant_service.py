"""
backend/app/services/qdrant_service.py
Singleton service managing embedded Qdrant access, dense search,
payload filtering (year ranges, study_type, MeSH terms), and point retrieval by PMID.
Implements FEAT-R2-07.
"""

from typing import List, Dict, Any, Optional
import logging
from pathlib import Path
import numpy as np
from qdrant_client import QdrantClient, models
from backend.app.retrieval.bm25 import build_qdrant_sparse_vector

logger = logging.getLogger(__name__)

COLLECTION_NAME = "medical_abstracts"
DEFAULT_STORAGE_PATH = "./data/qdrant_storage"


class QdrantService:
    """
    Thread-safe interface for querying embedded Qdrant local disk store.
    """

    def __init__(self, storage_path: str = DEFAULT_STORAGE_PATH, collection_name: str = COLLECTION_NAME):
        self.storage_path = Path(storage_path).resolve()
        self.collection_name = collection_name
        logger.info("Initializing QdrantService at %s", self.storage_path)
        self.client = QdrantClient(path=str(self.storage_path))

    def close(self):
        """Releases the embedded storage file lock."""
        if self.client:
            self.client.close()
            logger.info("QdrantService closed.")

    @staticmethod
    def _build_filter(
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        study_types: Optional[List[str]] = None,
        mesh_terms: Optional[List[str]] = None,
    ) -> Optional[models.Filter]:
        """Build one reusable metadata-filter contract for all retrieval modes."""
        conditions = []
        if year_min is not None or year_max is not None:
            range_kwargs = {}
            if year_min is not None:
                range_kwargs["gte"] = year_min
            if year_max is not None:
                range_kwargs["lte"] = year_max
            conditions.append(models.FieldCondition(key="year", range=models.Range(**range_kwargs)))
        if study_types:
            conditions.append(
                models.FieldCondition(key="study_type", match=models.MatchAny(any=study_types))
            )
        if mesh_terms:
            conditions.extend(
                models.FieldCondition(key="mesh_terms", match=models.MatchValue(value=term))
                for term in mesh_terms
            )
        return models.Filter(must=conditions) if conditions else None

    def search_dense(
        self,
        query_vector: np.ndarray,
        limit: int = 50,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        study_types: Optional[List[str]] = None,
        mesh_terms: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Executes dense vector search against collection with optional metadata filters.
        Returns list of ranked dicts with 'pmid', 'score', and full 'payload'.
        """
        query_filter = self._build_filter(year_min, year_max, study_types, mesh_terms)
        vec = query_vector.tolist() if isinstance(query_vector, np.ndarray) else query_vector

        if hasattr(self.client, "query_points"):
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=vec,
                using="dense",
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            search_results = response.points
        else:
            search_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=vec,
                query_filter=query_filter,
                limit=limit,
                with_payload=True,
            )

        results = []
        for pt in search_results:
            results.append({
                "pmid": pt.id,
                "score": float(pt.score),
                "payload": pt.payload,
            })
        return results

    def search_sparse(
        self,
        query: str,
        limit: int = 50,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        study_types: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search the Qdrant-resident BM25-style sparse vector representation."""
        indices, values = build_qdrant_sparse_vector(query)
        if not indices:
            return []
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=models.SparseVector(indices=indices, values=values),
            using="bm25",
            query_filter=self._build_filter(year_min, year_max, study_types),
            limit=limit,
            with_payload=True,
        )
        return [
            {"pmid": point.id, "score": float(point.score), "payload": point.payload}
            for point in response.points
        ]

    def get_paper_by_pmid(self, pmid: int) -> Optional[Dict[str, Any]]:
        """Retrieves single paper metadata payload by PMID."""
        points = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[int(pmid)],
            with_payload=True,
        )
        if points:
            return points[0].payload
        return None

    def get_collection_stats(self) -> Dict[str, Any]:
        """Returns collection point count and status for health checks."""
        info = self.client.get_collection(self.collection_name)
        status_val = info.status.value if hasattr(info.status, "value") else str(info.status)
        indexed_vectors = getattr(info, "indexed_vectors_count", 0) or 0
        return {
            "collection_name": self.collection_name,
            "status": status_val,
            "points_count": info.points_count,
            # Every point in this collection carries one dense and one sparse
            # vector. Local Qdrant may report zero *indexed* vectors below its
            # HNSW threshold, which is not the same as vectors being absent.
            "vectors_count": info.points_count,
            "indexed_vectors_count": indexed_vectors,
        }
