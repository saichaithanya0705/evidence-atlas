# TEST_READY.md: AI-Powered Medical Research Abstract Finder

**Status**: Historical test inventory; current account-aware verification is described in `frontend/tests/README.md` and the latest `pytest` result.
**Current verification (2026-09-29, Task 11)**: With process-scoped `LLM_MODE=mock` and empty `NVIDIA_API_KEY`, full backend suite: 968 passed, 4 failed, 1 skipped. The only failures are the four empirical Qdrant storage checks listed below that cannot acquire `data/qdrant_storage/.lock` while the existing backend owns it. The NIM TLS recursion was fixed with an explicit certifi-backed shared transport; bounded live planner and synthesis checks returned provider-backed results. Standalone verifier requests were intermittent: one supported verdict succeeded and later calls got NIM `InternalServerError` and failed closed. Conversation, preview, and account browser checks passed; Vite production build passed with the installed Node 20.18.0 compatibility warning (Vite requires 20.19+ or 22.12+). The historical inventory below describes earlier milestones.
**E2E Test Cases**: 398 passed (0 failed, 0 skipped)  
**Current Project Suite**: 762 passed in total (756 non-loader tests + 6 isolated MedCPT/index loader tests)  
**Latest Verification**: 2026-09-26; frontend production build and npm audit also passed  
**Execution Note**: On this Windows host, the MedCPT loader file was run in a fresh process after the remaining 755 tests to avoid native Torch/SafeTensors resource contention.  
**Test Framework**: `pytest` 8.3.3 + `pytest-asyncio` + `starlette.testclient`  
**Test Suite Directory**: `tests/e2e/`  
**Test Fixtures**: `tests/fixtures/synthetic_pubmed.csv` (30 records), `tests/fixtures/mock_responses.json`

---

## 1. Test Suite Architecture & Coverage Breakdown

The E2E test framework implements the 4-tier opaque-box methodology specified in `ORIGINAL_REQUEST.md`, `PROJECT.md`, and `TEST_INFRA.md`.

| Tier | Test Module | Scope & Methodology | Test Count | Pass Rate | Target Requirement |
|---|---|---|:---:|:---:|---|
| **Tier 1** | `tests/e2e/test_tier1_features.py` | Core feature verification across R1–R7: Setup automation, MedCPT caching, secret hygiene, CSV schema cleaning, MeSH/keyword parsing, concept graph, QueryPlan contracts, adaptive router (SIMPLE, MODERATE, COMPLEX), RRF ($k=60$), cross-encoder reranking, CRAG sufficiency grader, evidence extraction, synthesis, deterministic citation verification, FastAPI endpoints (`/health`, `/metrics`, `/analyze-query`, `/search`, `/research`, `/paper/{pmid}`, `/trace/{request_id}`), and UI contracts. | 185 | 100% | R1, R2, R3, R4, R5, R6, R7 |
| **Tier 2** | `tests/e2e/test_tier2_boundaries.py` | Boundary Value Analysis (BVA) & Corner Cases: Empty/whitespace queries (HTTP 422), single-word queries, extreme query lengths (up to 8,000 chars), adversarial payloads (SQLi, XSS, Unicode RTL, null bytes), accented medical terms (diacritics), extreme publication years (1899–2100), edge MeSH formatting, malformed CSV records, partial/null PICO fields, zero search results, extreme top_k limits, RRF constant $k$ variations, and non-existent PMIDs (HTTP 404). | 142 | 100% | BVA across R1–R7 |
| **Tier 3** | `tests/e2e/test_tier3_combinations.py` | Pairwise Cross-Feature Integration: Query Understanding -> Router Decision -> Retrieval Channel Configuration -> RRF Rank Fusion -> Cross-Encoder Reranking -> CRAG Sufficiency Judge -> Corrective Search / Abstention Loop -> Evidence Extraction -> Synthesis -> Deterministic Citation Gate -> Audit Trace Logging -> Inferred Temporal / Design Filters to Result Cards. | 42 | 100% | Cross-Module Contracts |
| **Tier 4** | `tests/e2e/test_tier4_scenarios.py` | Real-World Clinical Researcher Workloads: S1 (Comparative Drug Efficacy: GLP-1 RA vs SGLT2i in T2D with CKD), S2 (Rare Disease CRAG Corrective Loop: Sotorasib KRAS G12C NSCLC), S3 (Corpus Absence Abstention: Hyperbaric oxygen in Stage IV Alzheimer's tau), S4 (Strict Temporal & Design Filters: Pediatric mRNA vaccines after 2022), S5 (Lay Acronym Normalization: T2D heart attack risk with metformin), plus extended workloads S6–S10 (Asthma biologics, breast cancer ADCs, resistant hypertension denervation, aldosterone synthase inhibition, Alzheimer's monoclonal antibodies). | 29 | 100% | Realistic User Journeys |
| **Total** | **Full E2E Test Suite** | **Comprehensive Opaque-Box Quality Gates** | **398** | **100%** | **Full Specification** |

---

## 2. Test Runner Commands

### Running Full E2E Test Suite
```bash
python -m pytest tests/e2e/ -v --tb=short
```

### Running Specific Tiers
```bash
# Tier 1: Feature verification (185 tests)
python -m pytest tests/e2e/test_tier1_features.py -v --tb=short

# Tier 2: Boundary & Corner Cases (142 tests)
python -m pytest tests/e2e/test_tier2_boundaries.py -v --tb=short

# Tier 3: Cross-Feature Combinations (42 tests)
python -m pytest tests/e2e/test_tier3_combinations.py -v --tb=short

# Tier 4: Clinical Researcher Scenarios (29 tests)
python -m pytest tests/e2e/test_tier4_scenarios.py -v --tb=short
```

---

## 3. Strict Verification & Invariant Gates Enforced

1. **100% Deterministic Citation Precision**:
   - `Cited PMIDs ⊆ EvidencePack PMIDs`.
   - Any cited PMID not present in the retrieved evidence set immediately triggers `is_valid = False` with zero tolerance for hallucinated PMIDs.
   - Tested against adversarial injection of fabricated PMIDs (`[PMID: 99999999]`), confirming immediate fail-closed or repair action.
2. **Graceful Abstention on Insufficient Evidence**:
   - When evidence is insufficient or completely absent (Scenario S3), the system gracefully abstains, cites zero unsupported claims, and outputs explicit evidence gap statements.
3. **Strict Filter Adherence**:
   - Hard temporal constraints (e.g. `year > 2022`) and study design constraints (e.g. `Randomized Controlled Trial`) are strictly enforced, ensuring 100% compliance in returned candidate sets.
4. **Acronym & MeSH Mapping**:
   - Clinical acronyms (`T2D`, `CKD`, `NSCLC`, `MACE`, `HBOT`) expand to standardized medical descriptors without semantic drift.
5. **RRF Mathematical Invariant**:
   - Reciprocal Rank Fusion enforces deterministic scoring: $RRF(d) = \sum_{channel} \frac{1}{k + rank_{channel}(d)}$ with $k=60$.

---

## 4. Test Fixtures Reference

- **`tests/fixtures/synthetic_pubmed.csv`**:
  30 medically realistic research abstracts spanning:
  - Type 2 Diabetes, SGLT2 inhibitors (Empagliflozin, Dapagliflozin), GLP-1 receptor agonists (Semaglutide), CKD, heart failure.
  - KRAS G12C mutated NSCLC (Sotorasib, Adagrasib, CodeBreaK 200, KRYSTAL-1, secondary mutations, MET amplification bypass, SHP2 co-inhibition).
  - Pediatric mRNA vaccines (BNT162b2, mRNA-1273, RSV mRNA, bivalent boosters, myopericarditis surveillance).
  - Resistant hypertension (Renal denervation SPYRAL HTN, Baxdrostat aldosterone synthase, dual RAAS blockade).
  - Alzheimer's disease (Lecanemab Clarity AD, Donanemab TRAILBLAZER-ALZ 2, tau PET imaging, hyperbaric oxygen ineffectiveness).
  - Metformin macrovascular outcomes (UKPDS 10-year follow-up, metformin vs sulfonylureas).
  - Asthma biologics (Tezepelumab NAVIGATOR), HER2 breast cancer ADCs (Trastuzumab deruxtecan DESTINY-Breast03), and ulcerative colitis (Upadacitinib).
- **`tests/fixtures/mock_responses.json`**:
  Deterministic mocks for query analysis, PICO extraction, router classification, CRAG sufficiency grades, and syntheses for Scenarios S1–S5 and adversarial edge cases.
- **`tests/e2e/e2e_contracts.py`**:
  Strict Pydantic contract models (`PICOModel`, `QueryPlan`, `RetrievalCandidate`, `EvidenceRecord`, `ResearchResponse`) and reference invariant evaluation functions.

## Conversational research: deterministic verification

The conversation agent is a biomedical literature interface, not medical advice or a clinical decision system. Its query path is conversation agent → query enhancer → guarded router → research workflow. Enhancement runs for initial and corrective queries. Route complexity is `max(deterministic rule, valid agent hint, prior route floor)`. Claims are released only with a retrieved PMID and exact supporting abstract span; a `LIMITED` response contains only the independently supported portion. `INSUFFICIENT` means no claim passed release checks, and `FAILED` denotes a technical failure.

History, message, title, provider request time, model output, and correction loops are bounded by `CONVERSATION_HISTORY_TURN_LIMIT` (12), `CONVERSATION_MESSAGE_MAX_CHARS` (4000), `CONVERSATION_TITLE_MAX_CHARS` (80), `LLM_TIMEOUT_SECONDS` (30 seconds per provider request), `AGENT_OUTPUT_MAX_TOKENS` (800), and `MAX_CORRECTIVE_LOOPS` (2). A conversation permits one running turn; a duplicate is rejected with 409. Conversations and bounded linked administrator audit summaries are durable in the application SQLite database until operators archive or remove that database. Audits do not retain prompts, raw provider output, or chain-of-thought. Public responses omit internal scores and diagnostics.

`LLM_MODE=mock` is deterministic offline fallback behavior and is not live planner or semantic-grader intelligence. A configured live check requires `LLM_MODE=nim` and a nonempty valid `NVIDIA_API_KEY`. Real-index checks are also separate from deterministic checks and require exclusive Qdrant access. Neither optional check changes the PubMed corpus or index.

Run the safe fixture evaluator and focused checks from the project root:

```powershell
python scripts/evaluate_conversational_research.py tests/fixtures/conversational_research_report.json
python -m pytest tests/adversarial/test_conversational_research_guardrails.py tests/unit/test_conversational_research_evaluation.py -q
```

The fixture evaluator accepts a JSON report object and never reads the live corpus. It reports deterministic route accuracy, correction-loop count, answer-status and abstention distribution, unsupported released-claim rate, citation validity, claim attribution, latency, and LLM-call count. Optional LLM-as-judge and RAGAS-style values are secondary evidence and cannot override these checks.

Run all deterministic browser checks from `frontend/`:

```powershell
npm run test:ui-conversations
npm run test:ui-preview
npm run test:ui-accounts
npm run build
```

The conversation browser fixture covers creation, initial and follow-up messages, limited and insufficient rendering, unique PMID tabs with turn-specific spans, collapse/reopen, reload, and linked administrator audit navigation. It does not exercise live provider intelligence. See `frontend/tests/README.md` for the separate backend-backed stress suite.
