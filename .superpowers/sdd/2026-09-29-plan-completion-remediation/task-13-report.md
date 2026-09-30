# Task 13 — final report integration fixes

Date: 2026-09-30
Base: `ec331be53a065c6ad5ae6f6cd8b0817dbba729e3`
Commit: `fix: complete evaluation report integration`

## Changes

1. Filter accuracy now checks returned candidate study type and any requested year range against candidate metadata, and includes each candidate's `filter_satisfied` flag. Missing metadata required for a check yields `not_run` with a query-specific reason. Regression fixtures cover wrong study type, wrong year, a false compliance flag, and missing candidate metadata.
2. Saved agentic artifacts now feed route accuracy/confusion, subquestion coverage, explicit answer completeness when answered-subquestion IDs exist, exact span precision, citations, and available claim verdict metrics. Metrics are completed only when prerequisites are present; otherwise they remain `not_run` with specific reasons. RAGAS is injectable in the evaluator and configurable from the CLI with `--ragas-provider module:factory`; imports remain lazy. No reference answers or claim verdicts were added. Retrieval-only answer metrics remain `not_run` because those variants intentionally save `answer: null`.
3. Report promotion now requires complete artifacts for all four variants. `--allow-subset` is a separate diagnostic-only opt-in. The ordinary CLI still requires the complete four-name variant list, and direct promotion fails closed if any corresponding artifact set is absent.
4. The admin projection allowlist now retains `query_context_coverage`, `context_precision`, and `candidate_filter_compliance` in aggregate robustness deltas and per-query robustness deltas.

The promoted report and per-query bundle also store answer-status distribution data. The demo script now budgets eight minutes for the walkthrough and two minutes for Q&A.

## TDD and verification

- Initial regression run was RED: three new runner tests failed, including a reproduction where a dense-only artifact set did not raise before promotion (`DID NOT RAISE ValueError`). The two filtering cases first stopped at the missing `allow_subset` API; after that API and candidate scoring landed, hostile type/year/compliance and missing-metadata assertions passed. The original route/coverage/claim/RAGAS code emitted hardcoded `not_run`, and the original admin metric set omitted all three robustness names; the new injected-evaluator and generated-shape API regressions now assert those outputs directly.
- The first full suite after report regeneration found one documentation mismatch: the report stored dense-only median latency as `1460.0149999999999`, while the prose rounded it. The doc now uses the exact generated value, and the promoted-report checksum/doc test passes.
- Focused evaluator, metrics, and admin tests: 53 passed, 1 skipped. Promoted report validation against docs/checksums passed.
- Full backend: 1,115 passed, 2 skipped, 9 warnings.
- Frontend production build passed with the existing Node 20.18.0 versus Vite's 20.19+ warning. `test:ui-evaluation` passed with the Vite QA server running.
- `git diff --check` passed. The processed corpus SHA-256 still matches the report/index manifest (`de14fbebfb00d541670e1fdf7202deddc60fbe5ae98a2fcc2e8881dc739ebc67`), and the manifest continues to report 29,994 records.

## Regenerated report

- Run: `eval-1e50313b8ba2-task13-final`
- Benchmark: 40 queries; four variants; 160 regenerated artifacts.
- Metric states: 34 `completed`, 54 `not_run`, 0 `failed`.
- Answer status counts: 10 `SUPPORTED`, 3 `LIMITED`, 27 `INSUFFICIENT`.
- Report JSON SHA-256: `b20c351eb0d8dbbc06b26b63b364931bb723c6eb966ca868e173444908924aae`.
- Report Markdown SHA-256: `1d774d1553a4c6f3eeeb59a1f30e61286a73b0180bcd5a5e8211bedb5ed5322b`.

The `INSUFFICIENT` distribution is an evaluation observation, not a clinical outcome. Conservative abstention when evidence is conflicting or no supported claim survives validation follows the agent design. The three retrieval-only variants' `answer: null` values are expected by their contract. RAGAS faithfulness/relevancy stayed `not_run` without a configured provider; reference-dependent RAGAS metrics stayed `not_run` because the frozen benchmark has no reference answers.
