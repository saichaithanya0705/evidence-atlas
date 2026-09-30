"""Multi-channel biomedical retrieval with RRF and hard metadata filtering.

The retriever keeps expensive model and storage initialization out of module
imports. It accepts injected collaborators for tests and service composition,
and otherwise loads the project's local indexes on the first search.
"""

from __future__ import annotations

import json
import logging
import math
import re
import gc
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from backend.app.models.request_response import RetrievalCandidate
from backend.app.query.models import QueryPlan

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[str]], k: int = 60
) -> Dict[str, float]:
    """Return RRF scores, using one-based rank positions in each channel."""
    if k < 1:
        raise ValueError("RRF k must be a positive integer")
    scores: Dict[str, float] = {}
    for ranked_pmids in rankings.values():
        seen_in_channel = set()
        for rank, raw_pmid in enumerate(ranked_pmids, start=1):
            pmid = str(raw_pmid).strip()
            if not pmid or pmid in seen_in_channel:
                continue
            seen_in_channel.add(pmid)
            scores[pmid] = scores.get(pmid, 0.0) + 1.0 / (k + rank)
    return scores


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normal(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


class HybridRetriever:
    """Dense + BM25 + optional MeSH-graph retrieval with provenance.

    Parameters can be injected (``qdrant_service``, ``bm25_index``, ``records``,
    ``graph_retriever``, ``query_encoder``) so the same class is usable with
    lightweight tests and the local production assets.
    """

    def __init__(
        self,
        settings: Any = None,
        qdrant_service: Any = None,
        bm25_index: Any = None,
        records: Optional[Iterable[Mapping[str, Any]]] = None,
        graph_retriever: Any = None,
        query_encoder: Any = None,
    ) -> None:
        self._settings = settings
        self._qdrant = qdrant_service
        self._bm25 = bm25_index
        self._graph = graph_retriever
        self._query_encoder = query_encoder
        self._query_encoder_injected = query_encoder is not None
        self._records_by_pmid: Optional[Dict[str, Dict[str, Any]]] = None
        if records is not None:
            self._records_by_pmid = {
                str(record.get("pmid", "")).strip(): dict(record)
                for record in records
                if str(record.get("pmid", "")).strip()
            }
        self.last_trace: Dict[str, Any] = {}

    @property
    def settings(self) -> Any:
        if self._settings is None:
            from backend.app.core.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _get_qdrant(self) -> Any:
        if self._qdrant is None:
            from backend.app.services.qdrant_service import QdrantService

            self._qdrant = QdrantService(
                storage_path=self.settings.QDRANT_STORAGE_PATH,
                collection_name=self.settings.QDRANT_COLLECTION_NAME,
            )
        return self._qdrant

    def _get_bm25(self) -> Any:
        if self._bm25 is None:
            index_path = Path(self.settings.BM25_INDEX_PATH)
            if not index_path.exists():
                return None
            from backend.app.retrieval.bm25 import BM25Index

            self._bm25 = BM25Index.load(index_path)
        return self._bm25

    def _get_graph(self) -> Any:
        if self._graph is None:
            graph_path = Path(self.settings.MESH_GRAPH_PATH)
            if not graph_path.exists() and not graph_path.with_suffix(".json").exists():
                return None
            from backend.app.retrieval.graph_retrieval import ConceptGraphRetriever

            self._graph = ConceptGraphRetriever(
                pickle_path=str(graph_path), json_path=str(graph_path.with_suffix(".json"))
            )
        return self._graph

    def _get_query_encoder(self) -> Any:
        if self._query_encoder is None:
            from backend.app.retrieval.medcpt import MedCPTQueryEncoder

            self._query_encoder = MedCPTQueryEncoder(
                model_name_or_path=self.settings.MEDCPT_QUERY_ENCODER,
                device=self.settings.DEVICE,
                cache_dir=self.settings.MODELS_CACHE_DIR,
                allow_mock=bool(getattr(self.settings, "MEDCPT_ALLOW_MOCK", False)),
            )
        return self._query_encoder

    def release_query_encoder(self) -> None:
        """Release production MedCPT weights after dense retrieval.

        The query encoder and cross-encoder are each large BERT checkpoints.
        Keeping both resident can terminate memory-constrained Windows hosts.
        Injected collaborators are retained so tests and custom deployments keep
        their caller-owned lifecycle.
        """
        if self._query_encoder is None or self._query_encoder_injected:
            return
        encoder = self._query_encoder
        self._query_encoder = None
        for attribute in ("model", "tokenizer"):
            if hasattr(encoder, attribute):
                setattr(encoder, attribute, None)
        del encoder
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _load_records(self) -> Dict[str, Dict[str, Any]]:
        if self._records_by_pmid is not None:
            return self._records_by_pmid
        path = Path(self.settings.CLEANED_DATA_PATH)
        if not path.exists() and path.with_suffix(".jsonl").exists():
            path = path.with_suffix(".jsonl")
        records: Dict[str, Dict[str, Any]] = {}
        if path.exists():
            try:
                if path.suffix.casefold() == ".jsonl":
                    with path.open("r", encoding="utf-8") as stream:
                        rows = (json.loads(line) for line in stream if line.strip())
                        records = {str(row.get("pmid", "")): dict(row) for row in rows}
                else:
                    import pandas as pd

                    frame = pd.read_parquet(path) if path.suffix.casefold() == ".parquet" else pd.read_csv(path)
                    records = {
                        str(row.get("pmid", "")): row
                        for row in frame.to_dict(orient="records")
                        if str(row.get("pmid", "")).strip()
                    }
            except Exception as exc:
                logger.warning("Unable to load cleaned corpus metadata at %s: %s", path, exc)
        self._records_by_pmid = records
        return records

    def _metadata(self, pmid: str) -> Dict[str, Any]:
        record = self._load_records().get(str(pmid))
        if record is not None:
            return record
        try:
            payload = self._get_qdrant().get_paper_by_pmid(pmid)
            return dict(payload or {})
        except Exception as exc:
            logger.debug("Metadata lookup failed for PMID %s: %s", pmid, exc)
            return {}

    @staticmethod
    def _filter_values(plan: QueryPlan) -> Dict[str, Any]:
        hard_filters = dict(getattr(plan, "hard_filters", {}) or {})
        return {
            "year_min": getattr(plan, "year_min", None)
            if getattr(plan, "year_min", None) is not None
            else hard_filters.get("year_min"),
            "year_max": getattr(plan, "year_max", None)
            if getattr(plan, "year_max", None) is not None
            else hard_filters.get("year_max"),
            "study_types": list(getattr(plan, "study_type_filters", []) or hard_filters.get("study_type_filters", [])),
            "mesh_terms": list(hard_filters.get("mesh_terms", []) or []),
        }

    @staticmethod
    def _passes_filters(record: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
        year_min = filters.get("year_min")
        year_max = filters.get("year_max")
        if year_min is not None or year_max is not None:
            try:
                year = int(record.get("year"))
            except (TypeError, ValueError):
                return False
            if year_min is not None and year < int(year_min):
                return False
            if year_max is not None and year > int(year_max):
                return False
        study_types = {_normal(value) for value in filters.get("study_types", []) if _normal(value)}
        if study_types:
            actual = _normal(record.get("study_type"))
            if not actual or not any(wanted == actual or wanted in actual or actual in wanted for wanted in study_types):
                return False
        mesh_filters = {_normal(value) for value in filters.get("mesh_terms", []) if _normal(value)}
        if mesh_filters:
            actual_terms = {_normal(value) for value in _as_list(record.get("mesh_terms"))}
            if not mesh_filters.issubset(actual_terms):
                return False
        return True

    @staticmethod
    def _make_qdrant_filter(filters: Mapping[str, Any]) -> Any:
        from qdrant_client import models

        must: List[Any] = []
        year_min, year_max = filters.get("year_min"), filters.get("year_max")
        if year_min is not None or year_max is not None:
            range_values: Dict[str, Any] = {}
            if year_min is not None:
                range_values["gte"] = int(year_min)
            if year_max is not None:
                range_values["lte"] = int(year_max)
            must.append(models.FieldCondition(key="year", range=models.Range(**range_values)))
        study_types = list(filters.get("study_types", []) or [])
        if study_types:
            must.append(
                models.Filter(
                    should=[models.FieldCondition(key="study_type", match=models.MatchValue(value=value)) for value in study_types]
                )
            )
        for term in filters.get("mesh_terms", []) or []:
            must.append(models.FieldCondition(key="mesh_terms", match=models.MatchValue(value=term)))
        return models.Filter(must=must) if must else None

    def _dense_search(self, vector: np.ndarray, limit: int, filters: Mapping[str, Any]) -> List[Dict[str, Any]]:
        service = self._get_qdrant()
        qdrant_filter = self._make_qdrant_filter(filters)
        client = getattr(service, "client", None)
        if client is not None and hasattr(client, "query_points"):
            response = client.query_points(
                collection_name=service.collection_name,
                query=np.asarray(vector, dtype=np.float32).tolist(),
                using="dense",
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
            )
            points = response.points
            return [
                {"pmid": str(point.payload.get("pmid", point.id)), "score": float(point.score), "payload": point.payload or {}}
                for point in points
            ]
        if hasattr(service, "search_dense"):
            return service.search_dense(
                vector,
                limit=limit,
                year_min=filters.get("year_min"),
                year_max=filters.get("year_max"),
                study_types=filters.get("study_types"),
                mesh_terms=filters.get("mesh_terms"),
            )
        return []

    @staticmethod
    def _result_rows(results: Iterable[Any]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for item in results:
            if isinstance(item, Mapping):
                rows.append(dict(item))
            elif isinstance(item, tuple) and len(item) >= 2:
                rows.append({"pmid": str(item[0]), "score": float(item[1])})
        return rows

    @staticmethod
    def _candidate_payload(pmid: str, record: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            "pmid": str(record.get("pmid", pmid)),
            "title": str(record.get("title", "") or ""),
            "abstract": str(record.get("abstract", "") or ""),
            "journal": record.get("journal"),
            "year": record.get("year"),
            "authors": _as_list(record.get("authors")),
            "mesh_terms": _as_list(record.get("mesh_terms")),
            "study_type": record.get("study_type", "Other"),
        }

    def search(self, plan: QueryPlan, top_k: int = 10) -> List[RetrievalCandidate]:
        """Search by original/canonical MedCPT, BM25 and route-enabled MeSH graph.

        Every channel is hard-filtered before RRF and candidates retain per-channel
        ranks and scores for the UI/audit trail.
        """
        return self.search_channels(
            plan,
            channels=("dense_original", "dense_canonical", "bm25", "mesh_graph"),
            top_k=top_k,
        )

    def search_channels(
        self, plan: QueryPlan, *, channels: Sequence[str], top_k: int = 10
    ) -> List[RetrievalCandidate]:
        """Run selected production retrieval channels with shared filtering and fusion.

        ``dense_original`` embeds only the preserved user query. Selection is
        useful for controlled benchmark ablations without duplicating retrieval.
        """
        supported = {"dense_original", "dense_canonical", "bm25", "mesh_graph"}
        selected = tuple(dict.fromkeys(channels))
        unknown = set(selected) - supported
        if unknown:
            raise ValueError(f"unsupported retrieval channels: {', '.join(sorted(unknown))}")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        filters = self._filter_values(plan)
        dense_k = max(int(getattr(self.settings, "DENSE_TOP_K", 30)), top_k)
        sparse_k = max(int(getattr(self.settings, "SPARSE_TOP_K", 30)), top_k)
        trace: Dict[str, Any] = {"channels": {}, "filters": filters, "rrf_k": int(getattr(self.settings, "RRF_K", 60))}
        rankings: Dict[str, List[str]] = {}
        raw_scores: Dict[str, Dict[str, float]] = {}
        graph_paths: Dict[str, List[str]] = {}
        metadata: Dict[str, Dict[str, Any]] = {}

        original = str(plan.original_query or plan.clean_query)
        canonical = str(plan.canonical_query or plan.clean_query or original)
        if getattr(plan, "embeddings", None) is not None:
            orig_vector = getattr(plan.embeddings, "original_query_embedding", None)
            canonical_vector = getattr(plan.embeddings, "canonical_query_embedding", None)
        else:
            orig_vector = canonical_vector = None
        if "dense_original" not in selected:
            orig_vector = None
        if "dense_canonical" not in selected:
            canonical_vector = None
        if ("dense_original" in selected and orig_vector is None) or (
            "dense_canonical" in selected and canonical_vector is None
        ):
            try:
                encoder = self._get_query_encoder()
                queries = []
                if "dense_original" in selected and orig_vector is None:
                    queries.append(original)
                if "dense_canonical" in selected and canonical_vector is None:
                    queries.append(canonical)
                matrix = encoder.encode_queries(queries)
                index = 0
                if "dense_original" in selected and orig_vector is None:
                    orig_vector = matrix[index]
                    index += 1
                if "dense_canonical" in selected and canonical_vector is None:
                    canonical_vector = matrix[index]
            except Exception as exc:
                trace["dense_error"] = str(exc)
                logger.warning("MedCPT query encoding failed; lexical retrieval remains available: %s", exc)

        if any(vector is not None for vector in (orig_vector, canonical_vector)):
            for channel, vector in (("dense_original", orig_vector), ("dense_canonical", canonical_vector)):
                if channel not in selected or vector is None:
                    continue
                try:
                    rows = self._result_rows(self._dense_search(np.asarray(vector), dense_k, filters))
                    accepted: List[str] = []
                    for row in rows:
                        pmid = str(row.get("pmid", "")).strip()
                        if not pmid:
                            continue
                        payload = row.get("payload") or {}
                        record = self._metadata(pmid)
                        if not record:
                            record = dict(payload)
                        else:
                            record = {**record, **{key: value for key, value in payload.items() if value is not None}}
                        if not self._passes_filters(record, filters):
                            continue
                        metadata[pmid] = record
                        accepted.append(pmid)
                        raw_scores.setdefault(pmid, {})[channel] = float(row.get("score", 0.0))
                    rankings[channel] = accepted
                    trace["channels"][channel] = {"returned": len(rows), "accepted": len(accepted)}
                except Exception as exc:
                    trace["channels"][channel] = {"returned": 0, "accepted": 0, "error": str(exc)}
                    logger.warning("Dense retrieval channel %s failed: %s", channel, exc)
        else:
            trace["channels"]["dense_original"] = {"returned": 0, "accepted": 0, "error": trace.get("dense_error", "no query embedding")}
            trace["channels"]["dense_canonical"] = {"returned": 0, "accepted": 0, "error": trace.get("dense_error", "no query embedding")}

        bm25 = self._get_bm25() if "bm25" in selected else None
        queries = [original]
        if canonical.casefold() != original.casefold():
            queries.append(canonical)
        if str(getattr(plan, "route", "SIMPLE")).upper() in {"MODERATE", "COMPLEX"}:
            for query in list(getattr(plan, "subqueries", []) or [])[: max(0, int(getattr(self.settings, "MAX_SUBQUERIES", 4)) - len(queries))]:
                if query and all(query.casefold() != old.casefold() for old in queries):
                    queries.append(query)
        if bm25 is not None:
            for index, query in enumerate(queries):
                channel = "bm25" if index == 0 else f"bm25_query_{index + 1}"
                try:
                    rows = self._result_rows(bm25.search(query, top_k=sparse_k))
                    accepted = []
                    for row in rows:
                        pmid = str(row.get("pmid", "")).strip()
                        if not pmid:
                            continue
                        record = self._metadata(pmid)
                        if not record or not self._passes_filters(record, filters):
                            continue
                        metadata[pmid] = record
                        accepted.append(pmid)
                        raw_scores.setdefault(pmid, {})[channel] = float(row.get("score", 0.0))
                    rankings[channel] = accepted
                    trace["channels"][channel] = {"returned": len(rows), "accepted": len(accepted)}
                except Exception as exc:
                    trace["channels"][channel] = {"returned": 0, "accepted": 0, "error": str(exc)}
                    logger.warning("BM25 retrieval channel %s failed: %s", channel, exc)
        else:
            trace["channels"]["bm25"] = {"returned": 0, "accepted": 0, "error": "BM25 index unavailable"}

        route = str(getattr(plan, "route", "SIMPLE")).upper()
        graph = self._get_graph() if "mesh_graph" in selected and route in {"MODERATE", "COMPLEX"} else None
        if graph is not None and list(getattr(plan, "mesh_terms", []) or []):
            graph_scores: Dict[str, float] = {}
            try:
                terms = list(dict.fromkeys(str(term) for term in plan.mesh_terms if str(term).strip()))
                expanded: List[Tuple[str, str]] = [(term, term) for term in terms]
                if hasattr(graph, "expand_query_mesh_terms"):
                    for source_term in terms:
                        for term in graph.expand_query_mesh_terms([source_term], top_k=5):
                            if all(_normal(term) != _normal(existing[0]) for existing in expanded):
                                expanded.append((term, source_term))
                for term, source_term in expanded:
                    for rank, pmid in enumerate(graph.get_papers_for_mesh(term), start=1):
                        pmid = str(pmid)
                        record = self._metadata(pmid)
                        if not record or not self._passes_filters(record, filters):
                            continue
                        score = 1.0 / rank
                        graph_scores[pmid] = max(score, graph_scores.get(pmid, 0.0))
                        graph_paths.setdefault(pmid, [f"query:{source_term}", f"mesh:{term}", f"paper:{pmid}"])
                        metadata[pmid] = record
                graph_ranking = sorted(graph_scores, key=lambda pmid: (-graph_scores[pmid], pmid))
                rankings["mesh_graph"] = graph_ranking[:dense_k]
                for pmid in rankings["mesh_graph"]:
                    raw_scores.setdefault(pmid, {})["mesh_graph"] = graph_scores[pmid]
                trace["channels"]["mesh_graph"] = {"returned": len(graph_scores), "accepted": len(rankings["mesh_graph"])}
            except Exception as exc:
                trace["channels"]["mesh_graph"] = {"returned": 0, "accepted": 0, "error": str(exc)}
                logger.warning("MeSH graph retrieval failed: %s", exc)
        elif route in {"MODERATE", "COMPLEX"}:
            trace["channels"]["mesh_graph"] = {"returned": 0, "accepted": 0, "reason": "graph unavailable or no mapped MeSH terms"}

        rrf_k = int(getattr(self.settings, "RRF_K", 60))
        scores = reciprocal_rank_fusion(rankings, k=rrf_k)
        candidates: List[RetrievalCandidate] = []
        for pmid in sorted(scores, key=lambda item: (-scores[item], item)):
            record = metadata.get(pmid) or self._metadata(pmid)
            if not self._passes_filters(record, filters):
                continue
            channel_ranks = {
                channel: rank
                for channel, ranked in rankings.items()
                for rank, item in enumerate(ranked, start=1)
                if item == pmid
            }
            payload = self._candidate_payload(pmid, record)
            candidates.append(
                RetrievalCandidate(
                    **payload,
                    channel_ranks=channel_ranks,
                    channel_scores=raw_scores.get(pmid, {}),
                    rrf_score=scores[pmid],
                    graph_path=graph_paths.get(pmid),
                    filter_satisfied=True,
                )
            )
        self.last_trace = {
            **trace,
            "channel_rankings": rankings,
            "fused_count": len(candidates),
            "candidate_pmids": [candidate.pmid for candidate in candidates[:top_k]],
        }
        return candidates[:top_k]

    def get_paper(self, pmid: str) -> Optional[Dict[str, Any]]:
        record = self._metadata(str(pmid))
        if not record:
            return None
        # Keep the public paper endpoint metadata-only.  The parquet corpus also
        # contains numpy arrays and internal embedding text that are neither JSON
        # serializable nor part of the API contract.
        year = record.get("year")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None
        return {
            "pmid": str(record.get("pmid", pmid)),
            "title": str(record.get("title", "") or ""),
            "abstract": str(record.get("abstract", "") or ""),
            "authors": _as_list(record.get("authors")),
            "journal": str(record.get("journal", "") or ""),
            "publication_date": str(record.get("publication_date", "") or "") or None,
            "year": year,
            "mesh_terms": _as_list(record.get("mesh_terms")),
            "keywords": _as_list(record.get("keywords")),
            "study_type": str(record.get("study_type", "Other") or "Other"),
            "doi": str(record.get("doi")) if record.get("doi") else None,
        }

    def close(self) -> None:
        if self._qdrant is not None and hasattr(self._qdrant, "close"):
            self._qdrant.close()
