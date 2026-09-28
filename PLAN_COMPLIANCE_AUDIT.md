# Implementation Plan Compliance Audit

Audit date: 2026-09-28

Reference: `AI_Medical_Abstract_Finder_Final_Implementation_Plan.md`

This report distinguishes implemented behavior from aspirational plan items. It does not treat passing tests on the bundled demo corpus as proof of real-world biomedical relevance.

## Direct startup and asset answers

- `start.bat` creates/reuses `.venv`, installs Python requirements, creates `.env` only when absent, invokes `scripts/setup_project.py`, installs frontend dependencies, rebuilds every M1 artifact, and starts FastAPI plus Vite.
- A normal online run verifies and caches all three required Hugging Face assets: `ncbi/MedCPT-Query-Encoder`, `ncbi/MedCPT-Article-Encoder`, and `ncbi/MedCPT-Cross-Encoder`. Failure to load any of them fails startup.
- `start.bat --offline` performs no model download. It uses complete local caches when available and otherwise explicitly enables deterministic mock embeddings; that mode must not be described as real MedCPT retrieval.
- `start.bat --ingest` now reads relevant PMID lists from `PubMed_Phrases.tar.gz`, fetches the original PubMed XML from the official NCBI E-utilities endpoint, writes the canonical CSV, then executes the normal indexing/startup path. `PUBMED_INGEST_LIMIT` bounds the request; the default asks for every unique PMID available from the configured archive phrases.
- The acquired raw artifact contains 29,995 usable PubMed abstracts from 30,148 requested unique PMIDs. After content deduplication, all 29,939 records are active in the MedCPT, BM25, Qdrant, and paper-MeSH indexes. The archive checksum and ingestion/transformation counts are recorded, and the synthetic fixture remains test-only.
- Raw acquired abstracts and generated indexes are intentionally excluded from Git. The committed ingestion code and manifests reproduce this verified state when `start.bat --ingest` is run with the phrase archive on the target system.
- This workstation now has a CUDA-enabled PyTorch build and the full MedCPT article-encoder pass completed with durable resume checkpoints. Exact post-build checks confirmed 29,939 finite 768-dimensional unit-normalized vectors whose PMID order and corpus hash match the cleaned data.

## Phase compliance matrix

| Plan area | Status | Evidence and remaining limitation |
|---|---|---|
| 0. Corpus and baseline | **Partial** | Canonical schema and repeatable evaluation exist. The active index has 29,939 original PubMed records, still below the preferred 100k-250k active subset; the real pilot benchmark has 5 rather than 30-50 independently judged queries, and no saved dense-only baseline is present. |
| 1. Data preparation and knowledge base | **Pass** | Official-source acquisition, schema inspection, deduplication, original/normalized date and publication-type preservation, full-corpus MedCPT article embeddings, BM25, embedded Qdrant, Paper-MeSH graph, exact point-ID/vector validation, checksums, and manifests are implemented for all 29,939 cleaned records. |
| 2. Query understanding | **Partial** | Original query preservation, normalization, acronym/MeSH mapping, filters, and dual queries exist. The production path is primarily deterministic; the optional LLM canonicalizer is not the default. |
| 3. Medical query analysis | **Partial** | Typed PICO/non-PICO concepts, weights, filters, and query plans exist, but extraction is mainly rule-based and is not a complete semantic biomedical parser. |
| 4. Adaptive routing | **Pass** | SIMPLE, MODERATE, and COMPLEX routes include confidence/reasoning and control retrieval channels. |
| 5. Expansion and research planning | **Partial** | Route-specific subqueries exist. Complex queries do not yet produce a full dependency-aware research-plan DAG with per-subquestion evidence coverage. |
| 6. Hybrid retrieval and reranking | **Pass/Partial** | Original/canonical MedCPT dense retrieval, BM25, hard filters, selective graph expansion, RRF, MedCPT cross-encoder reranking, and provenance are implemented against the full active corpus. Relevance evidence is still limited to the provisional five-query pilot and UI scenarios. |
| 7. CRAG evidence correction | **Partial** | A real LangGraph `StateGraph` now executes query analysis, retrieval, judging, bounded correction, evidence extraction, synthesis, validation, and completion. Corrective searches remain template/missing-concept based rather than explicit missing-subquestion planning. |
| 8. Structured evidence extraction | **Partial** | Structured evidence records and exact supporting spans are implemented. Abstract-only data cannot reliably fill every PICO/study-detail field, so unsupported values remain null. |
| 9. Cross-study analysis and synthesis | **Partial** | Evidence grouping, agreement/conflict/gap signals, grounded deterministic fallback, and optional NIM synthesis exist. The deterministic comparison layer remains heuristic and requires human biomedical review. |
| 10. Citation validation | **Pass/Partial** | Returned PMIDs are constrained to retrieved evidence; unsupported numbers and clear direction/negation conflicts are rejected, and invalid output fails closed. These deterministic checks are safeguards, not a substitute for semantic entailment or human review. |
| 11. API and observability | **Pass/Partial** | Typed search, analysis, research, paper, trace, health, and metrics endpoints exist. Query analysis, traces, metrics, detailed health state, scores, consensus analysis, and evidence-gap diagnostics require administrator credentials; traces and metrics remain bounded in-process data rather than durable production telemetry. |
| 12. Research UI | **Pass with approved override** | Responsive search, result cards, synthesis, paper details, admin evidence/provenance, and audit UI exist. Per the later explicit requirement, query analysis, evidence spans, provenance, and traces are administrator-only even where the original plan described them as researcher-facing. |
| 13. Evaluation | **Partial** | Classical IR/router metrics, deterministic citation checks, a five-query provisional real-corpus pilot, and real-browser stress validation exist. The UI run completed 21/21 ordinary-user flows, including 2, 5, and 10 concurrent users plus 390-pixel mobile, with no application failures or HTTP 5xx; p95 was 98.456 seconds. The pilot measured BM25 Recall@10 0.933, MRR@10 1.0, nDCG@10 0.941, and router accuracy 0.6; labels remain provisional. RAGAS, RAGChecker-style diagnostics, ablations, 30-50 independently judged queries, and formal human evaluation are not complete and must not be fabricated. |
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

The project is a working local real-data prototype: 781 tests passed (one corpus-inapplicable keyword probe skipped), the frontend production build passed, all three MedCPT assets load online, the index has exact 29,939/29,939 PMID identity, and 21/21 real ordinary-user browser flows returned ranked papers and synthesis while keeping all diagnostics administrator-only. Live NVIDIA NIM generation was exercised; malformed or timed-out model responses were validated and failed closed to grounded deterministic synthesis. It must not be called plan-complete or production-ready while the preferred 100k-250k active corpus, comprehensive independent relevance evaluation, human evaluation, D1 architecture asset, D8 presentation, identity-aware multi-user authentication, and production vector service remain incomplete.
