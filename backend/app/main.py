"""FastAPI entrypoint for the Evidence Atlas research application."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
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
from backend.app.auth.routes import router as auth_router
from backend.app.auth.security import get_current_account, require_admin, require_admin_csrf, require_ready_account, require_ready_csrf
from backend.app.admin.routes import router as admin_router
from backend.app.conversation.routes import router as conversation_router
from backend.app.conversation.service import public_research_projection
from backend.app.storage.audits import AuditStore
from backend.app.storage.database import initialize_db

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
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(conversation_router)


@app.on_event("startup")
def initialize_application_storage() -> None:
    initialize_db(get_settings().APP_DATABASE_PATH)
    AuditStore(get_settings().APP_DATABASE_PATH).recover_interrupted()

_query_service = QueryAnalysisService()
_research_service: Optional[Any] = None
_service_lock = Lock()


def _public_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Return result metadata safe for non-administrator clients."""
    allowed = {
        "pmid", "title", "abstract", "journal", "year", "authors", "mesh_terms",
        "study_type",
    }
    return {key: value for key, value in candidate.items() if key in allowed}


def _public_research_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Keep safe synthesis, exact evidence rows, and public paper metadata."""
    return public_research_projection(payload)


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
        try:
            account = get_current_account(request)
        except HTTPException:
            account = None
        if account:
            try:
                body = await request.body()
                oversized = len(body) > 20000
                try:
                    data = json.loads(body) if body and not oversized else {}
                except (ValueError, UnicodeDecodeError):
                    data = {}
                data = data if isinstance(data, dict) else {}
                run_id = str(uuid.uuid4())
                request.state.audit_id = run_id
                request.state.audit_requested_keys = set(data) - {"query"}
                question = str(data.get("query", ""))
                long_question = len(question) > 4000
                allowed_controls = {"year_min", "year_max", "study_types", "max_loops", "top_k", "route_override"}
                controls = {key: data[key] for key in allowed_controls & data.keys()}
                unsupported = set(data) - allowed_controls - {"query"}
                if unsupported:
                    controls["unsupported_fields_count"] = len(unsupported)
                if oversized:
                    controls = {"request_too_large": True, "bytes": len(body)}
                if long_question:
                    controls["original_query_length"] = len(question)
                AuditStore(get_settings().APP_DATABASE_PATH).start(
                    run_id, account, request.url.path.lstrip("/"),
                    question[:4000], controls, {},
                )
                if oversized or long_question:
                    AuditStore(get_settings().APP_DATABASE_PATH).finish(run_id, "rejected", error="Query request exceeds the allowed size")
                    telemetry.end((perf_counter() - started) * 1000.0, failed=False)
                    return JSONResponse({"detail": "Query request is too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Query is too long"}, status_code=413)
            except Exception:
                logger.exception("Could not open a query audit record")
                return JSONResponse({"detail": "Query audit storage is unavailable"}, status_code=503)
    failed = False
    try:
        response = await call_next(request)
        failed = response.status_code >= 500
        run_id = getattr(request.state, "audit_id", None)
        if run_id:
            try:
                audit = AuditStore(get_settings().APP_DATABASE_PATH)
                if audit.detail(run_id)["status"] == "running":
                    audit.finish(run_id, "failed" if failed else "rejected", error=f"Request ended with status {response.status_code}")
            except Exception:
                logger.exception("Could not finalize query audit record")
                return JSONResponse({"detail": "Query audit storage is unavailable"}, status_code=503)
        return response
    except Exception:
        failed = True
        run_id = getattr(request.state, "audit_id", None)
        if run_id:
            try:
                audit = AuditStore(get_settings().APP_DATABASE_PATH)
                if audit.detail(run_id)["status"] == "running":
                    audit.finish(run_id, "failed", error="Research execution failed")
            except Exception:
                logger.exception("Could not persist failed query audit")
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
) -> Dict[str, Any]:
    manifest_path = Path(settings.INDEX_MANIFEST_PATH)
    records = 0
    if manifest_path.exists():
        try:
            records = int(json.loads(manifest_path.read_text(encoding="utf-8"))["corpus"]["total_records"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("Index manifest exists but is malformed: %s", manifest_path)
    ready = records > 0 and Path(settings.BM25_INDEX_PATH).exists() and Path(settings.MESH_DICT_PATH).exists()
    return {
        "status": "healthy" if ready else "degraded",
        "service": "Evidence Atlas",
        "version": app.version,
    }


@app.get("/metrics")
def metrics(
    account: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, float | int]:
    return telemetry.snapshot()


@app.post("/analyze-query")
async def analyze_query(
    payload: AnalyzeQueryRequest,
    request: Request,
    account: Dict[str, Any] = Depends(require_admin_csrf),
) -> Dict[str, Any]:
    plan, _ = await run_in_threadpool(_query_service.build_query_plan, payload.query)
    result = plan.model_dump(mode="json", exclude={"embeddings"})
    AuditStore(get_settings().APP_DATABASE_PATH).finish(request.state.audit_id, "completed", result, {"query_plan": result})
    return result


@app.post("/search")
async def search(
    payload: SearchRequest,
    request: Request,
    account: Dict[str, Any] = Depends(require_ready_csrf),
) -> Dict[str, Any]:
    is_admin = account["role"] == "admin"
    if not is_admin and getattr(request.state, "audit_requested_keys", set()):
        raise HTTPException(status_code=403, detail="Advanced search controls require administrator access")
    audit = AuditStore(get_settings().APP_DATABASE_PATH)
    audit.applied(request.state.audit_id, {"top_k": payload.top_k})
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
        audit.finish(request.state.audit_id, "completed", response, {"query_plan": plan.model_dump(mode="json", exclude={"embeddings"})})
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
    audit.finish(request.state.audit_id, "completed", response, trace)
    return response


@app.post("/research")
async def research(
    payload: ResearchRequest,
    request: Request,
    account: Dict[str, Any] = Depends(require_ready_csrf),
) -> Dict[str, Any]:
    is_admin = account["role"] == "admin"
    if not is_admin and getattr(request.state, "audit_requested_keys", set()):
        raise HTTPException(status_code=403, detail="Advanced research controls require administrator access")
    audit = AuditStore(get_settings().APP_DATABASE_PATH)
    audit.applied(request.state.audit_id, {
        "year_min": payload.year_min if is_admin else None,
        "year_max": payload.year_max if is_admin else None,
        "study_types": payload.study_types if is_admin else None,
        "max_loops": payload.max_loops if is_admin else 2,
    })
    service = _get_research_service()
    try:
        response = await run_in_threadpool(
            service.research,
            payload.query,
            {
                "year_min": payload.year_min,
                "year_max": payload.year_max,
                "study_types": payload.study_types,
            },
            payload.max_loops,
            request.state.audit_id,
            lambda stage, details: audit.event(request.state.audit_id, stage, details),
        )
    except Exception as exc:
        logger.exception("Research execution failed for audit %s", request.state.audit_id)
        raise HTTPException(status_code=503, detail="Research could not be completed. Review the audit entry.") from exc
    result = response.model_dump(mode="json")
    trace_payload = await run_in_threadpool(service.get_trace, request.state.audit_id)
    audit.finish(request.state.audit_id, "completed", result, trace_payload)
    return result if is_admin else _public_research_response(result)


@app.get("/paper/{pmid}")
async def paper_detail(pmid: str, account: Dict[str, Any] = Depends(require_ready_account)) -> Dict[str, Any]:
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
    account: Dict[str, Any] = Depends(require_admin),
) -> Dict[str, Any]:
    detail = AuditStore(get_settings().APP_DATABASE_PATH).admin_detail(request_id)
    if detail is not None:
        return detail["trace"] or {"request_id": request_id, "events": detail["events"], "status": detail["status"]}
    return {
        "request_id": request_id,
        "stages": [],
        "status": "not_found",
        "message": "No retained trace exists for this request id.",
    }
