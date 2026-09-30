# Implementation plan compliance audit

Audit date: 2026-09-30
Reference: `AI_Medical_Abstract_Finder_Final_Implementation_Plan.md`

This audit describes the implemented local prototype and the measured Task 11 evaluation. Scores from this query-focused benchmark are software evaluation results; they do not establish clinical correctness or broad PubMed performance.

## Current baseline

- The verified active corpus contains 29,994 records. The index manifest reports 29,994 corpus records and 29,994 Qdrant points.
- The active corpus checksum is `de14fbebfb00d541670e1fdf7202deddc60fbe5ae98a2fcc2e8881dc739ebc67`.
- The frozen version 2.0 benchmark contains 40 unique queries and 40 PubMed-linked relevance labels. Label provenance is web-assisted PubMed source verification, matched to the local corpus.
- Task 11 promoted run `eval-1e50313b8ba2-58df625f7252` from 40 queries across dense-only, hybrid, reranked, and agentic variants. The benchmark checksum is `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`.
- Variant retrieval measures and their limits are recorded in [the evaluation report](docs/evaluation_report.md). Aggregate reports and metrics are administrator-only; they do not appear in ordinary-user research views.

## Compliance summary

| Plan area | Status | Evidence and remaining limit |
|---|---|---|
| Corpus and baseline | Partial | The 29,994-record corpus and exact index manifest are verified. The corpus remains below the plan's preferred 100k–250k controlled subset. The 40-query benchmark improves ablation coverage but remains small and query-focused. |
| Data preparation and indexes | Pass for the active baseline | Normalization, deduplication, MedCPT embeddings, BM25, embedded Qdrant, MeSH dictionary/graph, and corpus/index manifests are present. Task 11 did not rebuild the corpus or index. |
| Query understanding and routing | Partial | Structured query understanding and guarded SIMPLE, MODERATE, and COMPLEX routes are implemented. Analysis is predominantly deterministic. |
| Research planning | Partial | A bounded, dependency-checked research-plan DAG and subquestion coverage states are implemented. Planning depth and coverage remain constrained by configured budgets and available abstract data. |
| Retrieval and ranking | Implemented and evaluated | Dense-only, hybrid, reranked, and agentic artifacts were generated for all 40 benchmark entries. See exact Recall@10, Precision@10, MRR@10, nDCG@10, filter, latency, and citation values in the report. |
| Corrective retrieval and evidence | Partial | The workflow supports bounded corrective retrieval, evidence extraction, exact source spans, and provenance. Some abstracts cannot fill all structured fields; unavailable facts remain unasserted. |
| Synthesis and citations | Partial | Claim repair, abstention, PMID membership, and exact span checks are implemented. During the agentic evaluation, NIM returned transient 502/503/internal errors and invalid selections; the workflow used deterministic source-span fallback where available. |
| API, access, and UI | Implemented for the local application | Authentication and administrator boundaries cover audit traces, observability, and evaluation reports. Public research projections omit evaluation metrics and internal trace fields. |
| Evaluation | Measured with explicit limits | The promoted report has 30 completed metrics and 58 `not_run` metrics with null values and reasons; no metrics failed or were coerced to zero. RAGAS remained `not_run`; its collection import smoke failed because `langchain_community.chat_models.vertexai` is unavailable in this environment. The robustness scores are based on saved artifacts, without new retrieval/model runs. |
| Reproducibility and docs | Pass for Task 11 package | Architecture source and SVG, evaluation plan/report, API contract, demo script, README updates, and this audit are included. Exact commands, run ID, checksums, measured values, and visibility boundaries are documented. |

## Deliverables

| Deliverable | Task 11 status |
|---|---|
| Architecture diagram and detailed architecture | Complete: `docs/architecture.mmd`, `docs/architecture.svg`, and `docs/architecture.md` |
| Reproducible evaluation plan and measured report | Complete: `docs/evaluation_plan.md` and `docs/evaluation_report.md` |
| API contract and administrator demo | Complete: `docs/api_contract.md` and `docs/demo_script.md` |
| Setup and evaluation usage | Updated in `README.md` and `TEST_READY.md` |
| Backend and report access | Existing implementation; evaluation reads remain administrator-only and read-only |
| Docker packaging | Remains waived in the project plan |

The project remains a local research prototype, not a clinical decision tool or a production-scale PubMed service. Deployment scale, provider reliability, and the corpus-size target remain separate work.
