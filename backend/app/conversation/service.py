"""Conversation API orchestration and safe response projections."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from backend.app.conversation.models import (
    ConversationCreateResponse,
    ConversationDetailResponse,
    ConversationHistoryWindow,
    ConversationSummary,
    ConversationTurnContext,
    ConversationTurnPublicResult,
    ConversationTurnRecord,
    ConversationTurnRequest,
    ConversationTurnResponse,
)
from backend.app.models.request_response import (
    AgentAction,
    AnswerStatus,
    EvidenceRecord,
    PublicInterpretation,
    RetrievalCandidate,
)
from backend.app.storage.conversations import ConversationBusyError

logger = logging.getLogger(__name__)

_PUBLIC_CANDIDATE_FIELDS = {
    "pmid", "title", "abstract", "journal", "year", "authors", "mesh_terms", "study_type",
}
_PUBLIC_EVIDENCE_FIELDS = {
    "pmid", "title", "year", "study_design", "population", "intervention", "comparator",
    "outcome", "key_findings", "limitations", "supporting_text_spans", "subquestion_ids",
}


def _value(payload: Any, name: str, default=None):
    return payload.get(name, default) if isinstance(payload, dict) else getattr(payload, name, default)


def public_research_projection(payload: Any, *, include_conversation_fields: bool = False) -> dict[str, Any]:
    """Keep evidence and safe paper metadata while dropping diagnostics and scores."""
    query_plan = _value(payload, "query_plan")
    research_plan = _value(payload, "research_plan")
    coverage_statuses = _value(payload, "coverage_statuses", {}) or {}
    source = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else dict(payload)
    allowed = {"request_id", "query", "synthesis", "cited_pmids", "evidence_gaps"}
    if include_conversation_fields:
        allowed.add("consensus_level")
    result = {key: source[key] for key in allowed if key in source}
    result["evidence_table"] = []
    for row in source.get("evidence_table", []):
        value = row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row)
        public_row = {key: item for key, item in value.items() if key in _PUBLIC_EVIDENCE_FIELDS}
        provenance = value.get("retrieval_provenance")
        if isinstance(provenance, dict):
            channels = []
            for field in ("channel_ranks", "channel_scores"):
                mapping = provenance.get(field)
                if isinstance(mapping, dict):
                    channels.extend(key for key in mapping if isinstance(key, str) and key.strip())
            public_row["retrieval_channels"] = list(dict.fromkeys(channels))
        else:
            channels = value.get("retrieval_channels", [])
            public_row["retrieval_channels"] = list(dict.fromkeys(
                item.strip() for item in channels if isinstance(item, str) and item.strip()
            )) if isinstance(channels, list) else []
        result["evidence_table"].append(public_row)
    result["retrieved_papers"] = [
        {key: value for key, value in (item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)).items()
         if key in _PUBLIC_CANDIDATE_FIELDS}
        for item in source.get("retrieved_papers", [])
    ]
    raw_interpretation = source.get("interpretation")
    if raw_interpretation is None:
        raw_interpretation = _interpretation_source(query_plan, research_plan, coverage_statuses, source)
    try:
        result["interpretation"] = PublicInterpretation.model_validate(raw_interpretation).model_dump(mode="json")
    except (TypeError, ValueError):
        result["interpretation"] = _interpretation_source(None, None, {}, source)
    return result


def _interpretation_source(query_plan: Any, research_plan: Any, coverage_statuses: Any, fallback: dict) -> dict[str, Any]:
    """Build a bounded public interpretation from trusted plan and coverage values."""
    canonical = _value(query_plan, "canonical_query") or fallback.get("canonical_query") or fallback.get("query") or "Research question"
    pico = _value(query_plan, "pico", {}) or {}
    if hasattr(pico, "model_dump"):
        pico = pico.model_dump(mode="json")
    mesh = _value(query_plan, "mesh_terms", []) or []
    route = _value(query_plan, "route") or fallback.get("route") or "SIMPLE"
    nodes = _value(research_plan, "subquestions", []) or []
    subquestions = []
    for node in nodes[:8]:
        identifier = _value(node, "id")
        question = _value(node, "question")
        if isinstance(identifier, str) and isinstance(question, str):
            subquestions.append({"id": identifier[:5], "question": " ".join(question.split())[:500]})
    if isinstance(coverage_statuses, dict):
        coverage_items = coverage_statuses.items()
    else:
        coverage_items = (
            (_value(item, "subquestion_id"), _value(item, "status"))
            for item in coverage_statuses or []
        )
    statuses = []
    for identifier, status in coverage_items:
        status = getattr(status, "value", status)
        if isinstance(identifier, str) and isinstance(status, str):
            statuses.append({"subquestion_id": identifier[:5], "status": status.upper()})
    return {
        "canonical_question": str(canonical).strip()[:4000] or "Research question",
        "pico": pico,
        "mesh_concepts": mesh[:50],
        "route": route,
        "subquestions": subquestions,
        "coverage_statuses": statuses[:8],
    }


class ConversationService:
    def __init__(self, *, store, audit, agent, research, settings=None):
        self.store = store
        self.audit = audit
        self.agent = agent
        self.research = research
        self.settings = settings
        self.history_limit = min(12, int(getattr(settings, "conversation_history_turn_limit", 12)))
        self.max_loops = min(2, int(getattr(settings, "MAX_CORRECTIVE_LOOPS", 2)))

    @staticmethod
    def _account_id(account: dict) -> str:
        return str(account["id"])

    def create(self, account: dict) -> ConversationCreateResponse:
        row = self.store.create(self._account_id(account))
        return ConversationCreateResponse(conversation_id=row["id"], title=row["title"], created_at=row["created_at"])

    def list(self, account: dict, *, limit: int, offset: int) -> dict:
        page = self.store.list_for_account(self._account_id(account), limit=limit, offset=offset)
        return {
            "items": [ConversationSummary(
                conversation_id=item["id"], title=item["title"], created_at=item["created_at"], updated_at=item["updated_at"]
            ) for item in page["items"]],
            "total": page["total"],
        }

    def detail(self, conversation_id: str, account: dict, *, limit: int, offset: int) -> ConversationDetailResponse | None:
        page = self.store.detail_for_account(conversation_id, self._account_id(account), limit=limit, offset=offset)
        if page is None:
            return None
        conversation = page["conversation"]
        turns = []
        for item in page["turns"]:
            result = None
            if item["status"] == "completed" and item.get("public_response_json"):
                try:
                    saved = json.loads(item["public_response_json"])
                    saved = public_research_projection(saved, include_conversation_fields=True)
                    public_fields = (
                        "cited_pmids", "evidence_table", "retrieved_papers", "evidence_gaps", "consensus_level", "interpretation",
                    )
                    result = ConversationTurnPublicResult.model_validate({
                        field: saved[field] for field in public_fields if field in saved
                    })
                except (TypeError, ValueError, ValidationError):
                    result = None
            turns.append(ConversationTurnRecord(
                turn_id=item["id"], sequence=item["ordinal"], user_message=item["user_message"],
                action=item["agent_action"], answer_status=item["answer_status"],
                assistant_message=item["assistant_message"], created_at=item["created_at"], result=result,
            ))
        following = offset + len(turns)
        return ConversationDetailResponse(
            conversation=ConversationSummary(
                conversation_id=conversation["id"], title=conversation["title"],
                created_at=conversation["created_at"], updated_at=conversation["updated_at"],
            ),
            turns=turns,
            next_cursor=str(following) if following < page["total_turns"] else None,
        )

    def _older_summary(self, turns: list[dict]) -> str | None:
        lines = []
        for turn in turns:
            response = {}
            try:
                response = json.loads(turn.get("public_response_json") or "{}")
            except (TypeError, ValueError):
                pass
            pmids = response.get("cited_pmids", [])
            evidence_ids = list(dict.fromkeys(
                str(row.get("pmid", "")) for row in response.get("evidence_table", [])
                if isinstance(row, dict) and str(row.get("pmid", "")).isdigit()
            ))
            fields = [
                "intent=" + str(turn.get("user_message", ""))[:300],
                "question=" + str(turn.get("standalone_query") or "")[:300],
                "status=" + str(turn.get("answer_status") or "unknown"),
                "cited_pmids=" + ",".join(str(value)[:20] for value in pmids[:20]),
                "validated_evidence_ids=" + ",".join(evidence_ids[:20]),
            ]
            lines.append("; ".join(fields))
        summary = "\n".join(lines)[-4000:]
        return summary or None

    def _history(self, conversation_id: str, account: dict, current: dict, current_message: str):
        page = self.store.detail_for_account(conversation_id, self._account_id(account), limit=100, offset=0)
        completed = [row for row in reversed(page["turns"]) if row["status"] == "completed" and row["id"] != current["id"]]
        entries = []
        for row in completed:
            entries.append(ConversationTurnContext(turn_id=row["id"], role="user", content=row["user_message"]))
            if row.get("assistant_message"):
                entries.append(ConversationTurnContext(turn_id=row["id"], role="assistant", content=row["assistant_message"]))
        recent = entries[-self.history_limit:]
        older_entry_ids = {item.turn_id for item in entries[:max(0, len(entries) - len(recent))]}
        older_rows = [row for row in completed if row["id"] in older_entry_ids]
        return ConversationHistoryWindow(
            current_message=current_message,
            older_context_summary=self._older_summary(older_rows),
            recent_turns=recent,
        )

    def _answer_from_prior(self, decision, page):
        by_id = {row["id"]: row for row in page["turns"]}
        candidates, evidence = [], []
        for turn_id in decision.referenced_turn_ids:
            row = by_id.get(turn_id)
            if row is None or row["status"] != "completed" or row["answer_status"] not in {"SUPPORTED", "LIMITED"}:
                continue
            saved = json.loads(row.get("public_response_json") or "{}")
            candidates.extend(RetrievalCandidate.model_validate(item) for item in saved.get("retrieved_papers", []))
            evidence.extend(EvidenceRecord.model_validate(item) for item in saved.get("evidence_table", []))
        if not evidence:
            raise ValueError("No validated evidence is available from the referenced turns")
        return candidates, evidence

    def run_turn(self, conversation_id: str, account: dict, request: ConversationTurnRequest) -> ConversationTurnResponse:
        is_admin = account.get("role") == "admin"
        supplied_controls = {"year_min", "year_max", "study_types", "max_loops"} & request.model_fields_set
        if supplied_controls and not is_admin:
            raise HTTPException(status_code=403, detail="Advanced research controls require an administrator account")
        account_id = self._account_id(account)
        message = request.message.strip()
        existing = self.store.detail_for_account(conversation_id, account_id, limit=1, offset=0)
        if existing is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        turn_id = str(uuid.uuid4())
        try:
            turn = self.store.begin_turn(conversation_id, account_id, message, turn_id=turn_id)
        except ConversationBusyError:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Conversation not found") from exc
        run_id = str(uuid.uuid4())
        audit_started = False
        try:
            if turn["ordinal"] == 1:
                self.store.update_title(conversation_id, account_id, message[:80] or "New research")
            self.audit.start(
                run_id, account, "conversation_turn", message[:4000], {}, {},
                conversation_id=conversation_id, turn_id=turn_id,
            )
            audit_started = True
            history = self._history(conversation_id, account, turn, message)
            decision = self.agent.plan_turn(message, history)
            event_sink = lambda stage, payload: self.audit.event(run_id, stage, payload)
            event_sink("agent_decision", {
                "action": decision.action.value,
                "complexity_hint": decision.complexity_hint,
            })
            research_response = None
            final_route = None
            standalone_query = decision.standalone_query
            complexity_hint = decision.complexity_hint
            if decision.action is AgentAction.RESEARCH:
                filters = {
                    key: value for key, value in (
                        ("year_min", request.year_min), ("year_max", request.year_max),
                        ("study_types", request.study_types),
                    ) if value is not None
                } if is_admin else {}
                max_loops = request.max_loops if is_admin else self.max_loops
                research_response = self.research.research(
                    message, filters, max_loops, run_id, event_sink,
                    agent_rewrite=decision.standalone_query,
                    agent_complexity_hint=decision.complexity_hint,
                )
                final_route = _value(research_response, "route")
                assistant_message = str(_value(research_response, "synthesis", ""))[:4000]
            elif decision.action is AgentAction.ANSWER_FROM_EVIDENCE:
                page = self.store.detail_for_account(conversation_id, account_id, limit=100, offset=0)
                candidates, evidence = self._answer_from_prior(decision, page)
                research_response = self.research.answer_from_evidence(
                    decision.standalone_query, candidates=candidates, evidence=evidence, event_sink=event_sink,
                )
                final_route = _value(research_response, "route")
                assistant_message = str(_value(research_response, "synthesis", ""))[:4000]
            else:
                assistant_message = decision.message or "Please clarify your research question."

            if research_response is None:
                public_payload = {
                    "request_id": run_id, "query": message, "synthesis": assistant_message,
                    "cited_pmids": [], "evidence_gaps": [], "evidence_table": [], "retrieved_papers": [],
                }
                status = AnswerStatus.INSUFFICIENT
                consensus = "insufficient"
            else:
                public_payload = public_research_projection(research_response)
                status = _value(research_response, "answer_status", AnswerStatus.FAILED)
                if isinstance(status, str):
                    status = AnswerStatus(status)
                consensus = _value(research_response, "consensus_level", "insufficient")
                assistant_message = str(_value(research_response, "synthesis", assistant_message))[:4000]
            public_payload["request_id"] = run_id
            public_payload["answer_status"] = status.value

            public_response = {
                "conversation_id": conversation_id,
                "turn_id": turn_id,
                "action": decision.action.value,
                "answer_status": status.value,
                "assistant_message": assistant_message,
                "cited_pmids": public_payload.get("cited_pmids", []),
                "evidence_table": public_payload.get("evidence_table", []),
                "retrieved_papers": public_payload.get("retrieved_papers", []),
                "evidence_gaps": public_payload.get("evidence_gaps", []),
                "consensus_level": consensus,
                "interpretation": public_payload.get("interpretation"),
                "progress_summary": "Evidence review completed." if research_response else "A follow-up detail is needed.",
                "request_id": run_id,
            }
            response = ConversationTurnResponse.model_validate(public_response)
            self.audit.finish(run_id, "completed", public_payload, None)
            self.store.complete_turn(
                turn_id, agent_action=decision.action.value, standalone_query=standalone_query,
                complexity_hint=complexity_hint, final_route=final_route,
                answer_status=status.value, assistant_message=assistant_message,
                audit_run_id=run_id, public_response=public_response,
            )
            return response
        except Exception as exc:
            if audit_started:
                try:
                    self.audit.finish(run_id, "failed", error="Conversation turn failed")
                except Exception:
                    logger.exception("Could not finalize failed conversation audit %s", run_id)
            try:
                self.store.fail_turn(
                    turn_id,
                    assistant_message="A technical failure prevented this turn from completing. Please try again.",
                    audit_run_id=run_id if audit_started else None,
                )
            except Exception:
                logger.exception("Could not persist failed conversation turn %s", turn_id)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=503, detail="The conversation turn could not be completed") from exc
