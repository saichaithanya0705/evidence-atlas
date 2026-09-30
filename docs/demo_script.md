# Administrator demo script

## Prepare

1. From the repository root, start the local app with `start.bat` and sign in as an administrator at `http://127.0.0.1:5173/login`.
2. Confirm `/health` is healthy and the index manifest lists 29,994 records.
3. If the evaluation artifacts are not already present, run the exact variant and report commands in [evaluation_plan.md](evaluation_plan.md). Confirm all four variants contain 40 query artifacts and that the promoted run ID and checksums match [evaluation_report.md](evaluation_report.md).

## Walkthrough

1. Open the administrator **Evaluations** page. Show the run ID, benchmark/corpus/configuration checksums, all four variants, measured aggregate metrics, and each metric's status and reason.
2. Open a report detail and show that a completed metric has a measured value while unavailable metrics remain `not_run` or `failed` with null values and explanations.
3. Open a per-query diagnostic to show the stored candidate and robustness summary without exposing raw prompts or provider secrets.
4. Open a separate ordinary-user session. Show the public research interpretation, qualitative evidence coverage, exact source spans, and PubMed source links. Confirm there is no Evaluations navigation, report data, trace control, or evaluation API request for this account.
5. Return to the administrator session and expand the audit trail only when demonstrating the linked request trace.

## Repeat and limits

The report commands are repeatable from saved artifacts. Use a new explicit `--run-id` when intentionally producing another immutable evaluation report; an existing run ID cannot be overwritten. Recheck the benchmark checksum and corpus/index invariants before and after a new run. This is a software evaluation demo, not a clinical decision workflow or independent medical adjudication.
