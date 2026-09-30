# Test readiness

This file records the current verification commands for the local research prototype. Task 11 verification on 2026-09-30 completed with 1,106 passed, 2 skipped, and 9 warnings in 147.60 seconds. The warnings were FastAPI lifecycle deprecations and existing embedded-Qdrant advisories. Focused Task 11 checks passed (13 tests); the evaluation-runner suite passed (5 tests). See the Task 11 report for the exact benchmark and environment run.

## Backend

Run the focused artifact/evaluation checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_setup_and_evaluation.py tests/unit/test_conversational_research_evaluation.py -q
```

Run the complete backend suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The frozen evaluation benchmark is `data/evaluation/benchmark_v2.json` (40 queries). Its labels use web-assisted PubMed source verification. The current index manifest declares 29,994 corpus rows and points. The dense-only, hybrid, and reranked variants are retrieval-only, so null answers and `not_run` answer metrics are expected, not failures. Evaluation metrics and reports are available only to administrators through the evaluation dashboard and API; ordinary-user research projections do not include them.

## Evaluation reproduction

From the repository root, first generate comparable variant artifacts, then score and promote only a complete checksum-valid report:

```powershell
.\.venv\Scripts\python.exe -m evaluation.ablation --benchmark data/evaluation/benchmark_v2.json --variant all --resume --output-dir data/evaluation/variants
.\.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --variants dense_only hybrid reranked agentic --output-dir evaluation/reports
```

Optional provider-backed metrics can remain `not_run` or `failed` with a reason when the dependency, reference fields, or provider is unavailable. They are never represented as zero for missing data. See [the evaluation plan](docs/evaluation_plan.md) and [the recorded report](docs/evaluation_report.md).

## Frontend

From `frontend/`, run the browser checks appropriate to the change and build the UI:

```powershell
npm run test:ui-conversations
npm run test:ui-evaluation
npm run test:ui-accounts
npm run build
```

On the recorded Windows environment, Node.js 20.18.0 is below the Vite minimum of 20.19.0; successful prior runs emitted that compatibility warning. Live Qdrant storage checks require exclusive access to the embedded store. See [the administrator demo](docs/demo_script.md) for a reproducible presentation flow and role-boundary check.
