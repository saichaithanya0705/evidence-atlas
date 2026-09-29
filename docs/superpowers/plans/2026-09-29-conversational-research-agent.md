# Conversational Research Agent and Evidence Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-shot biomedical research screen with persistent, evidence-grounded conversations and a collapsible, one-tab-per-paper evidence workspace without weakening the current retrieval, citation, authorization, or audit boundaries.

**Architecture:** A schema-constrained conversation agent interprets each turn and proposes an action, standalone query, and advisory complexity. The existing biomedical query enhancer then normalizes the proposal; the guarded router chooses the final route and owns budgets. The research workflow may return structured evidence gaps to the agent for bounded corrective queries, but deterministic budgets, exact PMID/span validation, an independent semantic verifier, and fail-closed release rules decide what reaches the user. Conversations persist public results, while complete traces stay in linked administrator audits.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, LangGraph, OpenAI-compatible NVIDIA NIM client, pytest, React 18, Vite, CSS, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-29-conversational-research-agent-design.md`

**Execution:** Use `superpowers:subagent-driven-development`. Dispatch one fresh `gpt-6-luna` implementation agent per task. After each task, run a separate spec-compliance review and then a code-quality review before accepting the task. Do not let agents overwrite unrelated changes in the current dirty worktree; stage only the files named by the task.

## Global Constraints

- Treat this as a biomedical literature research interface, not medical advice or a clinical decision system.
- Never release a biomedical claim solely from model memory. Every released claim must have a retrieved PMID and an exact supporting span.
- The agent may suggest `SIMPLE`, `MODERATE`, or `COMPLEX`; the router computes the final route as the maximum of the rule floor, the valid agent hint, and any prior route floor.
- The enhancer remains between every agent-created query and retrieval, including corrective queries.
- LLM judgments can downgrade or request more research. They cannot bypass filters, raise budgets, invent sources, or promote evidence over deterministic hard gates.
- One conversation may have only one running turn. A duplicate concurrent submission returns `409` and does not create a second audit run.
- Ordinary users receive public paper metadata, exact evidence spans, answer status, and evidence gaps. They never receive prompts, raw model output, internal scores, hidden reasoning, or other users' data.
- Every turn, including clarification and abstention, has one linked audit run. Audit events store bounded summaries and structured state, never chain-of-thought.
- Evidence is collapsed by default. Opening the same PMID from any turn focuses its existing tab and the selected span; it never creates a duplicate paper tab.
- Preserve existing `/research`, `/search`, `/analyze-query`, administrator routes, and their tests while introducing the conversation API.
- Do not stream draft model text. A complete answer must pass the release gate before any biomedical claim is rendered.
- Do not rebuild or modify PubMed corpus artifacts, embeddings, BM25 data, the MeSH graph, or the Qdrant collection for this feature.
- Preserve user-owned uncommitted changes. Before editing an existing file, inspect its diff; use narrow patches and stage explicit paths only.

## Review Focus

1. **Grounding failure:** malformed/injected agent or verifier output must fall back, prune unsupported claims, or abstain; it must never become a medical answer. Covered by Tasks 3, 5, 6, and 11.
2. **Route authority:** the agent cannot lower a rule-recognized route, skip enhancement, repeat a query, or exceed correction budgets. Covered by Tasks 4 and 6.
3. **Conversation integrity:** ownership, pagination, reload, failure recovery, and simultaneous submissions must not leak or duplicate state. Covered by Tasks 2, 7, and 11.
4. **Evidence-tab identity:** repeated citations to the same PMID across turns use one tab while changing the active supporting span correctly. Covered by Tasks 9 and 11.
5. **Public/admin boundary:** public responses expose useful spans but no trace internals; linked conversation, agent, router, judge, and validator events remain available to administrators. Covered by Tasks 7, 10, and 11.

## Planned File Map

### New backend files

- `backend/app/conversation/__init__.py` — package exports.
- `backend/app/conversation/models.py` — strict agent, gap-review, persistence, and API contracts.
- `backend/app/conversation/agent.py` — bounded OpenAI-compatible planning and gap-review client.
- `backend/app/conversation/service.py` — turn lifecycle and orchestration.
- `backend/app/conversation/routes.py` — authenticated conversation endpoints.
- `backend/app/storage/conversations.py` — owned conversation and turn persistence.
- `backend/app/workflow/verification.py` — semantic claim verification constrained by exact evidence spans.

### Modified backend files

- `backend/app/core/config.py` — bounded conversation/agent settings.
- `backend/app/storage/database.py` — additive schema migration.
- `backend/app/storage/audits.py` — conversation/turn links and named-column inserts.
- `backend/app/query/models.py` — enhancement and arbitration metadata.
- `backend/app/query/query_service.py` — separate enhancement from routing.
- `backend/app/query/router.py` — final route arbitration.
- `backend/app/workflow/judge.py` — structured gaps, conflicts, and conservative LLM merge.
- `backend/app/workflow/service.py` — agent-advised initial and corrective retrieval.
- `backend/app/workflow/synthesis.py` — independent semantic verifier hook and fail-closed repair.
- `backend/app/models/request_response.py` — answer status and public evidence response fields.
- `backend/app/main.py` — conversation router registration and shared public projection.

### New or modified frontend files

- `frontend/src/api.js` — conversation API functions.
- `frontend/src/App.jsx` — conversation route selection and legacy-compatible navigation.
- `frontend/src/components/ConversationWorkspace.jsx` — history loading, turn submission, and page composition.
- `frontend/src/components/ConversationHistory.jsx` — persisted user/assistant turns.
- `frontend/src/components/ConversationMessage.jsx` — statuses, claims, citations, gaps, and errors.
- `frontend/src/components/ResearchComposer.jsx` — chat composer and administrator controls.
- `frontend/src/components/ConversationList.jsx` — create/select persisted conversations.
- `frontend/src/components/EvidenceWorkspace.jsx` — shell, toggle, resize, mobile drawer, and paper tabs.
- `frontend/src/components/EvidenceOverview.jsx` — turn-aware source and gap summary.
- `frontend/src/components/EvidencePaperTab.jsx` — one paper view with span focus.
- `frontend/src/hooks/useEvidenceWorkspace.js` — tab identity and focus behavior.
- `frontend/src/components/SynthesisPanel.jsx`, `RankedPapers.jsx`, `PaperDrawer.jsx`, `TopBar.jsx` — migrate reusable presentation and remove the modal-only path.
- `frontend/src/editorial.css` — desktop split panel and mobile drawer behavior.
- `frontend/package.json` — conversation UI test script.

### New or modified tests and docs

- `tests/unit/test_conversation_models.py`
- `tests/unit/test_conversation_storage.py`
- `tests/unit/test_conversation_agent.py`
- `tests/unit/test_query_understanding.py`
- `tests/unit/test_evidence_verification.py`
- `tests/unit/test_research_pipeline.py`
- `tests/unit/test_conversation_service.py`
- `tests/unit/test_conversation_routes.py`
- `tests/unit/test_query_audits.py`
- `tests/adversarial/test_conversational_research_guardrails.py`
- `scripts/evaluate_conversational_research.py`
- `tests/unit/test_conversational_research_evaluation.py`
- `frontend/tests/ui-conversations.mjs`
- `README.md`, `.env.example`, and `TEST_READY.md`

---

### Task 1: Define strict conversation contracts and bounded settings

**Files:**

- Create: `backend/app/conversation/__init__.py`
- Create: `backend/app/conversation/models.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/models/request_response.py:86`
- Test: `tests/unit/test_conversation_models.py`

Define these public types once and import them everywhere else:

```python
class AgentAction(str, Enum):
    RESEARCH = "RESEARCH"
    CLARIFY = "CLARIFY"
    ANSWER_FROM_EVIDENCE = "ANSWER_FROM_EVIDENCE"
    ABSTAIN = "ABSTAIN"

class AnswerStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"

class ConversationAgentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: AgentAction
    standalone_query: str | None = Field(default=None, max_length=4000)
    complexity_hint: Literal["SIMPLE", "MODERATE", "COMPLEX"] | None = None
    referenced_turn_ids: list[str] = Field(default_factory=list, max_length=20)
    decision_summary: str = Field(max_length=500)
    message: str | None = Field(default=None, max_length=1000)
```

Also define `ConversationTurnContext`, `ConversationHistoryWindow`, `EvidenceGapContext`, `CorrectiveResearchProposal`, `ConversationCreateResponse`, `ConversationSummary`, `ConversationTurnRequest`, `ConversationTurnRecord`, `ConversationDetailResponse`, and `ConversationTurnResponse`. `ConversationHistoryWindow` contains a bounded application-generated `older_context_summary` plus recent turns. `ConversationTurnResponse` carries `answer_status`, `assistant_message`, `cited_pmids`, public `evidence_table`, public `retrieved_papers`, `evidence_gaps`, `consensus_level`, a coarse `progress_summary`, and `request_id`. Add `answer_status: AnswerStatus = AnswerStatus.SUPPORTED` to `ResearchResponse` for backward compatibility.

Validation rules:

- `RESEARCH` requires a nonblank standalone query and complexity hint.
- `CLARIFY` and `ABSTAIN` require a nonblank user-facing message and reject a standalone query.
- `ANSWER_FROM_EVIDENCE` requires at least one referenced turn ID and a standalone question to resynthesize.
- Trim all user/model strings; reject blank, oversized, unknown, or extra fields.
- `ConversationTurnRequest.message` is 1–4000 characters. Advanced year/study-type/loop controls remain optional and are accepted only by the service for administrators.

- [ ] **Step 1: Write the failing contract tests.**

Add tests for all four valid actions, every cross-field rejection, extra-field rejection, message bounds, enum serialization, and the backward-compatible `ResearchResponse` default.

- [ ] **Step 2: Run the focused tests and confirm the expected failure.**

Run: `python -m pytest tests/unit/test_conversation_models.py -q`

Expected: FAIL because `backend.app.conversation.models` and the new response field do not exist.

- [ ] **Step 3: Implement only the contracts and settings.**

Add settings with conservative defaults: `conversation_history_turn_limit=12`, `conversation_message_max_chars=4000`, `conversation_title_max_chars=80`, `conversation_turn_timeout_seconds=120`, and `agent_output_max_tokens=800`. Reuse the existing NIM endpoint/model/key settings; do not add a second secret path.

- [ ] **Step 4: Run focused and compatibility tests.**

Run: `python -m pytest tests/unit/test_conversation_models.py tests/unit/test_research_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the task without unrelated files.**

```powershell
git add backend/app/conversation/__init__.py backend/app/conversation/models.py backend/app/core/config.py backend/app/models/request_response.py tests/unit/test_conversation_models.py
git commit -m "feat: define conversation research contracts"
```

### Task 2: Persist owned conversations and link audit runs atomically

**Files:**

- Modify: `backend/app/storage/database.py:32`
- Modify: `backend/app/storage/audits.py:14`
- Create: `backend/app/storage/conversations.py`
- Test: `tests/unit/test_conversation_storage.py`
- Test: `tests/unit/test_app_storage.py`
- Test: `tests/unit/test_query_audits.py`

Add migration version 2 without returning early when version 1 already exists. Create:

- `conversations(id, account_id, title, created_at, updated_at)` with account/update indexes.
- `conversation_turns(id, conversation_id, ordinal, user_message, assistant_message, agent_action, standalone_query, complexity_hint, final_route, answer_status, status, audit_run_id, public_response_json, created_at, completed_at)`.
- A unique `(conversation_id, ordinal)` index.
- A partial unique index allowing only one `status = 'running'` row per conversation.
- Nullable `conversation_id` and `turn_id` columns plus indexes on `query_runs`.

Implement:

```python
class ConversationBusyError(RuntimeError): ...

class ConversationStore:
    def create(self, account_id: str, title: str = "New research") -> dict: ...
    def update_title(self, conversation_id: str, account_id: str, title: str) -> dict | None: ...
    def list_for_account(self, account_id: str, *, limit: int = 50, offset: int = 0) -> dict: ...
    def detail_for_account(self, conversation_id: str, account_id: str, *, limit: int = 100, offset: int = 0) -> dict | None: ...
    def begin_turn(self, conversation_id: str, account_id: str, user_message: str, *, turn_id: str | None = None) -> dict: ...
    def complete_turn(self, turn_id: str, *, agent_action: str, standalone_query: str | None, complexity_hint: str | None, final_route: str | None, answer_status: str, assistant_message: str, audit_run_id: str, public_response: dict) -> dict: ...
    def fail_turn(self, turn_id: str, *, assistant_message: str, audit_run_id: str | None = None) -> dict: ...
```

Change `AuditStore.start(...)` to accept keyword-only `conversation_id: str | None = None` and `turn_id: str | None = None`. Convert its insert to named columns so future migrations cannot reorder data accidentally.

- [ ] **Step 1: Write migration, ownership, pagination, lifecycle, and concurrency tests.**

Cover fresh database creation, upgrading a version-1 fixture, same-account access, cross-account `None`, title bounds/update, stable `updated_at DESC` pagination, sequential ordinals, completion, failure recovery, and a second `begin_turn` raising `ConversationBusyError` without a second row. Verify deactivating an account preserves its conversation and audit rows.

- [ ] **Step 2: Write the failing audit-link test.**

Assert `AuditStore.detail(run_id)` returns `conversation_id` and `turn_id`, while old callers still work with both values absent.

- [ ] **Step 3: Run storage tests and confirm failure.**

Run: `python -m pytest tests/unit/test_conversation_storage.py tests/unit/test_app_storage.py tests/unit/test_query_audits.py -q`

Expected: FAIL because migration 2, `ConversationStore`, and audit link columns do not exist.

- [ ] **Step 4: Implement migration and storage transactions.**

Use `BEGIN IMMEDIATE` around ordinal allocation and insertion. Translate the partial-index `sqlite3.IntegrityError` to `ConversationBusyError`. Cap list limits server-side, serialize public response JSON deterministically, and never return another account's row.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/unit/test_conversation_storage.py tests/unit/test_app_storage.py tests/unit/test_query_audits.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the task without unrelated files.**

```powershell
git add backend/app/storage/database.py backend/app/storage/audits.py backend/app/storage/conversations.py tests/unit/test_conversation_storage.py tests/unit/test_app_storage.py tests/unit/test_query_audits.py
git commit -m "feat: persist conversations and audit links"
```

### Task 3: Build the schema-constrained conversation agent

**Files:**

- Create: `backend/app/conversation/agent.py`
- Test: `tests/unit/test_conversation_agent.py`

Implement a synchronous, injectable agent so unit tests never call the network:

```python
class ConversationAgent:
    def __init__(self, settings: Settings, *, completion_client: Callable[..., object] | None = None): ...
    def plan_turn(self, message: str, history: ConversationHistoryWindow) -> ConversationAgentDecision: ...
    def review_evidence_gap(self, context: EvidenceGapContext) -> CorrectiveResearchProposal | None: ...
```

Use the existing OpenAI-compatible NIM client shape and structured JSON output. The planning prompt receives only the bounded recent conversation, compact statuses, and validated source identifiers. The gap prompt receives the standalone question, deterministic grade, missing concepts/subquestions, conflicts, prior normalized queries, and route floor. Abstract text, conversation text, and titles are delimited as untrusted data. Neither prompt asks for hidden reasoning.

On timeout, client error, invalid JSON, extra keys, invalid action combination, or oversized content:

- `plan_turn` returns a safe deterministic `RESEARCH` decision using the trimmed current message only when that message is independently actionable. It uses no lower than a `MODERATE` hint for comparison/mechanism cues and otherwise `SIMPLE`. If the message is deictic or depends on failed conversational resolution, it returns one focused `CLARIFY` question rather than guessing.
- `review_evidence_gap` returns `None`, allowing the workflow's deterministic corrective fallback or abstention.

- [ ] **Step 1: Write failing tests with a fake completion client.**

Cover follow-up rewriting, valid clarification, referenced-evidence action, prompt-injection text treated as data, bounded recent history plus older application summary, malformed JSON, extra keys, timeout, client error, safe standalone fallback, unsafe deictic fallback to clarification, and gap-review proposals that try to alter filters/budgets.

- [ ] **Step 2: Run the focused tests and confirm failure.**

Run: `python -m pytest tests/unit/test_conversation_agent.py -q`

Expected: FAIL because `ConversationAgent` does not exist.

- [ ] **Step 3: Implement prompt construction, strict parsing, and safe fallbacks.**

Keep raw provider output out of returned objects and logs. Allow only the fields defined by the Pydantic contracts. Normalize referenced turn IDs against the supplied history before accepting `ANSWER_FROM_EVIDENCE`.

- [ ] **Step 4: Run the focused tests.**

Run: `python -m pytest tests/unit/test_conversation_agent.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the task.**

```powershell
git add backend/app/conversation/agent.py tests/unit/test_conversation_agent.py
git commit -m "feat: add guarded conversation planner"
```

### Task 4: Keep the query enhancer and give the router final authority

**Files:**

- Modify: `backend/app/query/models.py:118`
- Modify: `backend/app/query/query_service.py:151`
- Modify: `backend/app/query/router.py:50`
- Modify: `backend/app/workflow/service.py:189`
- Test: `tests/unit/test_query_understanding.py`
- Test: `tests/unit/test_research_pipeline.py`

Add an `EnhancedQuery` model containing raw query, agent rewrite, canonical query, concepts, must-have concepts, optional expansions, filters, intent, and transformation notes. Extend `QueryPlan` with nullable `agent_complexity_hint`, `rule_route`, `route_floor`, and `route_source` fields while preserving existing defaults and serialization.

Refactor without breaking old callers:

```python
class QueryAnalysisService:
    def enhance_query(self, raw_query: str, *, agent_rewrite: str | None = None, explicit_filters: QueryFilters | None = None) -> EnhancedQuery: ...
    def build_query_plan(self, raw_query: str, *, agent_rewrite: str | None = None, agent_complexity_hint: str | None = None, route_floor: str | None = None, explicit_filters: QueryFilters | None = None) -> QueryPlan: ...

class AdaptiveComplexityRouter:
    def arbitrate(self, rule_decision: RoutingDecision, *, agent_hint: str | None = None, route_floor: str | None = None) -> RoutingDecision: ...
```

Route rank is `SIMPLE < MODERATE < COMPLEX`. `arbitrate` takes the highest rank, retains rule confidence/signals, and records why the route changed. Invalid hints are ignored. `ResearchService._build_plan(...)` accepts and forwards the advisory hint and floor.

- [ ] **Step 1: Add failing enhancer-boundary tests.**

Assert agent rewrites are preserved separately, must-have concepts and explicit filters survive enhancement, and both initial and corrective queries call `enhance_query` before routing.

- [ ] **Step 2: Add failing arbitration tests.**

Assert a `SIMPLE` hint cannot lower a rule `COMPLEX`, a `COMPLEX` hint can raise a rule `SIMPLE`, a prior `COMPLEX` floor cannot be lowered, invalid hints fall back, and the legacy no-hint result is unchanged.

- [ ] **Step 3: Run focused tests and confirm failure.**

Run: `python -m pytest tests/unit/test_query_understanding.py tests/unit/test_research_pipeline.py -q`

Expected: FAIL because enhancement and arbitration are not separate interfaces.

- [ ] **Step 4: Implement the refactor with compatibility defaults.**

Do not change route budgets or retrieval channels here. Keep all existing `build_query_plan(query, filters...)` calls valid.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/unit/test_query_understanding.py tests/unit/test_research_pipeline.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the task.**

```powershell
git add backend/app/query/models.py backend/app/query/query_service.py backend/app/query/router.py backend/app/workflow/service.py tests/unit/test_query_understanding.py tests/unit/test_research_pipeline.py
git commit -m "refactor: arbitrate agent hints through guarded router"
```

### Task 5: Add conservative evidence judgment and independent semantic verification

**Files:**

- Modify: `backend/app/workflow/judge.py:19`
- Create: `backend/app/workflow/verification.py`
- Modify: `backend/app/workflow/synthesis.py:151`
- Modify: `backend/app/models/request_response.py:69`
- Test: `tests/unit/test_evidence_verification.py`
- Test: `tests/unit/test_synthesis_grounding.py`

Extend `EvidenceGrade` compatibly with defaulted `supported_concepts`, `missing_subquestions`, `conflicts`, and `judge_mode`. Parse the optional judge LLM through a strict, extra-forbidden schema. Merge its grade with deterministic signals using the weaker grade only. The LLM may add gaps/conflicts but may not erase deterministic ones or promote `INSUFFICIENT`/`PARTIAL` to `SUFFICIENT`.

Implement:

```python
class ClaimVerification(BaseModel):
    claim_index: int
    supported: bool
    supporting_pmids: list[str]
    rationale: str = Field(max_length=300)

class SemanticClaimVerifier:
    def verify(self, synthesis: str, records: Sequence[EvidenceRecord]) -> list[ClaimVerification]: ...
```

The verifier receives each proposed claim plus only the exact spans already accepted by `ClaimToSpanValidator`. It cannot introduce text, PMIDs, or claims. On invalid output, timeout, missing claim indexes, or unknown PMIDs, mark affected claims unsupported. In synthesis release order: exact PMID/span/numeric/direction checks, semantic verification, one bounded repair using only verified spans, repeat both checks, then prune or abstain.

- [ ] **Step 1: Write failing judge merge tests.**

Cover deterministic `PARTIAL` plus LLM `SUFFICIENT`, LLM-added conflict, invalid schema, unknown grade, timeout, and prompt injection embedded in an abstract.

- [ ] **Step 2: Write failing semantic verifier tests.**

Cover entailment, related-but-not-supporting evidence, numeric mismatch, directional contradiction, unknown PMID, incomplete verdict list, timeout, successful one-time repair, failed repair pruning, and zero validated claims producing `INSUFFICIENT`.

- [ ] **Step 3: Run focused tests and confirm failure.**

Run: `python -m pytest tests/unit/test_evidence_verification.py tests/unit/test_synthesis_grounding.py -q`

Expected: FAIL because the richer grade and semantic verifier do not exist.

- [ ] **Step 4: Implement conservative merge and verifier.**

Use dependency injection for the completion client. Store only verdicts and bounded rationales in trace events. Never store hidden reasoning or raw completion content.

- [ ] **Step 5: Integrate the verifier into synthesis release.**

Keep deterministic validation mandatory even when the verifier is disabled by configuration. If no semantic client is configured, fail closed for newly generated prose and continue to allow the existing extractive, exact-span fallback.

- [ ] **Step 6: Run focused and existing grounding tests.**

Run: `python -m pytest tests/unit/test_evidence_verification.py tests/unit/test_synthesis_grounding.py tests/unit/test_research_pipeline.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the task.**

```powershell
git add backend/app/workflow/judge.py backend/app/workflow/verification.py backend/app/workflow/synthesis.py backend/app/models/request_response.py tests/unit/test_evidence_verification.py tests/unit/test_synthesis_grounding.py
git commit -m "feat: verify biomedical claims before release"
```

### Task 6: Route structured evidence gaps back through the agent, enhancer, and router

**Files:**

- Modify: `backend/app/workflow/service.py:340`
- Modify: `backend/app/workflow/service.py:359`
- Modify: `backend/app/models/request_response.py:86`
- Test: `tests/unit/test_research_pipeline.py`

Extend the compatible research interface:

```python
def research(
    self,
    query: str,
    *,
    agent_rewrite: str | None = None,
    agent_complexity_hint: str | None = None,
    route_floor: str | None = None,
    gap_reviewer: Callable[[EvidenceGapContext], CorrectiveResearchProposal | None] | None = None,
    event_sink: Callable[[str, dict], None] | None = None,
    ...existing_args,
) -> ResearchResponse: ...

def answer_from_evidence(
    self,
    query: str,
    *,
    candidates: Sequence[RetrievalCandidate],
    evidence: Sequence[EvidenceRecord],
    event_sink: Callable[[str, dict], None] | None = None,
) -> ResearchResponse: ...
```

At each non-sufficient judge result, construct `EvidenceGapContext` from structured gaps/conflicts and used normalized queries. Ask `gap_reviewer` once for the next proposal. If accepted, send its query through `enhance_query` and router arbitration with the current route as a floor. Otherwise use the existing deterministic corrective query. Every pass preserves the initial standalone question, protected concepts, explicit filters, and minimum route. Stop on sufficient evidence, exhausted server budget, repeated normalized query, no safe proposal, retrieval failure, or unresolved conflict.

Map final release state:

- `SUPPORTED`: sufficient evidence and every released claim passes both validators.
- `LIMITED`: only independently verified claims are released; the response states that the full question was not established and exposes missing parts, limitations, and conflicts.
- `INSUFFICIENT`: no safe claim survives, or conflict prevents a conclusion; return an abstention plus sources/gaps.
- `FAILED`: technical failure; do not describe it as lack of evidence.

- [ ] **Step 1: Add failing graph-sequence tests.**

Assert the call order `agent proposal -> enhancer -> router -> retrieval -> judge`, route floors across loops, loop/subquery caps, repeated-query termination, and deterministic fallback when gap review fails.

- [ ] **Step 2: Add failing status and release tests.**

Cover sufficient support, partially supported multi-part question, zero surviving claims, unresolved contradiction, provider failure, and `answer_from_evidence` performing no retrieval while revalidating every claim.

- [ ] **Step 3: Run focused tests and confirm failure.**

Run: `python -m pytest tests/unit/test_research_pipeline.py tests/unit/test_synthesis_grounding.py -q`

Expected: FAIL because agent gap review and explicit answer statuses are not wired into the graph.

- [ ] **Step 4: Implement the bounded loop and event summaries.**

Emit bounded events for `agent_decision`, `query_enhanced`, `route_arbitrated`, `retrieval_attempt`, `evidence_judged`, `correction_stopped`, `claim_verified`, and `answer_released`. Event payloads must contain identifiers, route/status, counts, gaps, and short summaries only.

- [ ] **Step 5: Run focused tests.**

Run: `python -m pytest tests/unit/test_research_pipeline.py tests/unit/test_synthesis_grounding.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the task.**

```powershell
git add backend/app/workflow/service.py backend/app/models/request_response.py tests/unit/test_research_pipeline.py
git commit -m "feat: add agent-guided corrective research loop"
```

### Task 7: Orchestrate conversation turns and expose owned APIs

**Files:**

- Create: `backend/app/conversation/service.py`
- Create: `backend/app/conversation/routes.py`
- Modify: `backend/app/main.py:70`
- Modify: `backend/app/main.py:276`
- Test: `tests/unit/test_conversation_service.py`
- Test: `tests/unit/test_conversation_routes.py`
- Test: `tests/unit/test_admin_boundary.py`

Implement:

```python
class ConversationService:
    def create(self, account: dict) -> ConversationCreateResponse: ...
    def list(self, account: dict, *, limit: int, offset: int) -> dict: ...
    def detail(self, conversation_id: str, account: dict, *, limit: int, offset: int) -> ConversationDetailResponse | None: ...
    def run_turn(self, conversation_id: str, account: dict, request: ConversationTurnRequest) -> ConversationTurnResponse: ...
```

`run_turn` owns the invariant-sensitive sequence:

1. Verify conversation ownership and administrator-only controls.
2. Allocate the turn ID and insert the single running turn.
3. Start one linked audit run before invoking the agent.
4. Load bounded recent history and summarize older turns using only user intent, prior standalone questions, answer statuses, cited PMIDs, and validated evidence identifiers.
5. Execute `CLARIFY`, `ABSTAIN`, guarded `ANSWER_FROM_EVIDENCE`, or `RESEARCH`.
6. Project a public response and finish the audit.
7. Complete the persisted turn with the public response.
8. On an exception, finish the audit as failed when possible, persist a technical failure message, and return/raise the correct HTTP error without converting it to `INSUFFICIENT`.

Add authenticated routes:

```text
POST /conversations
GET  /conversations?limit=&offset=
GET  /conversations/{conversation_id}?limit=&offset=
POST /conversations/{conversation_id}/turns
```

Return `404` for a missing or foreign conversation, `409` for a running turn, `422` for invalid content/ordinary-user advanced controls, and existing auth errors unchanged. Apply the existing session and CSRF protections to every mutating route. Register the router in `main.py`. Do not add the dynamic turn route to the old generic request-audit middleware; the conversation service creates the correctly linked audit itself.

Extract `_public_research_response` into a reusable projection that includes exact evidence rows and safe paper metadata but strips raw scores, prompts, internal trace, model output, and admin-only fields. Preserve existing `/research` public behavior unless a compatibility test intentionally updates its evidence contract.

- [ ] **Step 1: Write failing service tests.**

Cover all four agent actions, linked audit-before-agent ordering, title initialization from the first bounded message, recent-history limits, deterministic older-context summary bounds/content, public response persistence, terminal-audit-before-success ordering, turn failure, and fail-closed audit failure recovery.

- [ ] **Step 2: Write failing route/auth tests.**

Cover create/list/detail/turn, pagination bounds, missing/expired/deactivated session, CSRF rejection on both POST routes, foreign ownership, ordinary/admin controls, concurrent `409`, and sanitized public fields.

- [ ] **Step 3: Run focused tests and confirm failure.**

Run: `python -m pytest tests/unit/test_conversation_service.py tests/unit/test_conversation_routes.py tests/unit/test_admin_boundary.py -q`

Expected: FAIL because service and routes do not exist.

- [ ] **Step 4: Implement orchestration and APIs.**

Construct dependencies in one factory so tests can inject fake agent/research/audit/store instances. Use FastAPI's threadpool for synchronous research work. Never hold a SQLite transaction open during an LLM or retrieval call.

- [ ] **Step 5: Run focused and legacy API tests.**

Run: `python -m pytest tests/unit/test_conversation_service.py tests/unit/test_conversation_routes.py tests/unit/test_admin_boundary.py tests/unit/test_query_audits.py tests/unit/test_research_pipeline.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the task.**

```powershell
git add backend/app/conversation/service.py backend/app/conversation/routes.py backend/app/main.py tests/unit/test_conversation_service.py tests/unit/test_conversation_routes.py tests/unit/test_admin_boundary.py
git commit -m "feat: expose persistent research conversations"
```

### Task 8: Replace the one-shot page with a persistent conversation workspace

**Files:**

- Modify: `frontend/src/api.js:57`
- Modify: `frontend/src/App.jsx:55`
- Create: `frontend/src/components/ConversationWorkspace.jsx`
- Create: `frontend/src/components/ConversationHistory.jsx`
- Create: `frontend/src/components/ConversationMessage.jsx`
- Create: `frontend/src/components/ResearchComposer.jsx`
- Create: `frontend/src/components/ConversationList.jsx`
- Modify: `frontend/src/components/SynthesisPanel.jsx`
- Modify: `frontend/src/components/RankedPapers.jsx`
- Modify: `frontend/src/editorial.css`
- Test: `frontend/tests/ui-conversations.mjs`

Add API functions:

```javascript
export function createConversation()
export function listConversations({ limit = 50, offset = 0 } = {})
export function getConversation(conversationId, { limit = 100, offset = 0 } = {})
export function submitConversationTurn(conversationId, payload)
```

Use `/research/:conversationId` and `/admin/research/:conversationId` as restorable routes. `/research` and `/admin/research` show the conversation list plus an empty composer; the first submitted message creates a conversation and navigates to its URL before posting the turn.

`ConversationWorkspace` owns loading, submitting, cancellation-safe state updates, and the active conversation. It appends the user's message immediately, shows one running assistant placeholder with coarse non-streaming progress, disables double submission, then replaces the placeholder with the stored response. On reload, it reconstructs every message and evidence link from `GET /conversations/{id}`. A `FAILED` turn is visibly technical; `INSUFFICIENT` is visibly evidentiary. Clarifications remain normal assistant messages. Keep the research-use disclaimer and prompt users to inspect the original papers.

- [ ] **Step 1: Add a mocked Playwright test for conversation persistence.**

Cover new conversation creation, URL navigation, optimistic user message, coarse progress without draft claims, disabled duplicate submit, supported/limited/insufficient/failed badges, clarification, switching conversations, reload restoration, expired-session handling, research disclaimer, and keyboard submit (`Enter`) versus newline (`Shift+Enter`).

- [ ] **Step 2: Add the package script and run the test to confirm failure.**

Add `"test:ui-conversations": "node tests/ui-conversations.mjs"`.

Run from `frontend`: `npm run test:ui-conversations`

Expected: FAIL because the conversation UI and API functions do not exist.

- [ ] **Step 3: Implement API and conversation components.**

Keep administrator controls in `ResearchComposer` only when `isAdmin` is true. Reuse rendering helpers from `SynthesisPanel` and `RankedPapers`, but make citation and paper selections callbacks rather than external navigation.

- [ ] **Step 4: Add accessible loading and error behavior.**

Use a labeled composer, live-region status text, real buttons, focus the assistant response after completion without stealing focus while typing, and preserve entered text on retryable network errors.

- [ ] **Step 5: Run the UI test and build.**

Run from `frontend`: `npm run test:ui-conversations`

Run from `frontend`: `npm run build`

Expected: PASS.

- [ ] **Step 6: Commit the task.**

```powershell
git add frontend/src/api.js frontend/src/App.jsx frontend/src/components/ConversationWorkspace.jsx frontend/src/components/ConversationHistory.jsx frontend/src/components/ConversationMessage.jsx frontend/src/components/ResearchComposer.jsx frontend/src/components/ConversationList.jsx frontend/src/components/SynthesisPanel.jsx frontend/src/components/RankedPapers.jsx frontend/src/editorial.css frontend/tests/ui-conversations.mjs frontend/package.json
git commit -m "feat: add persistent research chat workspace"
```

### Task 9: Implement the collapsible one-tab-per-paper evidence workspace

**Files:**

- Create: `frontend/src/hooks/useEvidenceWorkspace.js`
- Create: `frontend/src/components/EvidenceWorkspace.jsx`
- Create: `frontend/src/components/EvidenceOverview.jsx`
- Create: `frontend/src/components/EvidencePaperTab.jsx`
- Modify: `frontend/src/components/ConversationWorkspace.jsx`
- Modify: `frontend/src/components/ConversationMessage.jsx`
- Modify: `frontend/src/components/TopBar.jsx`
- Modify: `frontend/src/components/PaperDrawer.jsx`
- Modify: `frontend/src/editorial.css`
- Test: `frontend/tests/ui-conversations.mjs`

The hook contract is:

```javascript
const {
  isOpen,
  activeTabId,
  tabs,
  openOverview,
  openPaper,
  closePaper,
  activateTab,
  toggle,
  panelWidth,
  setPanelWidth,
} = useEvidenceWorkspace(conversationId)
```

`tabs` always begins with fixed `overview`. A paper tab ID is `pmid:${normalizedPmid}`. `openPaper({ paper, turnId, evidenceId, spanText })` upserts by PMID, updates its current focus target, activates it, and opens the panel. Closing the active paper selects the nearest remaining tab; Overview cannot be closed. Collapsing preserves tabs and focus state. Keep a session-memory state map keyed by conversation ID so switching away and back restores that conversation's tabs; a newly created conversation receives a fresh Overview-only state. Browser-restart persistence remains out of scope.

Desktop behavior:

- Initially collapsed.
- Top-bar Evidence toggle exposes `aria-expanded` and the current source count.
- Citation, evidence-row, and ranked-paper clicks all call `openPaper`.
- Right panel is full height, keyboard reachable, and resizable within `360px` and `min(50vw, 760px)`. Provide keyboard increment/decrement controls as an alternative to pointer dragging.
- A tab shows title, citation metadata, authors, journal/year/study type, relevant MeSH terms, complete stored abstract, every supporting span used in the conversation, provenance links, and turn references; the selected span is highlighted and scrolled into view. The canonical PubMed link opens a new browser tab with safe `target`/`rel` attributes.

Mobile behavior:

- At `<= 768px`, render a full-height modal drawer with backdrop, close button, focus trap, `Escape` close, and focus restoration.
- Keep the same tab strip and one-PMID identity.
- Do not render nested horizontal page scrolling at 320px.
- Honor reduced-motion preferences and surface empty, session-expired, and paper-detail-error states without discarding open tabs.

Migrate reusable content from `PaperDrawer`; remove the old modal invocation after parity is covered. Because `PaperDrawer.jsx` currently has user changes, inspect its diff and preserve any metadata/provenance logic while retiring only the modal shell.

- [ ] **Step 1: Extend the mocked UI test with tab identity cases.**

Click two spans from the same PMID in different turns and assert one tab exists while the highlight changes. Then open another PMID, switch tabs, close it, collapse/reopen, switch conversations, and verify the documented state transitions.

- [ ] **Step 2: Add responsive and accessibility cases.**

At 1440px verify pointer and keyboard resize bounds; at 768px, 390px, and 320px verify drawer layout, keyboard tab navigation, focus trap, `Escape`, focus restoration, reduced-motion behavior, paper-detail error recovery, and no horizontal overflow.

- [ ] **Step 3: Run the UI test and confirm failure.**

Run from `frontend`: `npm run test:ui-conversations`

Expected: FAIL because the evidence workspace and tab-state hook do not exist.

- [ ] **Step 4: Implement hook, components, and trigger wiring.**

Use stable IDs for tab/panel ARIA relationships. Keep source hyperlinks available inside the paper tab; citation clicks in chat should open the internal evidence tab first.

- [ ] **Step 5: Run conversation, preview, and build checks.**

Run from `frontend`: `npm run test:ui-conversations`

Run from `frontend`: `npm run test:ui-preview`

Run from `frontend`: `npm run build`

Expected: PASS.

- [ ] **Step 6: Commit the task.**

```powershell
git add frontend/src/hooks/useEvidenceWorkspace.js frontend/src/components/EvidenceWorkspace.jsx frontend/src/components/EvidenceOverview.jsx frontend/src/components/EvidencePaperTab.jsx frontend/src/components/ConversationWorkspace.jsx frontend/src/components/ConversationMessage.jsx frontend/src/components/TopBar.jsx frontend/src/components/PaperDrawer.jsx frontend/src/editorial.css frontend/tests/ui-conversations.mjs
git commit -m "feat: add tabbed evidence workspace"
```

### Task 10: Expose complete linked traces only in administrator audits

**Files:**

- Modify: `backend/app/storage/audits.py:14`
- Modify: `backend/app/admin/routes.py`
- Modify: `frontend/src/components/AuditData.jsx`
- Modify: `frontend/src/App.jsx`
- Test: `tests/unit/test_query_audits.py`
- Test: `tests/unit/test_admin_boundary.py`
- Test: `frontend/tests/ui-accounts.mjs`

Extend audit list/detail projections with `conversation_id`, `turn_id`, `agent_action`, `agent_complexity_hint`, `rule_route`, `final_route`, `answer_status`, correction count, bounded evidence gaps, and stage durations. Preserve the ordered event stream added in Task 6. Derive detailed fields from the stored allowlisted events/result rather than duplicating query plans into conversation rows. Add admin filters for conversation ID, final route, and answer status only if the existing list API already supports safe indexed query filtering; otherwise show them in list/detail without adding an unindexed free-form filter.

The administrator UI should link from a conversation/turn to its audit detail and show a compact phase timeline:

```text
Agent decision -> Query enhanced -> Route arbitrated -> Retrieval/Judge loop -> Claim verification -> Release
```

Ordinary conversation endpoints must continue to omit this timeline, internal scores, raw model output, and prompt data.

- [ ] **Step 1: Write failing audit projection and boundary tests.**

Assert linked IDs and bounded fields appear for an administrator, event order is stable, prompt/raw output keys are absent even for administrators, and ordinary responses cannot obtain the audit detail or internal metadata.

- [ ] **Step 2: Extend the mocked administrator UI test.**

Assert the audit list shows conversation/turn/status and the detail renders the phase timeline and evidence gaps.

- [ ] **Step 3: Run focused tests and confirm failure.**

Run: `python -m pytest tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py -q`

Run from `frontend`: `npm run test:ui-accounts`

Expected: FAIL because conversation trace fields are not projected.

- [ ] **Step 4: Implement safe audit projections and UI.**

Render structured summaries, never hidden reasoning. Use explicit allowlists on both API and UI mappings.

- [ ] **Step 5: Run focused tests and frontend build.**

Run: `python -m pytest tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py -q`

Run from `frontend`: `npm run test:ui-accounts`

Run from `frontend`: `npm run build`

Expected: PASS.

- [ ] **Step 6: Commit the task.**

```powershell
git add backend/app/storage/audits.py backend/app/admin/routes.py frontend/src/components/AuditData.jsx frontend/src/App.jsx tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py frontend/tests/ui-accounts.mjs
git commit -m "feat: show conversation traces in admin audits"
```

### Task 11: Lock down adversarial cases, document behavior, and run full verification

**Files:**

- Create: `tests/adversarial/test_conversational_research_guardrails.py`
- Create: `scripts/evaluate_conversational_research.py`
- Create: `tests/unit/test_conversational_research_evaluation.py`
- Modify: `frontend/tests/ui-conversations.mjs`
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `TEST_READY.md`

Add end-to-end adversarial fixtures for:

- A user message and abstract that attempt to override system/tool instructions.
- A planner that returns a fabricated PMID, extra authorization fields, a lower route, or an unlimited loop count.
- A judge that promotes insufficient evidence.
- A verifier that cites an unknown PMID or omits a claim verdict.
- A partially supported comparison with one safe claim and one unsupported claim.
- Conflicting studies with no resolvable conclusion.
- Repeated corrective queries and exhausted research budget.
- Conversation ownership probing, replayed turn requests, and simultaneous submissions.
- Failure after audit start and failure before research completion.
- Same PMID selected from multiple turns with different spans.

Add a deterministic fixture evaluator that reports route accuracy, correction-loop count, final answer/abstention distribution, unsupported-claim rate, citation validity, claim attribution, latency, and LLM-call count. Its input is a fixture JSON/report object, not the live corpus, and its output must make deterministic checks primary while labeling LLM-as-judge/RAGAS-style signals as optional secondary evidence.

Document the final behavior in plain language:

- Where the query enhancer lives: conversation agent -> enhancer -> guarded router -> research workflow.
- What each answer status means.
- Why a limited answer contains only independently supported claims.
- Which settings bound history, output, time, and loops.
- Conversation and audit retention expectations.
- How to run backend and frontend verification.
- How mock mode differs from configured live NVIDIA NIM planning/semantic grading; mock mode must not be presented as live agent intelligence.
- That the product summarizes biomedical literature and does not provide medical advice.

- [ ] **Step 1: Write adversarial tests before adjusting implementation.**

Run: `python -m pytest tests/adversarial/test_conversational_research_guardrails.py -q`

Expected: At least one new test FAILS, demonstrating the unhandled edge case rather than weakening the assertion.

- [ ] **Step 2: Apply the smallest guardrail fixes required by those failures.**

Touch only the owning modules. Do not add special-case strings to make fixtures pass; enforce schema, ownership, budget, source, and release invariants generally.

- [ ] **Step 3: Add and test the deterministic evaluation report.**

Run: `python -m pytest tests/unit/test_conversational_research_evaluation.py -q`

Expected: PASS and a fixture report containing every required metric with zero unsupported released claims.

- [ ] **Step 4: Run the complete backend suite.**

Run: `python -m pytest -q`

Expected: PASS with no skipped new guardrail tests.

- [ ] **Step 5: Run all deterministic frontend checks.**

Run from `frontend`: `npm run test:ui-conversations`

Run from `frontend`: `npm run test:ui-preview`

Run from `frontend`: `npm run test:ui-accounts`

Run from `frontend`: `npm run build`

Expected: PASS. Do not require live-network or live-model smoke tests for deterministic CI.

- [ ] **Step 6: Run a manual local smoke check with safe fixtures.**

Verify: create conversation, ask initial and follow-up questions, receive a limited/insufficient fixture answer, open citations into unique paper tabs, collapse/reopen evidence, reload the conversation, and inspect the linked administrator audit.

- [ ] **Step 7: Run optional live/index checks only when prerequisites are available.**

Run the existing real-index and UI stress/smoke commands documented in `frontend/tests/README.md` and `TEST_READY.md`. Report them separately from deterministic results; a missing local model/index or live NIM key is not represented as a deterministic test failure.

- [ ] **Step 8: Update documentation and environment examples.**

Do not include real keys or production data. Mark optional live NIM and PubMed tests separately from the deterministic suite.

- [ ] **Step 9: Inspect the final diff and commit only feature files.**

Run: `git status --short`

Run: `git diff --check`

Review every changed path against this plan and the approved spec. Preserve unrelated pre-existing worktree changes.

```powershell
git add tests/adversarial/test_conversational_research_guardrails.py scripts/evaluate_conversational_research.py tests/unit/test_conversational_research_evaluation.py frontend/tests/ui-conversations.mjs README.md .env.example TEST_READY.md
git add <only-the-owning-modules-changed-for-guardrail-fixes>
git commit -m "test: harden conversational research guardrails"
```

## Completion Criteria

- All 11 tasks are checked off and each task has passed spec-compliance and code-quality review.
- Existing one-shot APIs remain compatible, while authenticated conversations persist and reload correctly.
- The enhancer is exercised for every initial and corrective research query.
- Router authority, correction budgets, one-running-turn concurrency, ownership, and public/admin boundaries are proven by tests.
- Every released biomedical claim passes exact citation/span checks and semantic verification, or is pruned/abstained.
- Partial support is visibly `LIMITED`; zero safe support is `INSUFFICIENT`; technical failures are `FAILED`.
- The evidence panel is collapsed by default and implements one tab per PMID across all turns in a conversation.
- Backend suite, deterministic frontend tests, production build, diff check, and manual smoke check pass.
- Deterministic evaluation reports route, loop, grounding, citation, latency, and LLM-call metrics; optional live-provider/index checks are reported separately.
