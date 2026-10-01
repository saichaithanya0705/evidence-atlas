# Corpus Grounding and Local Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild a broad, current PubMed corpus, prevent false `INSUFFICIENT` releases when exact grounded evidence exists, and restore the local UI/API with an authenticated end-to-end check.

**Architecture:** The ingestion selection becomes balanced across explicit biomedical topic phrases instead of filling the corpus from the first phrase's results. Re-indexing occurs only after the staged raw corpus passes schema, coverage, and metadata checks. The answer gate remains fail-closed for unsupported claims, but accepts a cited limited answer when validated source spans cover the answerable portion of a retrieved question.

**Tech Stack:** Python 3.11, NCBI PubMed E-utilities, MedCPT, BM25, embedded Qdrant, FastAPI, React/Vite, pytest.

---

### Task 1: Balanced PubMed seed selection and staged corpus validation

**Files:**
- Modify: `scripts/ingest_pubmed_phrases.py`
- Modify: `tests/unit/test_pubmed_phrase_ingestion.py`
- Create: `scripts/validate_corpus_coverage.py`

- [ ] **Step 1: Write failing selection tests**

```python
def test_balanced_selection_reserves_records_for_each_phrase():
    mapping = {
        "kidney disease": ["1", "2", "3", "4"],
        "mrna vaccine": ["4", "5", "6", "7"],
    }

    assert select_pmids_balanced(mapping, limit=4) == ["1", "4", "5", "2"]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_pubmed_phrase_ingestion.py::test_balanced_selection_reserves_records_for_each_phrase -q`

Expected: FAIL because `select_pmids_balanced` does not exist.

- [ ] **Step 3: Implement balanced round-robin PMID selection**

```python
def select_pmids_balanced(mapping: dict[str, list[str]], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    offsets = {phrase: 0 for phrase in mapping}
    while len(selected) < limit:
        progressed = False
        for phrase, pmids in mapping.items():
            while offsets[phrase] < len(pmids) and pmids[offsets[phrase]] in seen:
                offsets[phrase] += 1
            if offsets[phrase] < len(pmids):
                pmid = pmids[offsets[phrase]]
                offsets[phrase] += 1
                seen.add(pmid)
                selected.append(pmid)
                progressed = True
                if len(selected) == limit:
                    break
        if not progressed:
            break
    return selected
```

Make balanced selection the default; retain `--selection-mode legacy` only for reproducible historical runs. Add `--profile broad-medical` with the validated phrase list.

- [ ] **Step 4: Run the ingestion tests and verify GREEN**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_pubmed_phrase_ingestion.py -q`

Expected: PASS with the new selection test and existing parsing/TLS tests.

- [ ] **Step 5: Stage and validate the new official corpus**

Run PubMed extraction to a timestamped staging CSV using `--profile broad-medical --limit 100000`, then run `scripts/validate_corpus_coverage.py` against that CSV. The validator must require non-empty records for mRNA-vaccine/respiratory, diabetes/cardiovascular, CKD/SGLT2, comparative-treatment, and recent-publication probes; it must also require unique numeric PMIDs and non-empty title/abstract fields.

- [ ] **Step 6: Promote only validated artifacts and rebuild every dependent index**

Back up current raw and generated artifacts under an immutable timestamped directory, promote the staged CSV atomically, then run preprocessing, MedCPT embeddings, BM25, MeSH dictionary/graph, and Qdrant indexing. Confirm corpus, embedding, BM25, and Qdrant PMID sets agree before proceeding.

### Task 2: False-abstention regression contract

**Files:**
- Modify: `tests/unit/test_research_pipeline.py`
- Modify: `backend/app/workflow/judge.py`
- Modify: `backend/app/workflow/service.py`

- [ ] **Step 1: Write a failing false-abstention regression test**

```python
def test_validated_grounded_evidence_releases_limited_answer_when_one_subquestion_remains_uncovered():
    response = service.answer_from_evidence(
        "What hemoglobin response rates follow oral iron in iron-deficient nondialysis CKD?",
        candidates=[candidate_with_exact_oral_iron_evidence],
        evidence=[record_with_exact_oral_iron_span],
    )

    assert response.answer_status is AnswerStatus.LIMITED
    assert response.cited_pmids == ["29092739"]
    assert "insufficient" not in response.synthesis.casefold()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_pipeline.py::test_validated_grounded_evidence_releases_limited_answer_when_one_subquestion_remains_uncovered -q`

Expected: FAIL because the existing combined concept/subquestion gate produces `INSUFFICIENT`.

- [ ] **Step 3: Implement the narrow release correction**

Keep `SUPPORTED` reserved for complete evidence coverage. When exact-span citation and semantic checks pass, no evidence conflict exists, and at least one answerable source-backed claim remains, release `LIMITED` with the explicit unmet subquestion/evidence gap. Do not allow a provider grade to delete independently validated local evidence merely because another subquestion is uncovered.

- [ ] **Step 4: Run focused regression and adversarial evidence tests**

Run: `\.venv\Scripts\python.exe -m pytest tests/unit/test_research_pipeline.py tests/unit/test_evidence_verification.py tests/adversarial/test_conversational_research_guardrails.py -q`

Expected: PASS; unsupported, conflicting, malformed-citation, and no-evidence paths must remain fail-closed.

### Task 3: Local runtime recovery and end-to-end verification

**Files:**
- Modify only if diagnosis identifies a launcher defect: `start-dev.ps1` or `stop-dev.ps1`
- Test: no source change required for a process-state-only recovery

- [ ] **Step 1: Inspect existing process ownership and launcher logs**

Identify the process tree, listener status, and the precise last error without killing unrelated Node or Python processes.

- [ ] **Step 2: Start the scoped backend and Vite processes**

Run: `powershell -ExecutionPolicy Bypass -File .\start-dev.ps1`

Expected: listeners on `127.0.0.1:8000` and `127.0.0.1:5173`, with both health checks returning HTTP 200.

- [ ] **Step 3: Verify the interactive spine**

Authenticate using the existing local administrator account through the browser, run an in-corpus question, confirm retrieved papers, exact evidence spans, citations, and answer status. Do not submit the out-of-corpus mRNA question as a quality pass; verify it reports the corpus limitation rather than inventing evidence.

- [ ] **Step 4: Run final automated checks and preserve runtime hygiene**

Run focused backend tests, frontend production build, and status/health checks. Stop only processes started by this task via `stop-dev.ps1` if the user does not want the local app left running.

## Plan review

- Corpus expansion is sequenced before answer-gate work, as requested.
- The staged promotion prevents a failed network extraction from destroying the current corpus/index.
- The release correction is narrow: it permits only cited, locally validated partial evidence and preserves abstention for unsupported/conflicting answers.
- No repository history is reset or unrelated dirty files are modified.
