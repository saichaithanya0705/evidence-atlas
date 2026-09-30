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

Feature commit: `975b80f` (`feat: add comprehensive research evaluation`).

Concerns: the optional RAGAS import smoke remains blocked by the upstream `langchain-community` import path described above. All deterministic evaluation and backend tests pass.

## Review fixes (based on `2c96d15`)

Added strict binding checks before scoring: every saved variant must match the loaded benchmark version and the active corpus file checksum in its `benchmark_version` and `corpus_identity`. Regressions cover both mismatch types failing before manifest promotion and a matching artifact succeeding.

Connected `evaluate_saved_variants` to the robustness helper through an explicit `robustness_runner` callback that must actually rerun/score each changed sample. For each variant and query, the report and query artifact now retain all seven scenario records, including perturbation provenance and per-metric deltas. Aggregate robustness metric values summarize scenario count, query count, and mean deltas. Without the callback, the runner stores `not_run` and explains the missing prerequisite; callback errors are recorded as `failed` with a bounded type-only reason.

The new runner regression tests first failed: both stale-identity fixtures reached report generation instead of being rejected, and the runner did not accept or persist a robustness callback. They pass after the changes. The matching-artifact path also exposed a JSON/Markdown comparison bug for compound metric values after sorted JSON serialization; a regression now verifies consistent canonical display across that round-trip.

Post-review verification: focused Task 8 and runner tests `20 passed`; full backend suite `1090 passed, 1 skipped, 9 warnings`. The warnings remain the FastAPI lifecycle deprecations and local Qdrant advisories noted above. The RAGAS import smoke limitation is unchanged.

## Review fixes (default robustness execution)

The normal saved-artifact runner now supplies a built-in deterministic robustness evaluator when no callback is injected. It measures query/context term coverage, relevance of context PMIDs, and candidate filter compliance from the saved artifact metadata. Each of the seven perturbations is applied to those inputs, then rescored; scenario provenance and computed metric deltas are persisted in the report and per-query artifact. These are artifact-based robustness checks and do not claim a fresh production retrieval or model inference run. An injected callback can still replace the evaluator when a caller has live rerun capability.

Robustness evaluation now fails closed if the baseline or any scenario has no numeric metrics, or if a scenario produces no comparable metric deltas. The runner records that metric as `failed` with a concise reason and null value; it does not publish empty results as `completed`.

TDD evidence for this review: the no-callback runner regression initially failed because no per-query robustness section was written, and the empty-metrics callback incorrectly reported `completed`. After wiring the default evaluator and rejecting empty deltas, the default path persisted all seven scenarios with nonempty deltas and the empty-metrics case reported `failed`. The filter-pressure fixture asserts a computed negative filter-compliance delta.

Verification after this review: focused Task 8 and runner tests `21 passed`; full backend suite `1091 passed, 1 skipped, 9 warnings`.

## Review fix (top-level robustness summary)

The top-level `report.robustness[variant]` summary now derives its status, value, and reason from the same metric record used by `report.metrics[variant.robustness]`. It includes each query's exact robustness payload from the per-query artifact, so scenario provenance and metric deltas agree across the summary and query detail. Failed callback results expose the same failure reason at both levels; completed results no longer coexist with a contradictory `not_run` summary.

TDD evidence: the CLI/default-evaluator regression first failed because top-level robustness was `not_run` while the aggregate metric was `completed`. Added assertions compare the status, summary values, and query payload; the focused Task 8 suite then passed (`21 passed`). Full backend suite passed (`1091 passed, 1 skipped, 9 warnings`).
