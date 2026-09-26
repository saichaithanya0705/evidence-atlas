# Implementation Plan Compliance Audit

Audit date: 2026-09-26

Reference: `AI_Medical_Abstract_Finder_Final_Implementation_Plan.md`

This report distinguishes implemented behavior from aspirational plan items. It does not treat passing tests on the bundled demo corpus as proof of real-world biomedical relevance.

## Direct startup and asset answers

- `start.bat` creates/reuses `.venv`, installs Python requirements, creates `.env` only when absent, invokes `scripts/setup_project.py`, installs frontend dependencies, rebuilds every M1 artifact, and starts FastAPI plus Vite.
- A normal online run verifies and caches all three required Hugging Face assets: `ncbi/MedCPT-Query-Encoder`, `ncbi/MedCPT-Article-Encoder`, and `ncbi/MedCPT-Cross-Encoder`. Failure to load any of them fails startup.
- `start.bat --offline` performs no model download. It uses complete local caches when available and otherwise explicitly enables deterministic mock embeddings; that mode must not be described as real MedCPT retrieval.
- Dataset preparation exists, but it is not a real PubMed bulk downloader. If `data/raw/pubmed_sample.csv` is absent, setup copies the bundled 30-record synthetic fixture. If a CSV already exists, it validates and preserves it.
- A real PubMed/MEDLINE run therefore requires an authorized CSV to be placed at `data/raw/pubmed_sample.csv` before startup. Automatically choosing and downloading the full PubMed baseline would be unsafe and impractical for a one-click demo because source, licensing, size, update date, and evaluation labels must be controlled explicitly.

## Phase compliance matrix

| Plan area | Status | Evidence and remaining limitation |
|---|---|---|
| 0. Corpus and baseline | **Partial** | Canonical schema and repeatable evaluation exist, but the active corpus has 30 synthetic records rather than the preferred 100k-250k controlled subset; the frozen evaluation set has 7 rather than 30-50 queries; no saved dense-only baseline is present. |
| 1. Data preparation and knowledge base | **Pass/Partial** | Schema inspection, deduplication, normalization, MedCPT article embeddings, BM25, embedded Qdrant, Paper-MeSH graph, and manifests are implemented. Real-corpus acquisition is external, and the active data is demo-only. |
| 2. Query understanding | **Partial** | Original query preservation, normalization, acronym/MeSH mapping, filters, and dual queries exist. The production path is primarily deterministic; the optional LLM canonicalizer is not the default. |
| 3. Medical query analysis | **Partial** | Typed PICO/non-PICO concepts, weights, filters, and query plans exist, but extraction is mainly rule-based and is not a complete semantic biomedical parser. |
| 4. Adaptive routing | **Pass** | SIMPLE, MODERATE, and COMPLEX routes include confidence/reasoning and control retrieval channels. |
| 5. Expansion and research planning | **Partial** | Route-specific subqueries exist. Complex queries do not yet produce a full dependency-aware research-plan DAG with per-subquestion evidence coverage. |
| 6. Hybrid retrieval and reranking | **Pass/Partial** | Original/canonical MedCPT dense retrieval, BM25, hard filters, selective graph expansion, RRF, MedCPT cross-encoder reranking, and provenance are implemented. Relevance evidence is limited to the small demo benchmark. |
| 7. CRAG evidence correction | **Partial** | A real LangGraph `StateGraph` now executes query analysis, retrieval, judging, bounded correction, evidence extraction, synthesis, validation, and completion. Corrective searches remain template/missing-concept based rather than explicit missing-subquestion planning. |
| 8. Structured evidence extraction | **Partial** | Structured evidence records and exact supporting spans are implemented. Abstract-only data cannot reliably fill every PICO/study-detail field, so unsupported values remain null. |
| 9. Cross-study analysis and synthesis | **Partial** | Evidence grouping, agreement/conflict/gap signals, grounded deterministic fallback, and optional NIM synthesis exist. The deterministic comparison layer remains heuristic and requires human biomedical review. |
| 10. Citation validation | **Pass/Partial** | Returned PMIDs are constrained to retrieved evidence; unsupported numbers and clear direction/negation conflicts are rejected, and invalid output fails closed. These deterministic checks are safeguards, not a substitute for semantic entailment or human review. |
| 11. API and observability | **Pass/Partial** | Typed search, analysis, research, paper, trace, health, and metrics endpoints exist. Traces and metrics are bounded in-process data rather than durable production telemetry. |
| 12. Research UI | **Pass with approved override** | Responsive search, result cards, synthesis, paper details, admin evidence/provenance, and audit UI exist. Per the later explicit requirement, query analysis, evidence spans, provenance, and traces are administrator-only even where the original plan described them as researcher-facing. |
| 13. Evaluation | **Partial** | Classical IR/router metrics and deterministic citation checks exist. RAGAS, RAGChecker-style diagnostics, ablations, robustness reports, 30-50 judged queries, and formal human evaluation are not complete and must not be fabricated. |
| 14. Hardening and reproducibility | **Pass/Partial** | Secret hygiene, medical disclaimer, bounded loops/timeouts, fail-closed behavior, structured traces, raw publication-date preservation, corpus SHA-256, and encoder revision binding exist. Multi-user production authentication, durable trace storage, and production monitoring remain deployment work. |

## Deliverables

| Deliverable | Status |
|---|---|
| D1 architecture diagram asset | Missing |
| D2 detailed design document | Partial: implementation plan plus this audited implementation mapping |
| D3 modular FastAPI backend | Implemented |
| D4 React research UI | Implemented with the approved administrator-only diagnostics override |
| D5 setup and usage documentation | Implemented in `README.md` |
| D6 comprehensive evaluation report | Partial: demo classical metrics only |
| D7 Docker packaging | Intentionally waived by the user |
| D8 presentation deck/demo script | Missing |

## Verification standard

The project is a working local demo: focused integration tests, frontend production build, dependency audit, online verification of all three MedCPT assets, the complete indexing pipeline, health checks, and a live real-model search have passed. It must not be called plan-complete or production-ready while the real corpus, comprehensive relevance evaluation, human evaluation, and remaining documentation deliverables are absent.
