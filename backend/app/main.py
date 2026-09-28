"""FastAPI entrypoint for the Evidence Atlas research application."""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import get_settings
from backend.app.models.request_response import (
    AnalyzeQueryRequest,
    ResearchRequest,
    SearchRequest,
)
from backend.app.query.query_service import QueryAnalysisService
from backend.app.services.telemetry import telemetry

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Evidence Atlas API",
    version="1.0.0",
    description="Adaptive hybrid retrieval and evidence-grounded biomedical research API.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_query_service = QueryAnalysisService()
_research_service: Optional[Any] = None
_service_lock = Lock()


def _admin_key_matches(provided: Optional[str]) -> bool:
    """Validate the administrator credential without leaking timing details."""
    configured = settings.get_raw_admin_api_key()
    if not configured or not provided:
        return False
    return secrets.compare_digest(str(provided), configured)


def _require_admin(provided: Optional[str]) -> None:
    if not settings.get_raw_admin_api_key():
        raise HTTPException(status_code=503, detail="Administrator diagnostics are not configured on this service.")
    if not _admin_key_matches(provided):
        raise HTTPException(status_code=403, detail="Administrator credentials are required for this resource.")


def _public_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Return result metadata safe for non-administrator clients."""
    allowed = {
        "pmid", "title", "abstract", "journal", "year", "authors", "mesh_terms",
        "study_type",
    }
    return {key: value for key, value in candidate.items() if key in allowed}


def _public_research_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return only ordinary-user synthesis content, never diagnostics."""
    allowed = {
        "query", "synthesis", "cited_pmids",
    }
    result = {key: value for key, value in payload.items() if key in allowed}
    result["evidence_table"] = []
    result["retrieved_papers"] = [
        _public_candidate(item) for item in payload.get("retrieved_papers", [])
    ]
    return result


def _get_research_service():
    """Construct heavyweight retrieval services once, on first real request."""
    global _research_service
    if _research_service is None:
        with _service_lock:
            if _research_service is None:
                from backend.app.workflow import ResearchService

                _research_service = ResearchService()
    return _research_service


@app.middleware("http")
async def record_request_metrics(request: Request, call_next):
    tracked_query = request.url.path in {"/research", "/search", "/analyze-query"}
    started = perf_counter()
    if tracked_query:
        telemetry.begin()
    failed = False
    try:
        response = await call_next(request)
        failed = response.status_code >= 500
        return response
    except Exception:
        failed = True
        raise
    finally:
        if tracked_query:
            telemetry.end((perf_counter() - started) * 1000.0, failed=failed)


@app.on_event("shutdown")
def close_services() -> None:
    global _research_service
    if _research_service is not None:
        try:
            _research_service.close()
        finally:
            _research_service = None


@app.get("/health")
def health(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    manifest_path = Path(settings.INDEX_MANIFEST_PATH)
    records = 0
    if manifest_path.exists():
        try:
            records = int(json.loads(manifest_path.read_text(encoding="utf-8"))["corpus"]["total_records"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Index manifest exists but is malformed: %s", manifest_path)
    model_root = Path(settings.MODELS_CACHE_DIR)
    model_markers = list(model_root.glob("models--ncbi--MedCPT-*")) if model_root.exists() else []
    ready = records > 0 and Path(settings.BM25_INDEX_PATH).exists() and Path(settings.MESH_DICT_PATH).exists()
    public_status = {
        "status": "healthy" if ready else "degraded",
        "service": "Evidence Atlas",
        "version": app.version,
    }
    if not _admin_key_matches(x_admin_key):
        return public_status
    return {
        **public_status,
        "qdrant_connected": Path(settings.QDRANT_STORAGE_PATH).exists(),
        "corpus_records_loaded": records,
        "mesh_service_loaded": Path(settings.MESH_DICT_PATH).exists(),
        "models_cached": len(model_markers) >= 3,
    }


@app.get("/metrics")
def metrics(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> Dict[str, float | int]:
    _require_admin(x_admin_key)
    return telemetry.snapshot()


@app.post("/admin/verify")
def verify_admin(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")) -> Dict[str, bool]:
    _require_admin(x_admin_key)
    return {"authenticated": True}


@app.post("/analyze-query")
async def analyze_query(
    payload: AnalyzeQueryRequest,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    _require_admin(x_admin_key)
    plan, _ = await run_in_threadpool(_query_service.build_query_plan, payload.query)
    return plan.model_dump(mode="json", exclude={"embeddings"})


@app.post("/search")
async def search(
    payload: SearchRequest,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    is_admin = _admin_key_matches(x_admin_key)
    if payload.top_k == 0:
        plan, _ = await run_in_threadpool(
            _query_service.build_query_plan,
            payload.query,
            {
                "year_min": payload.year_min,
                "year_max": payload.year_max,
                "study_types": payload.study_types,
            },
        )
        response = {"query": payload.query, "total_results": 0, "candidates": []}
        if is_admin:
            response.update({"canonical_query": plan.canonical_query, "route": payload.route_override or plan.route})
        return response
    service = _get_research_service()
    plan, candidates, trace = await run_in_threadpool(
        service.search,
        payload.query,
        payload.top_k,
        {
            "year_min": payload.year_min,
            "year_max": payload.year_max,
            "study_types": payload.study_types,
        },
        payload.route_override,
    )
    response = {
        "query": payload.query,
        "canonical_query": plan.canonical_query,
        "route": payload.route_override or plan.route,
        "total_results": len(candidates),
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    if is_admin:
        response["trace"] = trace
    else:
        response = {
            "query": response["query"],
            "total_results": response["total_results"],
            "candidates": [_public_candidate(item) for item in response["candidates"]],
        }
    return response


@app.post("/research")
async def research(
    payload: ResearchRequest,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    is_admin = _admin_key_matches(x_admin_key)
    service = _get_research_service()
    response = await run_in_threadpool(
        service.research,
        payload.query,
        {
            "year_min": payload.year_min,
            "year_max": payload.year_max,
            "study_types": payload.study_types,
        },
        payload.max_loops,
        None,
    )
    result = response.model_dump(mode="json")
    return result if is_admin else _public_research_response(result)


@app.get("/paper/{pmid}")
async def paper_detail(pmid: str) -> Dict[str, Any]:
    if not pmid.isdigit() or int(pmid) <= 0:
        raise HTTPException(status_code=404, detail="Paper not found")
    paper = await run_in_threadpool(_get_research_service().get_paper, pmid)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    result = dict(paper)
    result["pmid"] = str(result.get("pmid", pmid))
    result["pubmed_url"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return result


@app.get("/trace/{request_id}")
async def trace(
    request_id: str,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> Dict[str, Any]:
    _require_admin(x_admin_key)
    service = _get_research_service()
    stored = await run_in_threadpool(service.get_trace, request_id)
    if stored is not None:
        return stored
    return {
        "request_id": request_id,
        "stages": [],
        "status": "not_found",
        "message": "No retained trace exists for this request id.",
    }
