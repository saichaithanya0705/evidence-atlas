# Task 8 implementation report

## Delivered

Implemented deterministic evaluation metrics, optional RAGAS collections scoring, privacy-conscious failure diagnostics, seven reproducible robustness perturbations, immutable report publication, and the saved-variant evaluation CLI. Evaluation output remains in `evaluation/reports/`; no public application response fields or routes were added.

The optional dependency is pinned exactly as `ragas==0.4.3`. Core metrics and report validation have no RAGAS dependency. `RagasEvaluator` imports only from `ragas.metrics.collections`, checks each scorer's required fields, requires a caller-supplied provider adapter, isolates scorer failures, and records missing dependency/provider/reference states as `not_run` with reasons. Provider exceptions are `failed` with a bounded reason. No RAGAS failure is converted into a numeric zero.

## Deterministic metric definitions

- Recall@k is the unique retrieved relevant PMID count within k divided by the number of relevant PMIDs.
- Precision@k is the unique retrieved relevant PMID count within k divided by the requested k, even when fewer than k documents were returned.
- MRR@k is the reciprocal one-based rank of the first relevant result, or zero when no relevant result appears within k.
- nDCG@k uses graded relevance as a linear gain, discounted by `log2(rank + 1)`, and normalized by the ideal ordering.
- Route confusion has rows for expected routes and columns for predicted routes. Route accuracy excludes unlabeled expected routes.
- Filter accuracy is exact per-filter equality averaged across expected filters. Missing expected filters are undefined.
- Subquestion coverage and answer completeness are the covered/answered required-ID fraction.
- Citation validity and citation precision are valid-citation and benchmark-relevant-citation fractions, respectively.
- Span precision, attribution precision, and supported-claim rate are validated spans, correct attributions, and supported material claims divided by their corresponding totals.
- Latency summaries contain count, min, median, arithmetic mean, and max in milliseconds.
- Failure diagnostics count only explicit categories: retriever miss, context noise, missing evidence, extraction miss, unsupported generation, citation mismatch, and incomplete answer.

Zero-denominator semantics are explicit: empty relevance labels make Recall@k undefined (`None`); empty rankings yield zero Precision@k, MRR@k, and nDCG@k when references exist. Empty citation, span, attribution, claim, or required-subquestion denominators are undefined (`None`); empty latency inputs have count zero and null distribution values. The frozen benchmark requires nonempty relevance references. Report metrics must use `completed`, `not_run`, or `failed`; completed metrics require a value and no reason, while non-completed metrics require a concise reason and null value.

## RAGAS result

`pip install -r requirements-evaluation.txt` installed RAGAS 0.4.3. The requested import smoke command did not pass. Importing the requested classes fails before reaching `ragas.metrics.collections` because RAGAS imports `langchain_community.chat_models.vertexai`, which is absent in the installed `langchain-community` package (`ModuleNotFoundError`). Installing `langchain-google-vertexai` did not resolve that module path. This optional integration is therefore reported as unavailable; deterministic evaluation remains usable. The evaluator represents this import failure as `not_run` with the exception reason.

The RAGAS install temporarily changed the local venv's OpenAI package to 1.109.1, which caused two unrelated NIM transport tests to fail because the project uses `httpx2.Client`. The pre-existing OpenAI 3.19.2 package was restored in the venv, and both NIM tests passed afterward. No dependency changes were made to the core `requirements.txt`.

## TDD and verification

Tests were written before production implementation. The first focused run was RED: all 14 tests failed because the Task 8 modules did not exist. Implementation brought those tests GREEN. Additional tests were added for all diagnostic categories, scorer-specific required-field validation, and preserving the prior manifest after an interrupted later run; the final focused suite passed.

Commands and results:

- Focused Task 8 tests: `16 passed`.
- Existing evaluation/benchmark/variant/setup tests: `88 passed` before the last added focused cases.
- Full backend suite after restoring the original OpenAI client: `1086 passed, 1 skipped, 9 warnings`.
- The warnings are existing FastAPI lifecycle deprecations and local Qdrant large-collection/payload-index advisories.
- `git diff --check`: passed.
- RAGAS collection import smoke: failed as documented above.

## Report promotion guarantees

Each report run is written to a hidden staging directory. JSON, Markdown, query artifacts, and checksum metadata are written via temporary files and atomic replacement. The staged report and query checksums are verified, and Markdown is checked against JSON for run ID, benchmark/corpus/configuration checksums, variants, query count, and every metric's status/value/reason. Only after complete validation is the run copied into its immutable run directory and verified again. The manifest is then replaced atomically and becomes the sole latest-run promotion point. A validation or pre-promotion interruption leaves the previous manifest unchanged; a partial run is never promoted. Existing run IDs are rejected.

## Self-review and scope

The saved-artifact runner refuses partial variants and refuses to publish when no complete variant exists. It computes classical retrieval, filter, latency, and available citation metrics from saved data. It reports route scoring, claim/span/attribution metrics, RAGAS metrics, and robustness reruns as `not_run` when the saved artifacts lack independent labels, provider credentials, or perturbed retrieval results. It does not fabricate missing references, zero-valued scores, or successful provider states. Claim diagnostics persist bounded categories and concise reasons only; prompt and hidden reasoning fields are ignored.

The runner records aggregate diagnostics alongside per-query diagnostic artifacts. The report store enforces flat query artifact names and validates run IDs. No changes were made to `.env`, the active corpus, vector index, or public API models.

Feature commit: recorded after commit.

Concerns: the optional RAGAS import smoke remains blocked by the upstream `langchain-community` import path described above. All deterministic evaluation and backend tests pass.
