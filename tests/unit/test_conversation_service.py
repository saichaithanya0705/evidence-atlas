import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.conversation.models import ConversationAgentDecision, ConversationTurnRequest
from backend.app.models.request_response import AgentAction, AnswerStatus
from backend.app.storage.accounts import AccountStore
from backend.app.storage.audits import AuditStore
from backend.app.storage.conversations import ConversationBusyError, ConversationStore
from backend.app.storage.database import connect_db, initialize_db


def _setup(path):
    initialize_db(path)
    account = AccountStore(path).create("reader", "Reader", "user", "hash", None, False)
    return account, ConversationStore(path), AuditStore(path)


class _Agent:
    def __init__(self, decision, events):
        self.decision = decision
        self.events = events

    def plan_turn(self, message, history):
        self.events.append(("agent", message, history))
        return self.decision


class _Research:
    def __init__(self, events):
        self.events = events

    def research(self, query, filters, max_loops, request_id, event_sink=None, **kwargs):
        self.events.append(("research", query, filters, max_loops, request_id))
        if event_sink:
            event_sink("answer_released", {"status": "SUPPORTED", "claim_count": 1})
        return {
            "answer_status": AnswerStatus.SUPPORTED,
            "request_id": request_id,
            "query": query,
            "canonical_query": "diabetes",
            "route": "SIMPLE",
            "synthesis": "Evidence supports the outcome [PMID: 12345].",
            "evidence_table": [{"pmid": "12345", "title": "Trial", "key_findings": "Result", "supporting_text_spans": ["Exact span"], "admin_only": "secret"}],
            "cited_pmids": ["12345"],
            "citations_valid": True,
            "citation_precision": 1.0,
            "consensus_level": "consensus",
            "evidence_gaps": [],
            "audit_trace_url": "/trace/secret",
            "retrieved_papers": [{"pmid": "12345", "title": "Trial", "rrf_score": 0.9, "abstract": "Safe abstract"}],
            "raw_prompt": "secret prompt", "model_output": "internal completion", "internal_trace": {"secret": True},
        }

    def get_trace(self, request_id):
        return {"prompt": "secret", "request_id": request_id}


def _decision(action=AgentAction.RESEARCH, **kwargs):
    defaults = dict(
        action=action,
        standalone_query="What is the evidence for diabetes?" if action is AgentAction.RESEARCH else None,
        complexity_hint="SIMPLE" if action is AgentAction.RESEARCH else None,
        decision_summary="Decided based on the current message.",
        message=None,
    )
    defaults.update(kwargs)
    return ConversationAgentDecision(**defaults)


def test_research_turn_finishes_linked_audit_before_completing_public_turn(tmp_path):
    from backend.app.conversation.service import ConversationService

    path = tmp_path / "service.sqlite3"
    account, store, audit = _setup(path)
    events = []
    conversation = store.create(account["id"])
    service = ConversationService(store=store, audit=audit, agent=_Agent(_decision(), events), research=_Research(events))

    response = service.run_turn(conversation["id"], account, ConversationTurnRequest(message="diabetes evidence"))

    assert response.answer_status is AnswerStatus.SUPPORTED
    with connect_db(path) as db:
        turn = dict(db.execute("SELECT * FROM conversation_turns").fetchone())
        run = dict(db.execute("SELECT * FROM query_runs").fetchone())
    assert turn["status"] == "completed"
    assert turn["audit_run_id"] == run["id"]
    assert (run["conversation_id"], run["turn_id"], run["status"]) == (conversation["id"], turn["id"], "completed")
    public = json.loads(turn["public_response_json"])
    assert public["evidence_table"][0]["supporting_text_spans"] == ["Exact span"]
    assert "admin_only" not in public["evidence_table"][0]
    assert "rrf_score" not in public["retrieved_papers"][0]
    assert not {"audit_trace_url", "canonical_query", "route", "citation_precision", "raw_prompt", "model_output", "internal_trace"} & public.keys()
    assert [item[0] for item in events] == ["agent", "research"]
    assert store.detail_for_account(conversation["id"], account["id"])["conversation"]["title"] == "diabetes evidence"


def test_recent_history_and_older_summary_use_bounded_deterministic_fields(tmp_path):
    from backend.app.conversation.service import ConversationService

    class CapturingAgent:
        history = None

        def plan_turn(self, message, history):
            self.history = history
            return _decision(AgentAction.CLARIFY, message="Please clarify the outcome.")

    path = tmp_path / "history.sqlite3"
    account, store, audit = _setup(path)
    conversation = store.create(account["id"])
    for ordinal in range(1, 4):
        row = store.begin_turn(conversation["id"], account["id"], f"intent {ordinal}", turn_id=f"old-{ordinal}")
        store.complete_turn(
            row["id"], agent_action="RESEARCH", standalone_query=f"question {ordinal}",
            complexity_hint="SIMPLE", final_route="SIMPLE", answer_status="SUPPORTED",
            assistant_message=f"answer {ordinal}", audit_run_id=f"audit-{ordinal}",
            public_response={"cited_pmids": [str(100 + ordinal)], "evidence_table": [{"pmid": str(100 + ordinal)}]},
        )
    agent = CapturingAgent()
    service = ConversationService(
        store=store, audit=audit, agent=agent, research=_Research([]),
        settings=SimpleNamespace(conversation_history_turn_limit=2, MAX_CORRECTIVE_LOOPS=2),
    )

    service.run_turn(conversation["id"], account, ConversationTurnRequest(message="follow up"))

    assert [(item.turn_id, item.role) for item in agent.history.recent_turns] == [
        ("old-3", "user"), ("old-3", "assistant"),
    ]
    assert agent.history.older_context_summary == (
        "intent=intent 1; question=question 1; status=SUPPORTED; cited_pmids=101; validated_evidence_ids=101\n"
        "intent=intent 2; question=question 2; status=SUPPORTED; cited_pmids=102; validated_evidence_ids=102"
    )


def test_answer_from_evidence_uses_only_persisted_validated_sources(tmp_path):
    from backend.app.conversation.service import ConversationService

    class EvidenceAgent:
        def plan_turn(self, message, history):
            return ConversationAgentDecision(
            action=AgentAction.ANSWER_FROM_EVIDENCE,
            standalone_query="What did the evidence say about diabetes?",
            referenced_turn_ids=["source-turn"],
            decision_summary="Answering from a prior validated source.",
            )

    class EvidenceResearch(_Research):
        def answer_from_evidence(self, query, *, candidates, evidence, event_sink=None):
            self.events.append(("evidence", query, candidates, evidence))
            return {
                "answer_status": "SUPPORTED", "request_id": "evidence-run", "query": query,
                "synthesis": "A finding is supported [PMID: 12345].", "evidence_table": [item.model_dump(mode="json") for item in evidence],
                "cited_pmids": ["12345"], "evidence_gaps": [], "retrieved_papers": [item.model_dump(mode="json") for item in candidates],
                "consensus_level": "consensus",
            }

    path = tmp_path / "evidence.sqlite3"
    account, store, audit = _setup(path)
    conversation = store.create(account["id"])
    source = store.begin_turn(conversation["id"], account["id"], "diabetes evidence", turn_id="source-turn")
    store.complete_turn(
        source["id"], agent_action="RESEARCH", standalone_query="What is the evidence for diabetes?",
        complexity_hint="SIMPLE", final_route="SIMPLE", answer_status="SUPPORTED",
        assistant_message="Evidence supports the outcome [PMID: 12345].", audit_run_id="source-audit",
        public_response={
            "cited_pmids": ["12345"],
            "evidence_table": [{"pmid": "12345", "title": "Trial", "key_findings": "Result", "supporting_text_spans": ["Exact span"]}],
            "retrieved_papers": [{"pmid": "12345", "title": "Trial", "abstract": "Safe abstract"}],
        },
    )
    events = []
    service = ConversationService(store=store, audit=audit, agent=EvidenceAgent(), research=EvidenceResearch(events))

    second = service.run_turn(conversation["id"], account, ConversationTurnRequest(message="What did that say?"))

    assert events[-1][0] == "evidence"
    assert [item.pmid for item in events[-1][2]] == ["12345"]
    assert [item.pmid for item in events[-1][3]] == ["12345"]
    assert second.action is AgentAction.ANSWER_FROM_EVIDENCE
    saved = store.detail_for_account(conversation["id"], account["id"])["turns"][0]
    assert second.request_id == saved["audit_run_id"]


@pytest.mark.parametrize("action", [AgentAction.CLARIFY, AgentAction.ABSTAIN])
def test_nonresearch_agent_actions_complete_without_calling_research(tmp_path, action):
    from backend.app.conversation.service import ConversationService

    path = tmp_path / f"{action.value}.sqlite3"
    account, store, audit = _setup(path)
    events = []
    conversation = store.create(account["id"])
    decision = _decision(action, message="Please name the treatment and outcome.")
    service = ConversationService(store=store, audit=audit, agent=_Agent(decision, events), research=_Research(events))

    response = service.run_turn(conversation["id"], account, ConversationTurnRequest(message="What about it?"))

    assert response.action is action
    assert response.assistant_message == "Please name the treatment and outcome."
    assert [item[0] for item in events] == ["agent"]


def test_duplicate_running_turn_creates_neither_second_turn_nor_audit(tmp_path):
    from backend.app.conversation.service import ConversationService

    path = tmp_path / "duplicate.sqlite3"
    account, store, audit = _setup(path)
    conversation = store.create(account["id"])
    store.begin_turn(conversation["id"], account["id"], "Already running", turn_id="existing")
    events = []
    service = ConversationService(store=store, audit=audit, agent=_Agent(_decision(), events), research=_Research(events))

    with pytest.raises(ConversationBusyError):
        service.run_turn(conversation["id"], account, ConversationTurnRequest(message="duplicate"))
    with connect_db(path) as db:
        assert db.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM query_runs").fetchone()[0] == 0
    assert events == []


def test_agent_starts_after_linked_audit_and_turn_completes_after_terminal_audit(tmp_path):
    from backend.app.conversation.service import ConversationService

    order = []
    path = tmp_path / "ordering.sqlite3"
    account, base_store, _ = _setup(path)
    conversation = base_store.create(account["id"])

    class OrderedAudit(AuditStore):
        run_id = None

        def start(self, run_id, *args, **kwargs):
            super().start(run_id, *args, **kwargs)
            self.run_id = run_id
            order.append("audit-start")

        def finish(self, run_id, status, *args, **kwargs):
            super().finish(run_id, status, *args, **kwargs)
            order.append("audit-" + status)

    ordered_audit = OrderedAudit(path)

    class OrderedStore(ConversationStore):
        def complete_turn(self, turn_id, *args, **kwargs):
            assert ordered_audit.detail(ordered_audit.run_id)["status"] == "completed"
            order.append("turn-complete")
            return super().complete_turn(turn_id, *args, **kwargs)

    class OrderedAgent:
        def plan_turn(self, message, history):
            assert ordered_audit.detail(ordered_audit.run_id)["status"] == "running"
            order.append("agent")
            return _decision()

    class OrderedResearch(_Research):
        def research(self, *args, **kwargs):
            order.append("research")
            return super().research(*args, **kwargs)

    service = ConversationService(
        store=OrderedStore(path), audit=ordered_audit, agent=OrderedAgent(), research=OrderedResearch([]),
    )
    service.run_turn(conversation["id"], account, ConversationTurnRequest(message="diabetes"))

    assert order == ["audit-start", "agent", "research", "audit-completed", "turn-complete"]


def test_agent_failure_is_persisted_as_failed_turn_and_failed_audit(tmp_path):
    from backend.app.conversation.service import ConversationService

    class BrokenAgent:
        def plan_turn(self, message, history):
            raise RuntimeError("provider secret")

    path = tmp_path / "failure.sqlite3"
    account, store, audit = _setup(path)
    conversation = store.create(account["id"])
    service = ConversationService(store=store, audit=audit, agent=BrokenAgent(), research=_Research([]))

    with pytest.raises(HTTPException) as failure:
        service.run_turn(conversation["id"], account, ConversationTurnRequest(message="diabetes"))
    assert failure.value.status_code == 503
    with connect_db(path) as db:
        turn = dict(db.execute("SELECT * FROM conversation_turns").fetchone())
    assert turn["status"] == "failed"
    assert "provider secret" not in (turn["assistant_message"] or "")
    assert audit.detail(turn["audit_run_id"])["status"] == "failed"


def test_audit_start_failure_fails_turn_without_invoking_agent_or_research(tmp_path):
    from backend.app.conversation.service import ConversationService

    class BrokenAudit(AuditStore):
        def start(self, *args, **kwargs):
            raise RuntimeError("audit unavailable")

    path = tmp_path / "audit-start.sqlite3"
    account, store, _ = _setup(path)
    conversation = store.create(account["id"])
    events = []
    service = ConversationService(store=store, audit=BrokenAudit(path), agent=_Agent(_decision(), events), research=_Research(events))

    with pytest.raises(HTTPException) as failure:
        service.run_turn(conversation["id"], account, ConversationTurnRequest(message="diabetes"))
    assert failure.value.status_code == 503

    with connect_db(path) as db:
        turn = dict(db.execute("SELECT * FROM conversation_turns").fetchone())
        assert db.execute("SELECT COUNT(*) FROM query_runs").fetchone()[0] == 0
    assert turn["status"] == "failed" and turn["audit_run_id"] is None
    assert events == []


def test_terminal_audit_failure_never_completes_or_reports_turn(tmp_path):
    from backend.app.conversation.service import ConversationService

    class FailingFinishAudit(AuditStore):
        def finish(self, run_id, status, response=None, trace=None, error=None):
            if status == "completed":
                raise RuntimeError("audit finish unavailable")
            return super().finish(run_id, status, response, trace, error)

    path = tmp_path / "audit-finish.sqlite3"
    account, store, _ = _setup(path)
    conversation = store.create(account["id"])
    events = []
    service = ConversationService(
        store=store, audit=FailingFinishAudit(path), agent=_Agent(_decision(), events), research=_Research(events),
    )

    with pytest.raises(HTTPException) as failure:
        service.run_turn(conversation["id"], account, ConversationTurnRequest(message="diabetes"))
    assert failure.value.status_code == 503

    with connect_db(path) as db:
        turn = dict(db.execute("SELECT * FROM conversation_turns").fetchone())
    assert turn["status"] == "failed"
    assert FailingFinishAudit(path).detail(turn["audit_run_id"])["status"] == "failed"
    assert [item[0] for item in events] == ["agent", "research"]
