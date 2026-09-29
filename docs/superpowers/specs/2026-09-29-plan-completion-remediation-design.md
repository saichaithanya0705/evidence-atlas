# Plan Completion Remediation Design

## Purpose

Complete the missing runtime, evaluation, explainability, and documentation work from `AI_Medical_Abstract_Finder_Final_Implementation_Plan.md` without rebuilding or enlarging the active 29,939-record corpus.

The finished system must support dependency-aware complex research, targeted corrective retrieval, provenance-preserving evidence extraction, bounded citation repair, reproducible ablation and quality evaluation, and an administrator-only evaluation dashboard. Ordinary users continue to receive useful research answers, public paper metadata, exact supporting evidence spans, and evidence gaps, but never evaluation reports, aggregate metrics, raw model output, prompts, hidden reasoning, or unrestricted internal traces.

## Scope Decisions

- Keep the current corpus and all existing index artifacts unchanged.
- Preserve the existing FastAPI, React/Vite, SQLite, LangGraph, Qdrant, BM25, MedCPT, MeSH, authentication, conversation, and audit architecture.
- Extend existing interfaces instead of introducing a second research engine.
- Build a 30–50-query benchmark from PMIDs present in the active corpus.
- Use NCBI PubMed records and other primary publication pages to verify benchmark relevance judgments. Store source URLs and adjudication notes with each label.
- Describe those judgments as web-assisted benchmark adjudication. Do not claim independent human or biomedical-expert review.
- Show evaluation metrics only to authenticated administrators.
- Keep request-level diagnostic scores, unrestricted traces, and full audit records administrator-only. Public explainability is limited to safe interpretation summaries, channel names without raw scores, exact evidence spans, and paper metadata.

## Chosen Approach

Use one cohesive remediation built around the current research service.

Alternatives rejected:

- A minimal patch would fix individual schema mismatches but leave complex-query coverage and evaluation unmeasurable.
- A separate evaluation service would add deployment and synchronization cost without improving this capstone's correctness.

## Runtime Architecture

### Dependency-aware research planning

Add strict research-plan models:

- `ResearchSubquestion`: stable ID, question, purpose, dependency IDs, required concepts, and status.
- `ResearchPlan`: root question, ordered subquestions, maximum query budget, and a validated acyclic dependency graph.
- `SubquestionCoverage`: subquestion ID, status (`UNCOVERED`, `PARTIAL`, `COVERED`, or `BLOCKED`), supporting PMIDs, missing concepts, and a concise reason.

Only `COMPLEX` queries require a multi-node plan. `SIMPLE` and `MODERATE` queries receive a one-node plan so downstream coverage code has one consistent interface.

The planner is deterministic first. Comparisons create treatment-arm nodes followed by a dependent comparison node; mechanism questions create mechanism and outcome nodes; contradiction questions create evidence-arm nodes followed by an agreement/conflict node. An optional schema-constrained model may refine wording but cannot add dependencies outside the budget, remove required concepts, or create a cycle.

### Coverage-driven retrieval

The LangGraph state carries the research plan and a coverage map. Initial complex retrieval executes ready subquestions in dependency order. The evidence judge returns both its existing overall grade and per-subquestion coverage.

Corrective retrieval selects the highest-priority uncovered or partial subquestion whose dependencies are covered. Its corrective query includes that subquestion and its missing concepts. Generic broadening remains a final fallback only when no actionable subquestion exists. Every generated query still passes through the existing enhancer and router, and route floors and loop budgets remain authoritative.

The final trace records plan nodes, dependencies, coverage changes, targeted corrections, and supporting PMIDs without storing chain-of-thought.

### Evidence provenance

Extend `EvidenceRecord` with:

- `retrieval_provenance`: channel ranks, channel scores, graph path, RRF contribution, applied-filter status, and retrieval iteration.
- `reranker_score` and `reranker_mode`.
- `subquestion_ids`: plan nodes supported by the record.

The evidence extractor copies these values from the selected `RetrievalCandidate`; it never regenerates them. Administrator APIs and audits retain full values. Public projections expose channel names and subquestion associations but remove numerical scores and internal iteration details.

### Targeted citation repair

Citation validation produces a stable ordered claim list plus claim-to-span mappings. If validation fails:

1. Preserve already supported claims byte-for-byte.
2. For each unsupported claim, attempt one bounded repair using only validated spans associated with that claim's cited PMIDs and subquestions.
3. Revalidate the combined answer deterministically and semantically.
4. Prune claims that remain unsupported.
5. If no material claim remains, fail closed to an insufficient-evidence response.

The repair budget is separate from the retrieval-loop budget and cannot cause new retrieval or introduce new PMIDs.

### API contract correction

`POST /analyze-query` returns the declared `AnalyzeQueryResponse` shape:

```json
{
  "query_plan": {}
}
```

The route remains administrator-only under the existing access policy. Compatibility tests cover the OpenAPI schema and serialized response.

## Evaluation Architecture

### Frozen benchmark

Create a versioned benchmark containing 30–50 queries across discovery, treatment effectiveness, safety, association, mechanism, comparison, date filtering, study-type filtering, contradiction, sparse evidence, acronym use, spelling/noise, and complex synthesis.

Each entry contains:

- stable query ID and text;
- category and expected route;
- filters and required subquestions;
- relevant PMIDs from the active corpus with graded relevance;
- reference answer or reference claims when available;
- PubMed or primary-publication source URLs;
- concise adjudication rationale and date;
- corpus/index version identifiers.

An adjudication command verifies that every labelled PMID exists in the active corpus, fetches PubMed metadata through NCBI E-utilities with bounded retries and rate limiting, detects title/PMID mismatches, and writes a deterministic validation report. Network failures mark individual labels unverified and never silently pass.

### Retrieval variants and ablation

Expose a shared evaluation interface with four variants:

1. `dense_only`: original-query MedCPT retrieval with hard filters.
2. `hybrid`: original/canonical dense, BM25, optional graph, and RRF without cross-encoder reranking.
3. `reranked`: hybrid candidates followed by the MedCPT cross-encoder.
4. `agentic`: the complete adaptive planning, corrective retrieval, evidence, synthesis, and validation workflow.

Every variant emits the same per-query artifact: ranked PMIDs, contexts, route, filters, latency, model/index versions, and optional answer fields. Reports compare variants on the same frozen benchmark and configuration.

### Metrics

Compute and persist:

- Recall@5/10, Precision@5/10, MRR@10, and nDCG@10;
- route accuracy and per-route confusion counts;
- year/study-type filter accuracy;
- subquestion coverage and answer completeness;
- citation PMID validity, exact-span validity, attribution accuracy, and supported-claim rate;
- latency by stage, LLM call count, retrieval-loop count, and correction count;
- RAGAS Context Precision, Context Recall, Context Entity Recall, Faithfulness, Response Relevancy, and Answer Correctness when their required reference fields exist;
- claim-level failure categories: retriever miss, context noise, missing evidence, extraction miss, unsupported generation, citation mismatch, and incomplete answer;
- robustness deltas under irrelevant plausible context, conflicting evidence, incomplete evidence, misleading context, noisy spelling, acronyms, and filter pressure.

Missing credentials or optional metric dependencies produce an explicit `not_run` result with a reason. A skipped metric is never represented as zero or success.

### Reports and persistence

Each evaluation run writes immutable JSON and a concise Markdown report under `evaluation/reports/`, including benchmark checksum, corpus/index/model versions, configuration, per-query results, aggregate metrics, failures, and limitations. A small manifest identifies the latest completed report. Partial runs are never promoted to latest.

## Administrator-only Evaluation UI

Add administrator endpoints for listing reports and reading a selected report. They use the existing `require_admin` boundary and return only allowlisted report data. There is no public evaluation route.

Add an `Evaluation` item to the administrator navigation with:

- benchmark and run metadata;
- ablation comparison table;
- retrieval, routing, filtering, citation, grounding, coverage, RAGAS, robustness, and latency metrics;
- per-query failure diagnostics and explicit `not_run` reasons.

Ordinary-user routing redirects or rejects all evaluation paths, and frontend bundles do not fetch evaluation data for ordinary sessions.

## Researcher Explainability UI

Integrate the existing interpretation and evidence components into the live conversation/research workflow:

- show a sanitized interpretation summary containing the original/canonical question, extracted PICO/MeSH concepts, final route label, and planned subquestions;
- render the reusable evidence table with exact supporting spans and PubMed links;
- expose qualitative retrieval channel names and subquestion coverage without raw ranking scores;
- preserve one-tab-per-PMID evidence workspace behavior;
- show the complete audit trail and score breakdown only to administrators.

Evaluation metrics never appear in ordinary research responses or components.

## Error Handling and Safety

- Research-plan validation rejects duplicate IDs, missing dependencies, cycles, oversized plans, and empty subquestions.
- Planner failure falls back to a deterministic plan appropriate to the router-selected complexity.
- Corrective retrieval stops on duplicate queries, exhausted budgets, blocked dependencies, or non-actionable gaps.
- Evaluation commands validate schemas before loading models or making network calls.
- Web adjudication uses bounded concurrency, NCBI rate limits, retry/backoff, and cached raw metadata.
- RAGAS/provider failures are isolated per metric and recorded as `not_run` or failed with a bounded error summary.
- Report APIs reject path traversal and never serve arbitrary filesystem paths.
- All biomedical answer release paths continue to require retrieved PMIDs and exact supporting spans.

## Testing Strategy

Use test-driven development for each behavior:

- model tests for DAG validity, coverage transitions, provenance serialization, and public/admin projections;
- workflow tests for dependency ordering, subquestion-targeted correction, duplicate suppression, budgets, and fallbacks;
- synthesis tests proving supported claims are preserved, unsupported claims are repaired once, repaired text is revalidated, and failures prune or abstain;
- API tests for the wrapped analyze-query contract and administrator-only evaluation endpoints;
- evaluation tests with small deterministic fixtures for all variants, metrics, report promotion, partial failures, and robustness perturbations;
- frontend tests proving the evaluation page is admin-only and safe interpretation/evidence remain available to ordinary users;
- full Python suite, frontend production build, and browser UI regression run before completion.

Live corpus and provider evaluation is separate from deterministic tests. Reports state exactly which optional live checks ran.

## Documentation Deliverables

- architecture document and rendered diagram covering offline indexing, online research DAG, validation, evaluation, and access boundaries;
- API contract and access-control documentation;
- evaluation methodology, benchmark provenance, metric definitions, and run commands;
- generated evaluation report and failure analysis;
- guided eight-minute demo script with a two-minute Q&A buffer;
- README updates for setup, evaluation, administrator access, and limitations.

## Completion Criteria

- Active corpus count and artifacts are unchanged.
- Complex queries expose an acyclic research plan and per-subquestion coverage.
- Corrective retrieval demonstrably targets uncovered subquestions.
- Evidence records preserve retrieval and reranker provenance.
- Invalid claims receive one targeted repair-and-revalidate attempt before pruning or abstention.
- `/analyze-query` matches its declared wrapper contract.
- The frozen benchmark contains 30–50 web-verified, active-corpus queries.
- All four retrieval variants produce comparable saved artifacts and an ablation report.
- Classical, RAGAS, claim-level, robustness, citation, coverage, routing, filtering, and latency evaluations are implemented with honest run status.
- Evaluation APIs and UI are accessible only to administrators.
- Safe interpretation and evidence views are integrated into the researcher workflow without exposing evaluation metrics or internal scores.
- Architecture, evaluation, API, and demo documentation are present and verified.
