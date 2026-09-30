"""Session protected conversation endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from backend.app.auth.security import require_ready_account, require_ready_csrf
from backend.app.conversation.agent import ConversationAgent
from backend.app.conversation.models import (
    ConversationCreateResponse,
    ConversationDetailResponse,
    ConversationTurnRequest,
    ConversationTurnResponse,
)
from backend.app.conversation.service import ConversationService
from backend.app.core.config import get_settings
from backend.app.storage.audits import AuditStore
from backend.app.storage.conversations import ConversationBusyError, ConversationStore

router = APIRouter()


def get_conversation_service() -> ConversationService:
    """Build the service and its collaborators in one replaceable factory."""
    settings = get_settings()
    path = settings.APP_DATABASE_PATH
    return ConversationService(
        store=ConversationStore(path),
        audit=AuditStore(path),
        agent=ConversationAgent(settings),
        research=_LazyResearch(),
        settings=settings,
    )


class _LazyResearch:
    def __getattr__(self, name):
        from backend.app.main import _get_research_service

        return getattr(_get_research_service(), name)


@router.post("/conversations", response_model=ConversationCreateResponse, status_code=201)
def create_conversation(account=Depends(require_ready_csrf), service=Depends(get_conversation_service)):
    return service.create(account)


@router.get("/conversations")
def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    account=Depends(require_ready_account),
    service=Depends(get_conversation_service),
):
    return service.list(account, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def conversation_detail(
    conversation_id: str,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    account=Depends(require_ready_account),
    service=Depends(get_conversation_service),
):
    result = service.detail(conversation_id, account, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if account.get("role") == "admin":
        return JSONResponse(content=result.model_dump(mode="json"))
    return result


@router.post("/conversations/{conversation_id}/turns", response_model=ConversationTurnResponse)
async def run_conversation_turn(
    conversation_id: str,
    payload: ConversationTurnRequest,
    account=Depends(require_ready_csrf),
    service=Depends(get_conversation_service),
):
    try:
        return await run_in_threadpool(service.run_turn, conversation_id, account, payload)
    except ConversationBusyError as exc:
        raise HTTPException(status_code=409, detail="A turn is already running for this conversation") from exc
