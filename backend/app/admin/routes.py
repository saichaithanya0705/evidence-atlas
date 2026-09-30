"""Read-only audit history and observability endpoints."""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.auth.security import require_admin
from backend.app.core.config import get_settings
from backend.app.evaluation.service import EvaluationList, EvaluationReport, get_evaluation, list_evaluations
from backend.app.storage.audits import AuditStore

router = APIRouter(prefix="/admin")


@router.get("/evaluations", response_model=EvaluationList)
def evaluations(administrator=Depends(require_admin)):
    return list_evaluations()


@router.get("/evaluations/{run_id:path}", response_model=EvaluationReport)
def evaluation_detail(run_id: str, administrator=Depends(require_admin)):
    return get_evaluation(run_id)


def store():
    return AuditStore(get_settings().APP_DATABASE_PATH)


@router.get("/audits")
def audits(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
           account: str | None = None, status: str | None = None, query: str | None = None,
           from_date: str | None = None, to_date: str | None = None,
           administrator=Depends(require_admin)):
    return store().list_runs(limit=limit, offset=offset, account=account, status=status,
                             query=query, from_date=from_date, to_date=to_date)


@router.get("/audits/{run_id}")
def audit_detail(run_id: str, administrator=Depends(require_admin)):
    result = store().admin_detail(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return result


@router.get("/observability")
def observability(days: int = Query(30, ge=1, le=365), administrator=Depends(require_admin)):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return {"period_days": days, **store().aggregate(since)}
