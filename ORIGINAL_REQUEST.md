# Original User Request

## 2026-09-25T15:03:08Z

Requested team: Full multi-agent team to build the complete end-to-end project across backend, frontend, indexing, and evaluation

Build an AI-Powered Medical Research Abstract Finder: an adaptive agentic evidence RAG system that ingests PubMed/MEDLINE abstracts, indexes them in a hybrid vector/sparse knowledge base, dynamically routes queries by complexity, retrieves and reranks evidence, verifies claims, and presents traceable synthesized summaries through a FastAPI backend and React frontend.

Working directory: d:/projects/capstone
Integrity mode: demo

## Requirements

### R1. Environment & Asset Setup Automation
- Provide a single unified setup script (`python scripts/setup_assets.py`) that downloads a curated PubMed/MEDLINE CSV dataset into `data/raw/` and caches the MedCPT models (`ncbi/MedCPT-Query-Encoder`, `ncbi/MedCPT-Article-Encoder`, `ncbi/MedCPT-Cross-Encoder`) for offline/local reuse.
- Support standard `.env` configuration for `NVIDIA_API_KEY`, model selection (NVIDIA NIM OpenAI-compatible endpoint `https://integrate.api.nvidia.com/v1`), and Qdrant storage path.

### R2. Data Preprocessing & Hybrid Knowledge Base
- Ingest and preprocess the PubMed dataset (schema validation, deduplication of PMIDs, text normalization, MeSH term and keyword extraction).
- Index abstracts into Qdrant using embedded local disk mode (`./data/qdrant_storage`), storing MedCPT article dense embeddings, BM25 sparse lexical tokens, and metadata payloads (year, authors, publication type, MeSH).
- Construct a lightweight Paper-MeSH concept graph (via NetworkX) for relation-based concept neighbor retrieval.

### R3. Biomedical Query Understanding & Adaptive Router
- Implement a biomedical query analyzer that preserves the original query, normalizes acronyms/spelling, maps MeSH terms, extracts PICO concepts (Population, Intervention, Comparator, Outcome), and infers search filters (e.g. publication year).
- Implement an Adaptive Router that classifies queries into:
  - **SIMPLE**: Single hybrid retrieval pass with metadata filters.
  - **MODERATE**: Multi-query biomedical expansion followed by merged retrieval.
  - **COMPLEX**: Decomposition into a research plan DAG with subquestions and iterative retrieval.

### R4. Hybrid Retrieval, RRF, MedCPT Reranking & CRAG Evidence Judge
- Execute multi-channel retrieval: original + canonical query dense vectors (MedCPT Query Encoder), BM25 sparse search, MeSH graph neighbors, and hard metadata filters.
- Merge candidate rankings using Reciprocal Rank Fusion (RRF) and rerank the top candidates using the MedCPT Cross-Encoder.
- Apply a CRAG-style Evidence Quality Judge: evaluate sufficiency (SUFFICIENT, PARTIAL, INSUFFICIENT). If partial or insufficient and search budget remains, trigger corrective query reformulation; if exhausted, gracefully abstain with available sources.

### R5. Structured Evidence Extraction, Synthesis & Citation Validation
- Extract structured `EvidenceRecord` items for top papers (PICO elements, findings, limitations, exact supporting abstract spans).
- Group evidence to detect consensus, contradictions, and evidence gaps across studies.
- Synthesize an evidence-grounded research summary via NVIDIA NIM API.
- Execute deterministic citation validation: every cited PMID must exist in the retrieved evidence set and map to supporting text spans (100% citation precision, zero hallucinated PMIDs; fail closed if unverified).

### R6. FastAPI Backend Service
- Expose typed endpoints using Pydantic:
  - `POST /search`: Direct hybrid retrieval with route and filter controls.
  - `POST /analyze-query`: Query normalization, PICO extraction, and route classification.
  - `POST /research`: Full end-to-end agentic workflow returning synthesis, evidence table, citations, and audit trace.
  - `GET /paper/{pmid}`: Paper metadata and abstract retrieval.
  - `GET /trace/{request_id}`: Step-by-step retrieval and reasoning audit trail.
  - `GET /health`: Service health check.

### R7. React + Vite Researcher Application
- Implement a responsive React + Vite web application with:
  - Natural-language query search bar and metadata filters (publication year, study type).
  - Expandable "How this search was understood" panel showing normalized query and PICO concepts.
  - Ranked paper cards with PMID, authors, year, MeSH tags, and abstract preview.
  - Structured Cross-Study Evidence Table comparing studies.
  - Evidence-grounded synthesis with clickable PubMed citation links.
  - "Why this paper?" provenance drawer showing dense, BM25, and reranker score contributions.
  - Claim-to-evidence interactive highlighting and Research Audit Trail drawer.

## Acceptance Criteria

### Automation & Knowledge Base
- [ ] Single setup command (`python scripts/setup_assets.py`) successfully prepares sample PubMed data and verifies MedCPT models.
- [ ] Ingestion script processes raw records, deduplicates PMIDs, normalizes dates and MeSH terms, and builds the Qdrant embedded collection and MeSH graph without errors.

### Retrieval & Agentic Routing
- [ ] Hybrid retrieval returns relevant papers combining MedCPT dense similarity and BM25 lexical matching with RRF scoring.
- [ ] Query analyzer accurately parses PICO fields and classifies queries into SIMPLE, MODERATE, and COMPLEX.
- [ ] Corrective retrieval loop triggers when initial evidence is insufficient and respects the max-iteration budget.

### Grounding & Citations
- [ ] 100% of cited PMIDs in synthesized research answers exist in the retrieved evidence set.
- [ ] Unsupported claims or unverified PMIDs trigger repair or are pruned before returning the response.
- [ ] The system abstains or explicitly reports evidence gaps when insufficient evidence exists.

### System Integration & UI
- [ ] FastAPI backend starts locally (`uvicorn backend.app.main:app`) and all endpoints (`/health`, `/search`, `/analyze-query`, `/research`, `/paper/{pmid}`) respond successfully.
- [ ] React frontend builds and runs via Vite (`npm run dev` / `npm run build`), connects to the FastAPI backend, and renders search, synthesis, evidence tables, citation links, and provenance views.

## Follow-up — 2026-09-26T03:56:19Z

The server has restarted and quota is refreshed. The root .gitignore has been created and verified with git check-ignore, resolving the Milestone 1 audit finding. Please resume execution from Milestone 1 gate verification and proceed through Milestone 2 (Query Understanding & Adaptive Router).

