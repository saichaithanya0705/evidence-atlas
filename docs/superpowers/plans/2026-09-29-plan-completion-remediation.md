# Plan Completion Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the original capstone plan's missing research-planning, provenance, validation, evaluation, administrator UI, and documentation work while leaving the active corpus unchanged.

**Architecture:** Extend the existing LangGraph research service with a strict dependency-aware research plan and coverage map, then drive corrective retrieval from uncovered subquestions. Preserve retrieval metadata through evidence extraction, add bounded claim-level repair, and evaluate four comparable retrieval variants against a source-linked 30–50-query benchmark. Persist immutable reports and expose them through administrator-only API and React surfaces; ordinary users receive only sanitized interpretation, evidence, and qualitative provenance.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, LangGraph, Qdrant, MedCPT, BM25, NetworkX, RAGAS 0.4.x, pytest, React 18, Vite, Playwright, NCBI E-utilities.

**Spec:** `docs/superpowers/specs/2026-09-29-plan-completion-remediation-design.md`

## Global Constraints

- Do not rebuild, resize, or mutate the active PubMed corpus, embeddings, BM25 index, MeSH graph, Qdrant collection, or manifests.
- Preserve every existing authentication, ownership, conversation, audit, retrieval, citation, and fail-closed boundary.
- Every model-created initial or corrective query must pass through the existing enhancer and router; agent output cannot lower route floors or raise budgets.
- Every released biomedical claim must retain a retrieved PMID and exact source span.
- Benchmark judgments must reference PMIDs in the active corpus and primary PubMed/publication URLs; call them web-assisted adjudication, not independent human review.
- Evaluation reports and metrics are administrator-only. Ordinary users may see sanitized query interpretation, exact evidence, qualitative channel names, and subquestion coverage but never aggregate metrics, numeric ranking scores, raw traces, prompts, or model output.
- Optional evaluation failures must be represented as `not_run` or `failed` with a reason, never as zero or success.
- Use the RAGAS 0.4 collections API; do not introduce legacy `ragas.metrics` or deprecated `evaluate()` usage.
- Preserve user-owned work and commit only files named by the current task.

## Review Focus

1. **Cyclic or malformed complex plans:** duplicate/missing dependency IDs, cycles, oversized plans, and empty nodes must fail validation or use a bounded deterministic fallback. Covered by Tasks 1 and 2.
2. **Correction drift:** a missing subquestion must create a targeted, enhanced query without repeating a prior query, lowering route authority, or exceeding the loop budget. Covered by Task 2.
3. **Grounding regression during repair:** supported claims must remain unchanged; repaired claims must use only existing validated spans and fail closed after one retry. Covered by Task 4.
4. **Evaluation leakage:** all report endpoints and frontend routes must reject ordinary users, and public research projections must omit metrics and raw scores. Covered by Tasks 3, 5, and 9.
5. **Dishonest evaluation state:** network/provider/dependency failures, partial reports, or unverified PMIDs must not be promoted as a completed benchmark result. Covered by Tasks 6–8.

---

### Task 1: Define and generate dependency-aware research plans

**Files:**

- Create: `backend/app/models/research_plan.py`
- Create: `backend/app/workflow/planning.py`
- Modify: `backend/app/workflow/__init__.py`
- Test: `tests/unit/test_research_planning.py`

**Interfaces:**

- Consumes: `backend.app.query.models.QueryPlan`.
- Produces: `ResearchSubquestion`, `ResearchPlan`, `SubquestionCoverage`, `CoverageStatus`, and `ResearchPlanner.build(query_plan: QueryPlan, *, max_subqueries: int) -> ResearchPlan`.
- `ResearchPlan.ready_subquestions(coverage: dict[str, SubquestionCoverage]) -> list[ResearchSubquestion]` returns uncovered/partial nodes whose dependencies are covered, in stable plan order.

- [ ] **Step 1: Write failing model and planner tests.**

Cover one-node SIMPLE/MODERATE plans, comparison/mechanism/contradiction COMPLEX DAGs, stable IDs/order, maximum node count, duplicate IDs, unknown dependencies, cycles, blank questions, and ready-node dependency ordering.

- [ ] **Step 2: Run the focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_planning.py -q`

Expected: FAIL because the research-plan models and planner do not exist.

- [ ] **Step 3: Implement the strict models and deterministic planner.**

Use `ConfigDict(extra="forbid")`; allow 1–8 subquestions; normalize stable IDs as `sq-1` through `sq-8`; validate the graph with an explicit topological walk. COMPLEX comparisons create independent evidence-arm nodes followed by a dependent comparison node. Non-complex routes create one root node.

- [ ] **Step 4: Run focused and query compatibility tests.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_planning.py tests/unit/test_query_understanding.py -q`

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add backend/app/models/research_plan.py backend/app/workflow/planning.py backend/app/workflow/__init__.py tests/unit/test_research_planning.py
git commit -m "feat: add dependency-aware research plans"
```

### Task 2: Drive LangGraph retrieval from subquestion coverage

**Files:**

- Modify: `backend/app/workflow/judge.py`
- Modify: `backend/app/workflow/service.py`
- Modify: `backend/app/models/research_plan.py`
- Test: `tests/unit/test_research_planning.py`
- Test: `tests/unit/test_research_pipeline.py`
- Test: `tests/adversarial/test_conversational_research_guardrails.py`

**Interfaces:**

- Consumes: `ResearchPlanner.build(...)`, `ResearchPlan.ready_subquestions(...)` from Task 1.
- Produces: `EvidenceGrade.subquestion_coverage: list[SubquestionCoverage]`, workflow trace fields `research_plan`, `coverage_history`, and targeted `corrective_queries[].subquestion_id`.
- Adds `ResearchService._corrective_query(plan, grade, used, research_plan, coverage) -> tuple[str, str] | None`, returning `(subquestion_id, query)`.

- [ ] **Step 1: Write failing coverage and correction tests.**

Assert that complex comparison arms run before their dependent comparison node; judge coverage records supporting PMIDs; missing-subquestion text is preferred over generic concept broadening; blocked nodes are reported; duplicate corrections stop; route floors and budgets still hold; SIMPLE behavior remains one-pass compatible.

- [ ] **Step 2: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_planning.py tests/unit/test_research_pipeline.py -q`

Expected: FAIL because workflow state has no plan/coverage fields and deterministic correction ignores missing subquestions.

- [ ] **Step 3: Extend grading and workflow state.**

Create the research plan after initial query analysis, compute deterministic per-node coverage from required concepts and candidate text, merge any conservative LLM downgrade, and store only bounded reasons and PMID lists.

- [ ] **Step 4: Implement dependency-ordered initial and corrective retrieval.**

Generate each active query from the original question plus the selected subquestion; re-enter `_build_plan`; preserve the original route floor; track normalized duplicates; and fall back to generic broadening only when no actionable plan node remains.

- [ ] **Step 5: Run focused and adversarial tests.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_planning.py tests/unit/test_research_pipeline.py tests/adversarial/test_conversational_research_guardrails.py -q`

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add backend/app/workflow/judge.py backend/app/workflow/service.py backend/app/models/research_plan.py tests/unit/test_research_planning.py tests/unit/test_research_pipeline.py tests/adversarial/test_conversational_research_guardrails.py
git commit -m "feat: target retrieval by subquestion coverage"
```

### Task 3: Preserve retrieval provenance in EvidenceRecord

**Files:**

- Modify: `backend/app/models/request_response.py`
- Modify: `backend/app/evidence/extraction.py`
- Modify: `backend/app/conversation/models.py`
- Modify: `backend/app/conversation/service.py`
- Modify: `backend/app/storage/audits.py`
- Test: `tests/unit/test_research_pipeline.py`
- Test: `tests/unit/test_conversation_models.py`
- Test: `tests/unit/test_conversation_service.py`
- Test: `tests/unit/test_admin_boundary.py`
- Test: `tests/unit/test_query_audits.py`

**Interfaces:**

- Produces `RetrievalProvenance(channel_ranks, channel_scores, graph_path, rrf_score, filter_satisfied, retrieval_iteration)` and new `EvidenceRecord` fields `retrieval_provenance`, `reranker_score`, `reranker_mode`, and `subquestion_ids`.
- Public evidence projection produces `retrieval_channels` and `subquestion_ids`, while omitting numerical scores, ranks, graph internals, reranker values, and iteration IDs.

- [ ] **Step 1: Write failing extraction and projection tests.**

Assert exact candidate metadata is copied into administrator evidence, merged candidates retain all channel provenance, public conversation/research responses expose only channel names plus subquestion IDs, and audit allowlists retain typed scalar score data without nested injection.

- [ ] **Step 2: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_pipeline.py tests/unit/test_conversation_models.py tests/unit/test_conversation_service.py tests/unit/test_admin_boundary.py tests/unit/test_query_audits.py -q`

Expected: FAIL because `EvidenceRecord` drops ranking provenance.

- [ ] **Step 3: Implement strict provenance copying and projections.**

Derive channel names from candidate keys, never from generated text. Preserve optional values as `None`; do not fabricate unavailable scores.

- [ ] **Step 4: Run focused tests.**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add backend/app/models/request_response.py backend/app/evidence/extraction.py backend/app/conversation/models.py backend/app/conversation/service.py backend/app/storage/audits.py tests/unit/test_research_pipeline.py tests/unit/test_conversation_models.py tests/unit/test_conversation_service.py tests/unit/test_admin_boundary.py tests/unit/test_query_audits.py
git commit -m "feat: carry retrieval provenance into evidence"
```

### Task 4: Add targeted claim repair and revalidation

**Files:**

- Create: `backend/app/workflow/repair.py`
- Modify: `backend/app/workflow/synthesis.py`
- Modify: `backend/app/workflow/verification.py`
- Modify: `backend/app/workflow/service.py`
- Test: `tests/unit/test_synthesis_grounding.py`
- Test: `tests/unit/test_evidence_verification.py`
- Test: `tests/unit/test_research_pipeline.py`

**Interfaces:**

- Produces `TargetedClaimRepairer.repair(text: str, records: Sequence[EvidenceRecord], audit: CitationAudit, verdicts: Sequence[ClaimVerification]) -> ClaimRepairResult`.
- `ClaimRepairResult` contains `text`, `preserved_claims`, `repaired_claims`, `pruned_claims`, and `attempt_count`; `attempt_count` is at most 1.
- EvidenceSynthesizer runs deterministic and semantic validation again on the combined output before release.

- [ ] **Step 1: Write failing repair tests.**

Cover preservation of supported text, replacement of one unsupported claim from an exact cited span, no new PMID, invalid semantic repair pruning, bounded one-attempt behavior, all-claims-failed abstention, and mixed supported/failed ordering.

- [ ] **Step 2: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_synthesis_grounding.py tests/unit/test_evidence_verification.py -q`

Expected: FAIL because current fallback regenerates the whole deterministic response.

- [ ] **Step 3: Implement the repairer and integrate both research paths.**

Build replacements only from exact spans already accepted by the validator. Preserve section metadata separately from factual claims. Record repair counts and pruned claim counts in synthesis metadata and audit events without storing prompts or raw verifier output.

- [ ] **Step 4: Run synthesis and pipeline tests.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_synthesis_grounding.py tests/unit/test_evidence_verification.py tests/unit/test_research_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add backend/app/workflow/repair.py backend/app/workflow/synthesis.py backend/app/workflow/verification.py backend/app/workflow/service.py tests/unit/test_synthesis_grounding.py tests/unit/test_evidence_verification.py tests/unit/test_research_pipeline.py
git commit -m "feat: repair unsupported claims before pruning"
```

### Task 5: Correct API contracts and add safe interpretation payloads

**Files:**

- Modify: `backend/app/models/request_response.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/conversation/models.py`
- Modify: `backend/app/conversation/service.py`
- Test: `tests/unit/test_admin_boundary.py`
- Test: `tests/unit/test_conversation_models.py`
- Test: `tests/unit/test_conversation_service.py`
- Test: `tests/e2e/e2e_contracts.py`

**Interfaces:**

- `POST /analyze-query` serializes `AnalyzeQueryResponse(query_plan=plan)` and declares `response_model=AnalyzeQueryResponse`.
- Public research/conversation responses add `interpretation` with canonical question, PICO/MeSH concepts, route label, sanitized subquestions, and coverage statuses; it contains no confidence, reasoning, scores, metrics, or unrestricted trace fields.

- [ ] **Step 1: Write failing API and projection tests.**

Assert the exact `{query_plan: ...}` wrapper, OpenAPI response schema, public safe interpretation allowlist, administrator full plan availability, and absence of `metrics`, `scores`, `router_confidence`, and `router_reasoning` from ordinary responses.

- [ ] **Step 2: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_admin_boundary.py tests/unit/test_conversation_models.py tests/unit/test_conversation_service.py tests/e2e/e2e_contracts.py -q`

Expected: FAIL because `/analyze-query` returns the plan directly and public responses lack the new interpretation contract.

- [ ] **Step 3: Implement the typed wrapper and shared safe projection.**

Use one projection function for legacy `/research` and conversation persistence/reload so fields cannot drift.

- [ ] **Step 4: Run focused tests.**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add backend/app/models/request_response.py backend/app/main.py backend/app/conversation/models.py backend/app/conversation/service.py tests/unit/test_admin_boundary.py tests/unit/test_conversation_models.py tests/unit/test_conversation_service.py tests/e2e/e2e_contracts.py
git commit -m "fix: align analysis and interpretation contracts"
```

### Task 6: Build and web-adjudicate the frozen 30–50-query benchmark

**Files:**

- Create: `evaluation/models.py`
- Create: `evaluation/benchmark.py`
- Create: `evaluation/adjudication.py`
- Create: `data/evaluation/benchmark_v2.json`
- Create: `data/evaluation/benchmark_v2_validation.json`
- Modify: `.env.example`
- Test: `tests/unit/test_evaluation_benchmark.py`

**Interfaces:**

- Produces `BenchmarkEntry`, `RelevanceJudgment`, `BenchmarkDataset`, `load_benchmark(path)`, and `validate_benchmark(dataset, corpus_pmids) -> BenchmarkValidationReport`.
- Produces CLI `python -m evaluation.adjudication --benchmark ... --corpus ... --output ...` using NCBI EFetch in batches of at most 100 PMIDs, at most 3 requests/second without `NCBI_API_KEY`, at most 10 with it, bounded retries, and a local response cache under ignored `data/temporary/`.

- [ ] **Step 1: Write failing schema and validation tests.**

Cover 30–50 entry count, unique IDs, category/route coverage, graded relevance, active-corpus PMID membership, source URL requirements, reference-field consistency, checksum stability, rate-limit selection, cached responses, title mismatch, missing PubMed record, and partial network failure.

- [ ] **Step 2: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_evaluation_benchmark.py -q`

Expected: FAIL because the benchmark package and v2 dataset do not exist.

- [ ] **Step 3: Implement schemas, loader, NCBI client, and validation CLI.**

Do not read or log the API key. Use `tool=EvidenceAtlas` and a configurable contact email only when supplied. Write validation atomically and include corpus checksum, benchmark checksum, fetched timestamp, and per-label status.

- [ ] **Step 4: Construct 40 representative queries from the active corpus.**

Use local metadata to find candidate topics, then use web search and PubMed/primary publication pages to verify relevance. Record the source URL, direct PMID/title match, relevance grade, rationale, and adjudication date for every label. Do not include a query with no verified relevant PMID.

- [ ] **Step 5: Run benchmark validation.**

Run: `\.venv\Scripts\python.exe -m evaluation.adjudication --benchmark data/evaluation/benchmark_v2.json --corpus data/processed/cleaned_pubmed.parquet --output data/evaluation/benchmark_v2_validation.json`

Expected: PASS with `query_count` between 30 and 50, zero corpus-ID mismatches, and zero unverified relevance labels.

- [ ] **Step 6: Run focused tests.**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 7: Commit.**

```powershell
git add evaluation/models.py evaluation/benchmark.py evaluation/adjudication.py data/evaluation/benchmark_v2.json data/evaluation/benchmark_v2_validation.json .env.example tests/unit/test_evaluation_benchmark.py
git commit -m "feat: add source-linked biomedical benchmark"
```

### Task 7: Implement comparable retrieval variants and ablation artifacts

**Files:**

- Create: `evaluation/variants.py`
- Create: `evaluation/ablation.py`
- Modify: `backend/app/retrieval/hybrid.py`
- Modify: `backend/app/workflow/service.py`
- Test: `tests/unit/test_evaluation_variants.py`
- Test: `tests/unit/test_research_pipeline.py`

**Interfaces:**

- Produces `EvaluationVariant` protocol with `run(entry: BenchmarkEntry) -> QueryEvaluationArtifact`.
- Produces `DenseOnlyVariant`, `HybridVariant`, `RerankedVariant`, and `AgenticVariant` using the same filters, top-k, corpus, and version metadata.
- `HybridRetriever.search_channels(plan, *, channels, top_k)` allows evaluation to disable graph/reranking without duplicating retrieval logic.

- [ ] **Step 1: Write failing variant tests.**

Assert dense-only uses only the original MedCPT query plus hard filters; hybrid omits cross-encoder output; reranked consumes the identical hybrid candidate pool; agentic emits plan/coverage/answer artifacts; and all variants share the same artifact schema and deterministic configuration hash.

- [ ] **Step 2: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_evaluation_variants.py tests/unit/test_research_pipeline.py -q`

Expected: FAIL because no variant interface or channel-controlled search exists.

- [ ] **Step 3: Implement the variant adapters and ablation runner.**

Reuse production retrievers and filters. Do not substitute BM25 for dense-only. Support `--variant`, `--query-id`, `--resume`, and `--output-dir`; each query artifact is written atomically so interrupted runs can resume without changing completed results.

- [ ] **Step 4: Run focused tests.**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 5: Commit.**

```powershell
git add evaluation/variants.py evaluation/ablation.py backend/app/retrieval/hybrid.py backend/app/workflow/service.py tests/unit/test_evaluation_variants.py tests/unit/test_research_pipeline.py
git commit -m "feat: add retrieval ablation variants"
```

### Task 8: Add comprehensive metrics, diagnostics, robustness, and reports

**Files:**

- Create: `requirements-evaluation.txt`
- Create: `evaluation/metrics.py`
- Create: `evaluation/ragas_metrics.py`
- Create: `evaluation/diagnostics.py`
- Create: `evaluation/robustness.py`
- Create: `evaluation/reporting.py`
- Modify: `evaluation/run_evaluation.py`
- Create: `evaluation/reports/.gitkeep`
- Test: `tests/unit/test_evaluation_metrics.py`
- Test: `tests/unit/test_evaluation_reporting.py`
- Test: `tests/unit/test_evaluation_robustness.py`

**Interfaces:**

- Pin `ragas==0.4.3` in `requirements-evaluation.txt`.
- Produces pure functions for IR, routing, filters, coverage, citation, attribution, grounded-claim, latency, and failure-category metrics.
- Produces `RagasEvaluator` using `ragas.metrics.collections` scorers and explicit provider adapters; no deprecated global `evaluate()` call.
- Produces robustness scenarios `irrelevant_context`, `conflicting_evidence`, `incomplete_evidence`, `misleading_context`, `noisy_query`, `acronym_query`, and `filter_pressure`.
- Produces immutable `evaluation/reports/<run_id>/report.json`, `report.md`, per-query artifacts, and atomically updated `evaluation/reports/manifest.json` only after a complete run.

- [ ] **Step 1: Write failing deterministic metric tests.**

Use hand-derived rankings and claims to pin Recall/Precision/MRR/nDCG, route confusion, filter accuracy, coverage, citation/span/attribution precision, supported-claim rate, completeness, and latency summaries.

- [ ] **Step 2: Write failing RAGAS adapter and failure-state tests.**

Assert required sample fields for each scorer, collections API imports, provider errors isolated per metric, `not_run` when references or credentials are absent, and no zero substitution.

- [ ] **Step 3: Write failing diagnostics, robustness, and report-promotion tests.**

Cover each failure category, perturbation provenance, metric deltas, interrupted runs, checksum mismatch, atomic manifest update, and Markdown/JSON agreement.

- [ ] **Step 4: Run focused tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_evaluation_metrics.py tests/unit/test_evaluation_reporting.py tests/unit/test_evaluation_robustness.py -q`

Expected: FAIL because the modules do not exist.

- [ ] **Step 5: Implement metrics and reporting.**

Keep deterministic metrics dependency-free. Lazy-import RAGAS so the core application and deterministic evaluation still run without optional packages.

- [ ] **Step 6: Install and smoke-test the optional evaluation environment.**

Run: `\.venv\Scripts\python.exe -m pip install -r requirements-evaluation.txt`

Run: `\.venv\Scripts\python.exe -c "from ragas.metrics.collections import Faithfulness, ContextPrecision, ContextRecall, ContextEntityRecall, AnswerRelevancy, AnswerCorrectness; print('ragas collections ok')"`

Expected: `ragas collections ok`.

- [ ] **Step 7: Run focused tests.**

Run the Step 4 command.

Expected: PASS.

- [ ] **Step 8: Commit.**

```powershell
git add requirements-evaluation.txt evaluation/metrics.py evaluation/ragas_metrics.py evaluation/diagnostics.py evaluation/robustness.py evaluation/reporting.py evaluation/run_evaluation.py evaluation/reports/.gitkeep tests/unit/test_evaluation_metrics.py tests/unit/test_evaluation_reporting.py tests/unit/test_evaluation_robustness.py
git commit -m "feat: add comprehensive research evaluation"
```

### Task 9: Add administrator-only evaluation API and dashboard

**Files:**

- Create: `backend/app/evaluation/__init__.py`
- Create: `backend/app/evaluation/service.py`
- Modify: `backend/app/admin/routes.py`
- Modify: `backend/app/core/config.py`
- Modify: `frontend/src/api.js`
- Create: `frontend/src/components/EvaluationDashboard.jsx`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/editorial.css`
- Create: `frontend/tests/ui-evaluation.mjs`
- Modify: `frontend/package.json`
- Test: `tests/unit/test_admin_boundary.py`
- Test: `tests/unit/test_evaluation_reporting.py`

**Interfaces:**

- `GET /admin/evaluations` lists completed allowlisted reports.
- `GET /admin/evaluations/{run_id}` returns one report after validating `run_id` as a basename and resolving it inside `EVALUATION_REPORTS_DIR`.
- Frontend `getEvaluations()` and `getEvaluation(runId)` are called only from administrator routes.

- [ ] **Step 1: Write failing API authorization and path-safety tests.**

Cover anonymous `401`, ordinary-user `403`, administrator success, absent report `404`, partial-report exclusion, path traversal rejection, malformed report fail-closed behavior, and response allowlists.

- [ ] **Step 2: Run focused backend tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_admin_boundary.py tests/unit/test_evaluation_reporting.py -q`

Expected: FAIL because evaluation routes/service do not exist.

- [ ] **Step 3: Implement report service and administrator routes.**

Read report files only; evaluation execution remains a CLI operation and is never triggered by a GET request.

- [ ] **Step 4: Add the dashboard and Playwright access fixture.**

Render benchmark/version metadata, ablation table, metric groups, per-query failures, robustness deltas, and explicit `not_run` reasons. Add the nav item only for administrators; assert ordinary sessions neither render the route nor request its API.

- [ ] **Step 5: Run backend, UI, and build checks.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_admin_boundary.py tests/unit/test_evaluation_reporting.py -q`

Run: `npm run test:ui-evaluation` from `frontend/`

Run: `npm run build` from `frontend/`

Expected: PASS; production build exits 0.

- [ ] **Step 6: Commit.**

```powershell
git add backend/app/evaluation/__init__.py backend/app/evaluation/service.py backend/app/admin/routes.py backend/app/core/config.py frontend/src/api.js frontend/src/components/EvaluationDashboard.jsx frontend/src/App.jsx frontend/src/editorial.css frontend/tests/ui-evaluation.mjs frontend/package.json tests/unit/test_admin_boundary.py tests/unit/test_evaluation_reporting.py
git commit -m "feat: add admin evaluation dashboard"
```

### Task 10: Integrate safe interpretation and reusable evidence views

**Files:**

- Modify: `frontend/src/components/InterpretationPanel.jsx`
- Modify: `frontend/src/components/EvidenceTable.jsx`
- Modify: `frontend/src/components/ConversationMessage.jsx`
- Modify: `frontend/src/components/ConversationWorkspace.jsx`
- Modify: `frontend/src/components/AuditTrail.jsx`
- Modify: `frontend/src/editorial.css`
- Modify: `frontend/tests/ui-conversations.mjs`
- Modify: `frontend/tests/ui-accounts.mjs`

**Interfaces:**

- `InterpretationPanel` accepts sanitized public interpretation and an `isAdmin` flag; numeric confidence/reasoning render only from administrator trace data.
- `EvidenceTable` accepts public evidence rows, qualitative channel names, coverage, and existing evidence-workspace callbacks.
- `AuditTrail` is mounted only for administrators and loads trace data only after explicit expansion.

- [ ] **Step 1: Extend UI fixtures with interpretation, coverage, and provenance.**

Assert ordinary users see canonical interpretation, planned subquestions, coverage, exact spans, and qualitative channels; they do not see raw scores, evaluation metrics, trace controls, or audit requests. Assert administrators can expand the audit trail.

- [ ] **Step 2: Run the UI test and confirm RED.**

Run: `npm run test:ui-conversations` from `frontend/`

Expected: FAIL because the components are not mounted in the conversation workflow.

- [ ] **Step 3: Integrate the components using stable callbacks and existing evidence-tab identity.**

Do not create inline component definitions or duplicate fetches. Preserve one tab per PMID and active-span focus.

- [ ] **Step 4: Run conversation/account UI tests and production build.**

Run: `npm run test:ui-conversations` from `frontend/`

Run: `npm run test:ui-accounts` from `frontend/`

Run: `npm run build` from `frontend/`

Expected: PASS; production build exits 0.

- [ ] **Step 5: Commit.**

```powershell
git add frontend/src/components/InterpretationPanel.jsx frontend/src/components/EvidenceTable.jsx frontend/src/components/ConversationMessage.jsx frontend/src/components/ConversationWorkspace.jsx frontend/src/components/AuditTrail.jsx frontend/src/editorial.css frontend/tests/ui-conversations.mjs frontend/tests/ui-accounts.mjs
git commit -m "feat: integrate research explainability views"
```

### Task 11: Run the evaluation and complete architecture/demo documentation

**Files:**

- Create: `docs/architecture.md`
- Create: `docs/architecture.mmd`
- Create: `docs/architecture.svg`
- Create: `docs/evaluation_plan.md`
- Create: `docs/evaluation_report.md`
- Create: `docs/api_contract.md`
- Create: `docs/demo_script.md`
- Modify: `README.md`
- Modify: `TEST_READY.md`
- Modify: `PLAN_COMPLIANCE_AUDIT.md`
- Create: `evaluation/reports/<run_id>/report.json`
- Create: `evaluation/reports/<run_id>/report.md`
- Create: `evaluation/reports/manifest.json`
- Test: `tests/unit/test_setup_and_evaluation.py`
- Test: `tests/unit/test_conversational_research_evaluation.py`

**Interfaces:**

- Documentation names exact commands, report IDs, benchmark checksums, access boundaries, and honest limitations.
- The architecture diagram covers offline indexing, query enhancement, plan DAG, retrieval variants, correction, evidence, repair/validation, reports, and public/admin projections.

- [ ] **Step 1: Write failing artifact-validation tests.**

Assert required docs exist, architecture links resolve, manifest points to a complete report, report query count is 30–50, corpus count remains 29,939, all four variants are represented, metric statuses are explicit, and README states evaluation metrics are administrator-only.

- [ ] **Step 2: Run documentation/evaluation tests and confirm RED.**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_setup_and_evaluation.py tests/unit/test_conversational_research_evaluation.py -q`

Expected: FAIL because final artifacts and comprehensive report do not exist.

- [ ] **Step 3: Run the four-variant benchmark and comprehensive evaluation.**

Run: `\.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --variants dense_only hybrid reranked agentic --output-dir evaluation/reports`

Expected: a completed report directory and promoted manifest; every metric is `completed`, `not_run`, or `failed` with a reason. Do not alter corpus/index artifacts.

- [ ] **Step 4: Create documentation and render the architecture diagram.**

Run: `npx -y @mermaid-js/mermaid-cli@11.12.0 -i docs/architecture.mmd -o docs/architecture.svg`

Embed the SVG in `docs/architecture.md`. Document measured results only from the generated report and omit human-review claims.

- [ ] **Step 5: Run focused artifact tests.**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 6: Commit.**

```powershell
git add docs/architecture.md docs/architecture.mmd docs/architecture.svg docs/evaluation_plan.md docs/evaluation_report.md docs/api_contract.md docs/demo_script.md README.md TEST_READY.md PLAN_COMPLIANCE_AUDIT.md evaluation/reports tests/unit/test_setup_and_evaluation.py tests/unit/test_conversational_research_evaluation.py
git commit -m "docs: publish evaluation and demo package"
```

### Task 12: Complete deterministic, live, and browser verification

**Files:**

- Modify only files required by failures reproduced during this task.

**Interfaces:**

- Consumes all prior tasks.
- Produces final verification evidence; no new feature interface.

- [ ] **Step 1: Run the complete deterministic Python suite.**

Run: `\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS, except an exclusively locked live Qdrant check may be separately identified and rerun after the owning process is stopped; no failure may be omitted.

- [ ] **Step 2: Run frontend builds and browser regressions.**

Run from `frontend/`:

```powershell
npm run build
npm run test:ui-conversations
npm run test:ui-accounts
npm run test:ui-evaluation
npm run test:ui-preview
```

Expected: all commands exit 0.

- [ ] **Step 3: Verify corpus immutability.**

Compare `data/manifests/index_manifest.json`, active Qdrant count, article PMID count, and git status against the pre-task values. Expected active count: 29,939 and no changed corpus/index artifact.

- [ ] **Step 4: Verify administrator boundaries with a real browser session.**

Confirm an ordinary account cannot navigate to or fetch evaluation reports, while an administrator can read the generated report. Confirm safe interpretation/evidence still renders for the ordinary account without numeric scores or metrics.

- [ ] **Step 5: Verify optional live RAGAS/NIM runs honestly.**

Run the report command with configured provider credentials. If a provider is unavailable, confirm the persisted metric status and reason are accurate and the deterministic suite remains green.

- [ ] **Step 6: Commit any test-driven fixes from this task.**

```powershell
git add <only files changed by reproduced verification failures>
git commit -m "fix: close plan-completion verification findings"
```

## Final Verification Contract

- Re-read the spec and this plan requirement by requirement.
- Run `git diff --check`.
- Run the full Python suite and all frontend build/UI commands from Task 12.
- Inspect the generated benchmark/report checksums and the administrator boundary tests.
- Run a fresh whole-branch code review against the feature base.
- Fix every Critical or Important finding with a failing regression test followed by a green full suite.
- Use `superpowers:finishing-a-development-branch` for final handoff; do not push or merge without explicit user direction.
