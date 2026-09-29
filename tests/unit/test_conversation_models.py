from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.conversation.models import (
    AgentAction,
    AnswerStatus,
    ConversationAgentDecision,
    ConversationCreateResponse,
    ConversationDetailResponse,
    ConversationHistoryWindow,
    ConversationSummary,
    ConversationTurnContext,
    ConversationTurnRecord,
    ConversationTurnRequest,
    ConversationTurnResponse,
    CorrectiveResearchProposal,
    EvidenceGapContext,
)
from backend.app.core.config import Settings
from backend.app.models.request_response import PublicResearchResponse, ResearchResponse


def test_all_agent_actions_accept_only_their_required_contract():
    research = ConversationAgentDecision(
        action="RESEARCH", standalone_query="  Compare treatments  ",
        complexity_hint="MODERATE", decision_summary="  Search the comparison  ",
    )
    clarify = ConversationAgentDecision(
        action="CLARIFY", message="  Which age group?  ", decision_summary="Need population",
    )
    answer = ConversationAgentDecision(
        action="ANSWER_FROM_EVIDENCE", standalone_query="Resynthesize prior evidence",
        referenced_turn_ids=["turn-1"], decision_summary="Prior evidence addresses this",
    )
    abstain = ConversationAgentDecision(
        action="ABSTAIN", message="Evidence cannot answer this", decision_summary="Insufficient support",
    )

    assert research.standalone_query == "Compare treatments"
    assert research.decision_summary == "Search the comparison"
    assert clarify.message == "Which age group?"
    assert answer.referenced_turn_ids == ["turn-1"]
    assert abstain.action is AgentAction.ABSTAIN


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "RESEARCH", "standalone_query": "Question", "decision_summary": "summary"},
        {"action": "RESEARCH", "standalone_query": "  ", "complexity_hint": "SIMPLE", "decision_summary": "summary"},
        {"action": "RESEARCH", "standalone_query": "Question", "complexity_hint": "SIMPLE", "message": "Not allowed", "decision_summary": "summary"},
        {"action": "RESEARCH", "standalone_query": "Question", "complexity_hint": "SIMPLE", "referenced_turn_ids": ["turn-1"], "decision_summary": "summary"},
        {"action": "CLARIFY", "message": "  ", "decision_summary": "summary"},
        {"action": "CLARIFY", "message": "Clarify", "standalone_query": "Question", "decision_summary": "summary"},
        {"action": "CLARIFY", "message": "Clarify", "complexity_hint": "SIMPLE", "decision_summary": "summary"},
        {"action": "CLARIFY", "message": "Clarify", "referenced_turn_ids": ["turn-1"], "decision_summary": "summary"},
        {"action": "ABSTAIN", "message": "No support", "standalone_query": "Question", "decision_summary": "summary"},
        {"action": "ABSTAIN", "message": "No support", "complexity_hint": "SIMPLE", "decision_summary": "summary"},
        {"action": "ABSTAIN", "message": "No support", "referenced_turn_ids": ["turn-1"], "decision_summary": "summary"},
        {"action": "ANSWER_FROM_EVIDENCE", "standalone_query": "Question", "decision_summary": "summary"},
        {"action": "ANSWER_FROM_EVIDENCE", "referenced_turn_ids": ["turn-1"], "decision_summary": "summary"},
        {"action": "ANSWER_FROM_EVIDENCE", "standalone_query": "Question", "referenced_turn_ids": ["  "], "decision_summary": "summary"},
        {"action": "ANSWER_FROM_EVIDENCE", "standalone_query": "Question", "referenced_turn_ids": ["turn-1"], "complexity_hint": "SIMPLE", "decision_summary": "summary"},
        {"action": "ANSWER_FROM_EVIDENCE", "standalone_query": "Question", "referenced_turn_ids": ["turn-1"], "message": "Not allowed", "decision_summary": "summary"},
        {"action": "RESEARCH", "standalone_query": "Question", "complexity_hint": "SIMPLE", "decision_summary": "summary", "unknown": True},
    ],
)
def test_agent_decision_rejects_cross_field_and_extra_field_errors(payload):
    with pytest.raises(ValidationError):
        ConversationAgentDecision(**payload)


def test_agent_decision_rejects_blank_oversized_and_unknown_strings():
    for summary in (" ", "x" * 501):
        with pytest.raises(ValidationError):
            ConversationAgentDecision(action="ABSTAIN", message="No", decision_summary=summary)
    with pytest.raises(ValidationError):
        ConversationAgentDecision(action="ABSTAIN", message="x" * 1001, decision_summary="summary")
    with pytest.raises(ValidationError):
        ConversationAgentDecision(action="UNSUPPORTED", message="No", decision_summary="summary")
    with pytest.raises(ValidationError):
        ConversationAgentDecision(action="RESEARCH", standalone_query="x" * 4001, complexity_hint="SIMPLE", decision_summary="summary")


def test_conversation_turn_request_trims_and_enforces_one_to_four_thousand_characters():
    assert ConversationTurnRequest(message="  Find evidence  ").message == "Find evidence"
    for message in ("", " \t ", "x" * 4001):
        with pytest.raises(ValidationError):
            ConversationTurnRequest(message=message)
    with pytest.raises(ValidationError):
        ConversationTurnRequest(message="question", max_loops=5)
    for admin_control in (
        {"year_min": 2020},
        {"study_types": ["Randomized Controlled Trial"]},
        {"max_loops": 2},
    ):
        with pytest.raises(ValidationError):
            ConversationTurnRequest(message="question", **admin_control)


def test_research_response_defaults_to_supported_without_breaking_old_payloads():
    response = ResearchResponse(
        request_id="req-1", query="q", canonical_query="q", route="SIMPLE", synthesis="s",
        citations_valid=True, citation_precision=1.0, audit_trace_url="/audit/req-1",
    )
    assert response.answer_status is AnswerStatus.SUPPORTED
    assert response.model_dump(mode="json")["answer_status"] == "SUPPORTED"
    assert response.evidence_gaps == []


def test_research_response_sanitizes_and_bounds_structured_evidence_gaps():
    response = ResearchResponse(
        request_id="req-gaps", query="q", canonical_query="q", route="SIMPLE", synthesis="s",
        citations_valid=True, citation_precision=1.0, audit_trace_url="/audit/req-gaps",
        evidence_gaps=["  Missing   safety evidence  ", "x" * 900] + [f"gap {i}" for i in range(25)],
    )

    assert response.evidence_gaps[0] == "Missing safety evidence"
    assert len(response.evidence_gaps) <= 20
    assert all(len(gap) <= 500 for gap in response.evidence_gaps)
    public_response = PublicResearchResponse(query="q", synthesis="s", evidence_gaps=response.evidence_gaps)
    assert public_response.model_dump(mode="json")["evidence_gaps"] == response.evidence_gaps


def test_conversation_response_types_validate_and_serialize_public_contracts():
    now = datetime.now(timezone.utc)
    summary = ConversationSummary(conversation_id="c-1", title="Title", created_at=now, updated_at=now)
    created = ConversationCreateResponse(conversation_id="c-1", title="Title", created_at=now)
    turn = ConversationTurnRecord(
        turn_id="t-1", sequence=1, user_message="Question", action="RESEARCH",
        answer_status="SUPPORTED", assistant_message="Answer", created_at=now,
    )
    detail = ConversationDetailResponse(conversation=summary, turns=[turn], next_cursor=None)
    gap = EvidenceGapContext(
        standalone_question="What are the safety outcomes?",
        deterministic_grade="PARTIAL",
        missing_concepts=["safety"],
        missing_subquestions=["Which serious adverse events were observed?"],
        conflicts=["Trials report different rates."],
        prior_queries=["metformin safety outcomes"],
        route_floor="MODERATE",
    )
    proposal = CorrectiveResearchProposal(standalone_query="Compare safety", complexity_hint="MODERATE")
    history = ConversationHistoryWindow(
        current_message="Follow up", older_context_summary="Earlier asked about treatment",
        recent_turns=[ConversationTurnContext(turn_id="t-1", role="user", content="Question")],
    )
    response = ConversationTurnResponse(
        conversation_id="c-1", turn_id="t-2", action="RESEARCH", answer_status="LIMITED",
        assistant_message="Limited findings", cited_pmids=[], evidence_table=[], retrieved_papers=[],
        evidence_gaps=["Safety evidence missing"], consensus_level="insufficient",
        progress_summary="Research complete", request_id="req-2",
    )
    assert created.conversation_id == summary.conversation_id
    assert detail.turns[0].sequence == 1
    assert gap.standalone_question == "What are the safety outcomes?"
    assert gap.deterministic_grade == "PARTIAL"
    assert gap.route_floor == "MODERATE"
    assert proposal.complexity_hint == "MODERATE"
    assert history.recent_turns[0].content == "Question"
    assert response.model_dump(mode="json")["answer_status"] == "LIMITED"


def test_failed_turn_record_keeps_failure_status_without_fabricating_agent_action():
    from backend.app.conversation.models import ConversationTurnRecord

    failed = ConversationTurnRecord(
        turn_id="t-failed", sequence=2, user_message="Question", action=None,
        answer_status="FAILED", assistant_message="A technical failure occurred.",
        created_at=datetime.now(timezone.utc),
    )

    assert failed.action is None
    assert failed.answer_status.value == "FAILED"


def test_evidence_gap_context_requires_complete_bounded_planner_inputs():
    values = {
        "standalone_question": "What are the safety outcomes?",
        "deterministic_grade": "INSUFFICIENT",
        "missing_concepts": ["adverse events"],
        "missing_subquestions": ["Which serious adverse events were reported?"],
        "conflicts": ["Two trials report different rates."],
        "prior_queries": ["metformin adverse events"],
        "route_floor": "MODERATE",
    }

    gap = EvidenceGapContext(**values)

    assert gap.model_dump() == values


@pytest.mark.parametrize(
    "changes",
    [
        {"standalone_question": None},
        {"standalone_question": "x" * 4001},
        {"deterministic_grade": "UNKNOWN"},
        {"route_floor": "UNKNOWN"},
        {"missing_subquestions": ["x" * 501]},
        {"missing_subquestions": [" "]},
        {"conflicts": ["x" * 1001]},
        {"prior_queries": ["x" * 4001]},
        {"filters": {"year_min": 2020}},
    ],
)
def test_evidence_gap_context_rejects_missing_invalid_oversized_and_extra_values(changes):
    values = {
        "standalone_question": "What are the safety outcomes?",
        "deterministic_grade": "INSUFFICIENT",
        "missing_concepts": ["adverse events"],
        "missing_subquestions": ["Which serious adverse events were reported?"],
        "conflicts": ["Two trials report different rates."],
        "prior_queries": ["metformin adverse events"],
        "route_floor": "MODERATE",
    }
    values.update(changes)

    with pytest.raises(ValidationError):
        EvidenceGapContext(**values)


def test_conversation_settings_have_bounded_conservative_defaults():
    settings = Settings(_env_file=None, DEVICE="cpu")
    assert settings.conversation_history_turn_limit == 12
    assert settings.conversation_message_max_chars == 4000
    assert settings.conversation_title_max_chars == 80
    assert settings.conversation_turn_timeout_seconds == 120
    assert settings.agent_output_max_tokens == 800
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DEVICE="cpu", conversation_message_max_chars=0)
