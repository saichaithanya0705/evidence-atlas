from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.models.request_response import (
    AgentAction,
    AnswerStatus,
    EvidenceRecord,
    PublicSearchCandidate,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def trim_nonblank_strings(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("String values must not be blank")
        return value


def _trim_string_list(values: list[str]) -> list[str]:
    trimmed = [value.strip() for value in values]
    if any(not value for value in trimmed):
        raise ValueError("String values must not be blank")
    return trimmed


class ConversationAgentDecision(_StrictModel):
    action: AgentAction
    standalone_query: str | None = Field(default=None, max_length=4000)
    complexity_hint: Literal["SIMPLE", "MODERATE", "COMPLEX"] | None = None
    referenced_turn_ids: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=20)
    decision_summary: str = Field(max_length=500)
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("referenced_turn_ids")
    @classmethod
    def trim_referenced_turn_ids(cls, values: list[str]) -> list[str]:
        return _trim_string_list(values)

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action is AgentAction.RESEARCH:
            if self.standalone_query is None or self.complexity_hint is None:
                raise ValueError("RESEARCH requires a standalone query and complexity hint")
        elif self.action in (AgentAction.CLARIFY, AgentAction.ABSTAIN):
            if self.message is None:
                raise ValueError("CLARIFY and ABSTAIN require a user-facing message")
            if self.standalone_query is not None:
                raise ValueError("CLARIFY and ABSTAIN cannot include a standalone query")
        elif self.action is AgentAction.ANSWER_FROM_EVIDENCE:
            if not self.referenced_turn_ids or self.standalone_query is None:
                raise ValueError("ANSWER_FROM_EVIDENCE requires referenced turns and a standalone question")
        return self


class ConversationTurnContext(_StrictModel):
    turn_id: str = Field(max_length=100)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ConversationHistoryWindow(_StrictModel):
    current_message: str = Field(max_length=4000)
    older_context_summary: str | None = Field(default=None, max_length=4000)
    recent_turns: list[ConversationTurnContext] = Field(default_factory=list, max_length=12)


class EvidenceGapContext(_StrictModel):
    standalone_question: str = Field(max_length=4000)
    deterministic_grade: Literal["SUFFICIENT", "PARTIAL", "INSUFFICIENT"]
    missing_concepts: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=20)
    missing_subquestions: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=20)
    conflicts: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=20)
    prior_queries: list[Annotated[str, Field(max_length=4000)]] = Field(default_factory=list, max_length=20)
    route_floor: Literal["SIMPLE", "MODERATE", "COMPLEX"]

    @field_validator("missing_concepts", "missing_subquestions", "conflicts", "prior_queries")
    @classmethod
    def trim_context_lists(cls, values: list[str]) -> list[str]:
        return _trim_string_list(values)


class CorrectiveResearchProposal(_StrictModel):
    standalone_query: str = Field(max_length=4000)
    complexity_hint: Literal["SIMPLE", "MODERATE", "COMPLEX"]


class ConversationCreateResponse(_StrictModel):
    conversation_id: str = Field(max_length=100)
    title: str = Field(max_length=80)
    created_at: datetime


class ConversationSummary(_StrictModel):
    conversation_id: str = Field(max_length=100)
    title: str = Field(max_length=80)
    created_at: datetime
    updated_at: datetime


class ConversationTurnRequest(_StrictModel):
    message: str = Field(min_length=1, max_length=4000)


class ConversationTurnRecord(_StrictModel):
    turn_id: str = Field(max_length=100)
    sequence: int = Field(ge=1)
    user_message: str = Field(max_length=4000)
    action: AgentAction
    answer_status: AnswerStatus | None = None
    assistant_message: str | None = Field(default=None, max_length=4000)
    created_at: datetime


class ConversationDetailResponse(_StrictModel):
    conversation: ConversationSummary
    turns: list[ConversationTurnRecord] = Field(default_factory=list, max_length=100)
    next_cursor: str | None = Field(default=None, max_length=200)


class ConversationTurnResponse(_StrictModel):
    conversation_id: str = Field(max_length=100)
    turn_id: str = Field(max_length=100)
    action: AgentAction
    answer_status: AnswerStatus
    assistant_message: str = Field(max_length=4000)
    cited_pmids: list[Annotated[str, Field(max_length=20)]] = Field(default_factory=list, max_length=100)
    evidence_table: list[EvidenceRecord] = Field(default_factory=list, max_length=100)
    retrieved_papers: list[PublicSearchCandidate] = Field(default_factory=list, max_length=100)
    evidence_gaps: list[Annotated[str, Field(max_length=500)]] = Field(default_factory=list, max_length=50)
    consensus_level: Literal["consensus", "mixed", "conflicting", "insufficient"]
    progress_summary: str = Field(max_length=500)
    request_id: str = Field(max_length=100)

    @field_validator("cited_pmids", "evidence_gaps")
    @classmethod
    def trim_string_lists(cls, values: list[str]) -> list[str]:
        return _trim_string_list(values)
