# Evidence Atlas: conversational research agent and tabbed evidence workspace

Status: approved conversational design captured for written review. This is not an implementation-completion report.

## 1. Agreed outcome

Replace the one-shot research form with a persistent biomedical research conversation. A user can ask an initial question and continue with context-dependent follow-ups. The assistant may interpret the conversation and suggest how complex the research is, but it cannot answer biomedical claims from model memory or directly control retrieval. The existing biomedical query enhancer remains in the path, and the adaptive router retains authority over retrieval depth, channels, correction budgets, and repeated research.

Every factual medical claim shown to a user must be traceable to retrieved PubMed evidence. Weak retrieval triggers bounded corrective research. A partially supported question may produce a clearly limited answer containing only independently validated claims. Insufficient or unresolved conflicting evidence produces an abstention with sources and evidence gaps rather than a medical conclusion.

The main user experience is a chat with an initially collapsed evidence workspace on the right. The workspace opens from a top-bar Evidence toggle or automatically when a citation, evidence item, or ranked paper is selected. It uses browser/IDE-like tabs with one tab per paper. Administrators continue to inspect full execution traces on the separate Audit Logs pages.

The current application remains a biomedical literature research prototype, not a general-purpose research chatbot, clinical decision tool, or medical-advice system.

## 2. Current implementation and relevant gaps

- `frontend/src/App.jsx` renders a one-shot `ResearchPage`; `SearchBar` submits one `/research` request and the page replaces the previous result.
- `SynthesisPanel`, `RankedPapers`, `EvidenceTable`, and `PaperDrawer` already render most required result data, but they are organized as a results page rather than a conversation and evidence workspace.
- `backend/app/query/query_service.py` already performs biomedical normalization, MeSH mapping, filter extraction, PICO/non-PICO extraction, intent classification, concept weighting, canonical-query creation, adaptive routing, and route-specific subquery generation.
- `backend/app/query/router.py` currently uses deterministic routing rules. It has an LLM fallback implementation, but `QueryAnalysisService.analyze()` currently returns the deterministic baseline and the main workflow calls the synchronous builder.
- `ResearchService` already runs a bounded LangGraph flow for query analysis, retrieval, evidence judgment, corrective retrieval, evidence extraction, synthesis, and citation validation.
- `EvidenceSufficiencyJudge` already combines observable retrieval signals with an optional NIM grade and prevents an LLM from promoting weaker deterministic evidence to `SUFFICIENT`.
- `ClaimToSpanValidator` already rejects hallucinated PMIDs, unsupported claims, numeric mismatches, and detectable directional contradictions. Invalid output fails closed.
- SQLite account and audit storage and separate administrator pages are being introduced under the previously approved accounts/admin-audits design. This feature extends that database and audit lifecycle; it does not replace it.
- Ordinary-user `/research` responses currently remove `evidence_table` and diagnostic data. The new evidence workspace requires a deliberately defined public evidence contract while still excluding ranking internals, prompts, and admin traces.

## 3. Architecture choice

Use an advisory conversation agent above the existing query-analysis and research workflow. The agent is responsible for conversational interpretation. The query enhancer and adaptive router remain deterministic application boundaries, and the research workflow remains the only path that may produce biomedical claims.

Alternatives considered:

1. **Advisory agent plus guarded router (selected).** The LLM resolves follow-up context, proposes a standalone research question and complexity hint, and reviews structured evidence gaps. The backend validates its output, enhances the query, selects the final route, and enforces all budgets and answer gates.
2. **Free-form autonomous agent.** The LLM chooses arbitrary tools, loops, and stopping behavior. This is flexible but difficult to bound, test, and audit and creates unacceptable false-positive risk for biomedical answers. Rejected.
3. **Chat-only wrapper around `/research`.** This has the smallest backend change but cannot safely resolve follow-ups or perform targeted evidence-gap correction. Rejected.

The selected design follows the project plan's explicit state-machine preference over unconstrained multi-agent chat. It also follows the plan's final rule: no medical claim or citation is returned unless it is traceable to retrieved evidence.

## 4. Component boundaries

### 4.1 Conversation agent

The conversation agent receives a bounded conversation view: the current user message, recent user/assistant turns, identifiers for any referenced validated evidence, and a compact summary of prior evidence status. It returns one strict structured decision:

- `RESEARCH`: a standalone biomedical question plus an advisory `SIMPLE`, `MODERATE`, or `COMPLEX` hint.
- `CLARIFY`: one focused clarification question when the research intent cannot be preserved safely.
- `ANSWER_FROM_EVIDENCE`: a proposed answer request that may use only already validated evidence linked to the conversation; the output still passes synthesis and validation again.
- `ABSTAIN`: a user-facing explanation that the available evidence cannot support the requested conclusion.

The agent does not receive a general shell, database, network, filesystem, audit, or raw retriever tool. It cannot set filters, route overrides, loop counts, source scores, or authorization fields. Retrieved abstracts and conversation text are untrusted data, never instructions.

The agent output schema contains the action, standalone query when applicable, complexity hint when applicable, referenced turn IDs, a bounded plain-language decision summary for auditing, and a clarification/abstention message when applicable. Extra fields are rejected. Hidden reasoning or chain-of-thought is neither requested nor stored.

### 4.2 Biomedical query enhancer

The query enhancer remains between the agent and router. It owns biomedical normalization and search interpretation:

1. Preserve the current user message and the agent's standalone rewrite separately.
2. Apply cautious spelling/whitespace and acronym normalization.
3. Identify validated MeSH concepts.
4. extract PICO or non-PICO concepts and research intent.
5. Preserve must-have concepts, high-priority concepts, optional expansions, and allowed hard filters.
6. Produce a canonical biomedical query.

The agent cannot silently replace must-have concepts or hard filters. Every transformation is recorded. Free-form LLM synonyms remain optional candidates and cannot become mandatory concepts without validation.

Implementation may refactor `QueryAnalysisService.build_query_plan()` into clearer enhancement and routing phases, but existing callers and `/research` behavior remain compatible.

### 4.3 Guarded adaptive router

The router owns the final execution route. The valid agent hint is advisory. The existing rule-based/classifier result provides a minimum-safe route floor; the final route is the higher-cost of the validated agent hint and that floor. Thus, an agent may request more research but cannot under-route a comparison, mechanism, or other rule-recognized complex question. Missing, malformed, or unavailable agent output falls back to the existing router.

The route has the existing meanings:

- `SIMPLE`: one enhanced hybrid retrieval bundle.
- `MODERATE`: bounded multi-query expansion and merged retrieval.
- `COMPLEX`: explicit subquestions plus iterative evidence-gap correction.

The final route, rule floor, agent hint, arbitration outcome, confidence information, and short decision reason are audited. Route and correction budgets remain server configuration, not model-controlled values.

### 4.4 Research workflow

Only the research workflow can retrieve evidence and produce biomedical synthesis. Its high-level graph becomes:

```text
user turn
  -> conversation agent
  -> query enhancer
  -> guarded router
  -> retrieve / fuse / rerank
  -> evidence judge
       sufficient -> extract / compare / synthesize / validate
       partial or insufficient + budget -> agent gap review
          -> enhancer -> guarded router -> retrieve again
       exhausted partial -> limited synthesis / validate
       exhausted insufficient or unresolved conflict -> abstain with sources
  -> persist turn and audit
```

Every corrective pass retains the initial standalone question, protected concepts, user filters, and minimum route. The agent receives structured missing concepts/subquestions and evidence status, not permission to rewrite the user's objective. Duplicate corrective queries are rejected. Existing configured limits on subqueries, loops, candidates, tokens, and timeouts remain hard bounds.

## 5. Evidence sufficiency and false-positive control

### 5.1 Combined judgment

The evidence judge uses both semantic and observable signals:

- The LLM judge evaluates relevance, subquestion coverage, missing relationships, and unresolved conflict across the evidence set.
- Application code checks candidate existence, metadata-filter compliance, coverage of protected concepts, usable supporting spans, study/source diversity signals, and retrieval/reranker diagnostics.
- `SUFFICIENT` requires the semantic judge and all applicable hard gates to agree. An LLM can downgrade evidence but cannot override an objective failure.
- If the semantic judge is unavailable, invalid, or times out, the system uses the conservative existing deterministic path and records degraded judgment mode.

Retrieval relevance is not treated as claim support. A paper mentioning the right entities does not by itself authorize an answer. Thresholds that depend on model scores must be configuration backed by evaluation; MedCPT logits are not presented as calibrated probabilities.

### 5.2 `PARTIAL`

`PARTIAL` identifies the supported and missing parts of the question. While budget remains, the workflow returns the structured gaps to the conversation agent for a targeted corrective-query proposal. That proposal passes through the enhancer and router before retrieval.

When the budget is exhausted, the system may return a `LIMITED` response only if at least one material claim passes every citation and claim-support gate. The response must:

- state that the full question could not be answered from the available corpus;
- include only validated claims with adjacent PMID citations;
- expose the unresolved evidence gaps and any conflict;
- avoid extrapolating from model memory; and
- retain the inspected papers in the evidence workspace.

If no material claim survives validation, `PARTIAL` collapses to abstention.

### 5.3 `INSUFFICIENT` or conflicting evidence

After the correction budget is exhausted, `INSUFFICIENT` produces no biomedical conclusion. The assistant explains that the indexed evidence could not establish the answer, lists the evidence gaps, and makes the inspected sources available. Unresolved contradiction is displayed explicitly and cannot be averaged into a false consensus.

## 6. Synthesis and final release gate

The synthesizer receives only validated `EvidenceRecord` data and permitted metadata, not unrestricted model memory or unrelated conversation text. Every factual sentence requires one or more adjacent PMIDs.

Before release:

1. Parse every cited PMID and require it to belong to the final evidence pack.
2. Map every factual claim to an exact supporting abstract span for the cited PMID.
3. Reject unsupported numbers and detectable direction/negation conflicts.
4. Run a separate bounded semantic claim-evidence verification pass that can flag unsupported, contradicted, or overstated claims.
5. Permit at most one evidence-constrained repair of affected content.
6. Re-run all deterministic checks after repair.
7. Remove any claim that still fails. If no useful claim remains, abstain.

The semantic verifier never invents replacement facts or citations and cannot promote a deterministically invalid claim. The response exposes one of `SUPPORTED`, `LIMITED`, `INSUFFICIENT`, or `FAILED`; a service failure is never mislabeled as lack of evidence.

## 7. Conversation persistence and ownership

Extend the application SQLite database with versioned migrations. Do not mix conversation records into Qdrant or corpus artifacts.

| Table/change | Key data |
|---|---|
| `conversations` | Stable ID, owner account ID, bounded generated/display title, created/updated timestamps |
| `conversation_turns` | Stable ID, conversation ID, sequence, user message, agent action, standalone query, agent hint, final route, answer status, assistant message, linked audit run ID, timestamps |
| `query_runs` extension | Nullable conversation and turn IDs for runs invoked through chat |

Detailed query plans, retrieval iterations, evidence packs, judgments, validation results, and provider metadata remain in the durable audit event/result records rather than being duplicated into the conversational transcript.

Conversation ownership is enforced on the server. A user can list and open only their own conversations. Administrators use the audit interface for cross-account inspection; ordinary conversation endpoints do not become an admin surveillance UI. Account deactivation preserves historical ownership and audits.

Conversation history supplied to an LLM is bounded by message count and size. Older context is represented only by an application-generated summary of user intent and identifiers for validated evidence; raw hidden reasoning is never reconstructed. Messages and research questions may be sensitive and follow the existing audit-data warnings and local filesystem protections.

One research turn per conversation may execute at a time. A second submission to that conversation receives a clear conflict response rather than racing the first turn or corrupting ordering. Retrieval across conversations continues to respect the service's existing model/search serialization.

## 8. API contract

Preserve `/research` as the backwards-compatible one-shot research endpoint. Add authenticated, CSRF-protected conversation routes:

- `POST /conversations`: create an empty conversation and return its metadata.
- `GET /conversations`: list the current account's conversations using bounded pagination, newest activity first.
- `GET /conversations/{conversation_id}`: return owned conversation metadata and paginated turns.
- `POST /conversations/{conversation_id}/turns`: synchronously execute one conversational turn.

The turn request contains only the message for ordinary users. Admin-only research controls remain server-authorized and are not smuggled through agent output. The turn response contains:

- conversation and turn IDs;
- linked audit request ID;
- agent action and public answer status;
- assistant message;
- cited PMIDs;
- public ranked-paper fields;
- public evidence records, including exact supporting abstract spans;
- evidence gaps/conflict status; and
- a coarse research-progress summary suitable for the UI.

It excludes prompts, model reasoning, router internals, retrieval scores, provider exceptions, credentials, and full audit traces. Administrators receive a separate audit-detail link rather than hidden diagnostic fields in the public payload.

Normal request/response execution is selected for the first version. Token streaming is out of scope because retrieval is already a long, serialized operation and correctness requires validating the complete synthesis before any medical claim is shown. The UI may show stage-level progress labels based on safe server events or local state, but it must not stream an unvalidated draft.

`GET /paper/{pmid}` remains authenticated and supplies the complete stored abstract and metadata needed by a paper tab. It does not expose retrieval scores to ordinary users.

## 9. User interface

### 9.1 Conversation workspace

The research page becomes a conversation timeline with a persistent composer. Each turn distinguishes the user message, research state, assistant response, status (`Supported`, `Limited evidence`, `Insufficient evidence`, or technical failure), citations, and evidence-opening controls.

A compact conversation-history control opens a list/drawer of the user's conversations. It does not add a permanent third column. Starting a new conversation clears the timeline and evidence-tab state. Reloading an existing conversation restores its persisted messages and evidence links.

The existing admin navigation remains separate. Admin research uses the same conversational surface with authorized advanced controls and a `View full trace` link on completed research turns.

### 9.2 Collapsible evidence workspace

Evidence is not a permanently visible column. On desktop, it is an initially collapsed, right-side workspace. The main chat occupies the available width while evidence is closed.

The workspace opens when:

- the user selects the top-bar `Evidence` toggle (with available-evidence count);
- the user selects an inline PMID citation;
- the user selects a supporting-evidence control; or
- the user selects a ranked paper.

The top-bar toggle opens the last active evidence tab, or `Overview` if no paper tab is active. Collapsing the workspace preserves its open tabs and active selection for the current conversation. A draggable separator resizes the desktop workspace within accessible minimum and maximum widths.

The workspace contains a browser/IDE-style tab strip:

- `Overview` is a fixed tab containing ranked papers, cross-study evidence, evidence gaps, conflicts, and status explanations for the selected research turn.
- Each opened paper has exactly one tab, keyed by PMID and labeled with a short title or PMID.
- Selecting the same PMID again focuses its existing tab; it never creates a duplicate.
- Selecting another claim supported by the same paper focuses that tab and scrolls to/highlights the associated exact span.
- Paper tabs can be closed individually. Closing the active tab selects the nearest remaining tab or `Overview`.
- Collapsing the workspace does not close tabs. Changing conversations maintains separate in-memory tab state per conversation during the session.

A paper tab shows title, PMID, authors, year, journal, study type, relevant MeSH terms, evidence-record fields, all supporting spans used in the conversation, and the complete stored abstract with selected spans highlighted. A clearly labeled external link opens the canonical PubMed page in a new browser tab using safe link attributes.

This is an internal web application panel inspired by side-by-side artifact/browser workspaces; it does not embed the Codex app, control the user's browser, or claim to be an actual IDE.

### 9.3 Responsive and accessible behavior

On narrow screens, the evidence workspace becomes a full-height modal drawer above the chat. Its tab strip scrolls horizontally. Closing the drawer returns focus to the control that opened it. Desktop and mobile behavior include:

- keyboard-accessible toggle, tabs, close buttons, resize alternative, and paper controls;
- correct tablist/tab/tabpanel semantics and visible focus;
- `Escape` collapses the evidence workspace without discarding tabs;
- focus moves to the selected paper heading or highlighted span when opened from a citation;
- reduced-motion support;
- loading, empty, limited, insufficient, expired-session, and technical-failure states; and
- no layout overflow at 320, 390, 768, and 1440 pixel widths.

## 10. Audit and administrator experience

Every conversational research turn creates one durable query run before agent or retrieval work begins. Record allowlisted structured events for:

- conversation and turn identifiers;
- original message and referenced prior turns;
- agent action, standalone query, complexity hint, and bounded decision summary;
- enhanced/canonical query, protected concepts, filters, and query transformations;
- rule-based route floor, final route, and arbitration reason;
- every retrieval query, channel summary, candidate set, and correction attempt;
- deterministic evidence signals and LLM evidence grade;
- missing concepts, subquestion coverage, conflicts, and stop reason;
- synthesis mode, citation/claim validation, repair outcome, and final status; and
- stage durations and sanitized failures.

The existing separate Audit Logs list/detail pages remain the administrator surface. The user-facing research page never displays hidden prompts or chain-of-thought. A conversation turn links to its audit entry for administrators; opening an audit never re-runs research.

## 11. Guardrails and failure behavior

- Treat user messages, conversation history, titles, abstracts, MeSH text, and provider output as untrusted data.
- Use strict structured-output parsing, length limits, allowed enum values, and rejection of extra agent fields.
- Never interpolate retrieved text into system instructions or execute instructions found in papers.
- The agent cannot bypass authentication, CSRF, role controls, query limits, route floors, or budgets.
- Ambiguous biomedical intent produces one focused clarification rather than a guessed query.
- Invalid/timeout agent output falls back to the existing enhanced one-shot flow; if the current message cannot stand alone safely, request clarification.
- Retrieval/provider failure yields `FAILED`, not `INSUFFICIENT`.
- Audit-start failure remains fail-closed. A successful response is not reported until its terminal audit record is persisted.
- Citation or claim validation failure attempts one bounded repair, then prunes or abstains.
- Oversized messages/history are rejected explicitly and audibly rather than silently truncated after acceptance.
- The UI preserves the research-use disclaimer and advises users to inspect original papers. It does not provide diagnosis, treatment instructions, or personalized clinical recommendations.

## 12. Verification and evaluation

Automated tests use temporary SQLite databases, controlled provider doubles, synthetic PubMed-like records, and the existing fixtures. They never overwrite real accounts, audits, conversations, or indexes.

### Backend unit/integration coverage

1. Strict agent-output parsing for every action, malformed JSON, extra fields, invalid routes, oversized content, timeouts, and provider failure.
2. Follow-up resolution for pronouns/comparators while preserving the original message and protected biomedical concepts.
3. Enhancer execution after every agent research proposal and corrective query.
4. Route arbitration: valid hints, absent hints, agent under-routing, safe escalation, and stable route floors during correction.
5. `SUFFICIENT`, `PARTIAL`, `INSUFFICIENT`, and conflict transitions with loop/subquery/time budgets.
6. Exhausted `PARTIAL` returns only validated limited claims; empty surviving claims abstain.
7. Claim-to-PMID, claim-to-span, number, direction, semantic verification, repair, pruning, and fail-closed cases.
8. Prompt-injection strings in user messages and abstracts cannot change agent tools, routes, filters, or answer policy.
9. Conversation ownership, pagination, sequence ordering, concurrent-turn rejection, account deactivation, CSRF, and admin audit access.
10. `/research` compatibility and ordinary-user evidence-contract redaction.

### Frontend coverage

1. Create/open conversations, reload persisted turns, submit follow-ups, and render all answer statuses.
2. Evidence toggle opens/collapses the right workspace and restores the active tab.
3. One-tab-per-PMID deduplication, close behavior, turn-specific Overview content, and per-conversation in-memory tab state.
4. Citation selection opens/focuses the correct paper tab and highlights the exact supporting span.
5. Ranked-paper and evidence-row selection use the same tab-opening path.
6. Desktop resizing and mobile drawer behavior, keyboard tab navigation, focus restoration, and responsive overflow checks.
7. Ordinary users never receive or render traces/scores; administrators retain audit links and authorized controls.
8. Empty, loading, partial, insufficient, technical-error, session-expired, and paper-detail-error states.

### Robustness and evaluation

Extend the existing adversarial suite with MedRGB-inspired irrelevant, incomplete, conflicting, and counterfactual evidence fixtures. Measure router accuracy, correction-loop count, answer/abstention behavior, unsupported-claim rate, citation validity, claim attribution, latency, and LLM-call count. Keep deterministic claim checks and targeted human review as primary safety evidence; LLM-as-judge and RAGAS remain secondary evaluation signals.

Run the complete relevant Python suite, frontend production build, UI smoke/stress tests, and a real-index smoke test when local model/index prerequisites are available. Report live-provider tests separately from deterministic/mock tests.

## 13. Compatibility, migration, and rollout

- Apply additive SQLite migrations; preserve existing accounts and query audits.
- Existing one-shot `/research`, `/search`, `/analyze-query`, paper, admin, and health endpoints remain available with their role boundaries.
- Existing saved audits remain readable without conversation IDs.
- Do not rebuild or modify the PubMed corpus, embeddings, BM25 index, MeSH graph, or Qdrant collection for this feature.
- Reuse focused existing components where practical, but split the current monolithic `App.jsx`/research flow into conversation, message, and evidence-workspace components rather than adding more conditional markup to one file.
- Introduce the conversation endpoint and storage behind tests before making it the default research UI.
- Document that live conversational planning and semantic grading require configured NVIDIA NIM mode. Mock mode supports deterministic development/testing and must not be presented as live agent intelligence.

## 14. Out of scope

General web research, non-biomedical corpora, full-text article ingestion, clinical recommendations, streaming unvalidated model tokens, voice input, file uploads, collaborative conversations, shared/public conversation links, paper annotations, persisted evidence-tab layout across browser restarts, arbitrary agent tools, multi-agent delegation, and replacing the existing retriever/vector store.

## 15. Acceptance criteria

The feature is complete when:

1. An authenticated user can create a conversation, ask a biomedical research question, and submit a context-dependent follow-up.
2. The agent produces a validated standalone question and advisory complexity while the enhancer and router remain mandatory and auditable.
3. Partial/insufficient evidence returns through a bounded agent-router correction loop and stops at configured limits.
4. No user-visible biomedical claim survives without valid PMID and exact-span support; invalid output repairs, prunes, or abstains.
5. Conversation turns survive restart and remain account-isolated.
6. Evidence is collapsed by default, opens from the top toggle or evidence selections, and uses one deduplicated tab per paper plus an Overview tab.
7. Clicking a citation focuses the correct paper tab and supporting span; desktop, mobile, keyboard, and screen-reader flows are verified.
8. Administrators can inspect every agent, enhancement, routing, retrieval, judgment, correction, and validation event on the separate audit pages.
9. Existing one-shot APIs, authentication boundaries, corpus assets, and relevant regression tests continue to work.
10. Documentation explains configuration, limitations, answer statuses, audit behavior, and the difference between mock and live agent modes.

## 16. Research foundations

- Adaptive-RAG separates query-complexity prediction from the selected retrieval strategy: <https://aclanthology.org/2024.naacl-long.389/>
- Corrective RAG evaluates retrieved evidence before selecting corrective actions: <https://arxiv.org/abs/2401.15884>
- PaperQA2 demonstrates iterative scientific-literature search and evidence gathering with citations: <https://arxiv.org/abs/2409.13740>
- MedRGB evaluates medical RAG under incomplete, irrelevant, and adversarial evidence: <https://arxiv.org/abs/2411.09213>
- Sufficient Context shows that capable models often answer rather than abstain when context is insufficient: <https://arxiv.org/abs/2411.06037>
- NIST's Generative AI Profile recommends layered measurement, provenance, testing, and risk management: <https://doi.org/10.6028/NIST.AI.600-1>
- Official OpenAI documentation describes previewing files alongside chat, surfacing sources in a chat sidebar, and opening a shared built-in browser from links or a toolbar. The evidence workspace adapts these interaction ideas; it is not an embedded Codex component: <https://learn.chatgpt.com/docs/artifacts-viewer> and <https://learn.chatgpt.com/docs/browser>

## Review handoff

This document captures the approved conversational-agent, guarded-router, evidence-safety, persistence, audit, and one-tab-per-paper workspace design. Review this written specification before the detailed implementation plan is produced. After approval, the implementation plan will sequence storage and contracts, agent/query boundaries, guarded evidence loops, API integration, the conversational UI, the tabbed evidence workspace, audits, and verification without rebuilding the corpus.
