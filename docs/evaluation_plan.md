# Evaluation plan

## Benchmark

The frozen benchmark is `data/evaluation/benchmark_v2.json`. It contains 40 distinct queries with expected route, study type, graded PMID judgments, rationales, and PubMed record links. Benchmark construction used web-assisted PubMed source verification: each listed PMID, title, and abstract evidence was checked against its official PubMed record and the local corpus record. This supports source identity and relevance-label traceability; it is not independent medical expert adjudication or a representative PubMed sample.

The dataset declares 29,994 active corpus records. The index manifest records the same total. Corpus and index files are inputs to evaluation and must not be regenerated, resized, or changed during this task.

## Variants and metrics

Run dense-only, hybrid, reranked, and agentic variants over the same 40 entries with top-k 10. The saved-artifact evaluator reports Recall@10, Precision@10, MRR@10, nDCG@10, filter accuracy, latency summaries, citation validity/precision when available, robustness deltas, and failure-category counts. Route, claim, span, attribution, and optional provider-backed RAGAS metrics remain explicitly `not_run` or `failed` when their required independent labels, fields, provider, or dependency are unavailable.

The dense-only, hybrid, and reranked variants measure retrieval only; their missing answer payloads are expected. Answer, span, attribution, and subquestion metrics for those variants remain `not_run` with null values, not zero or a product failure. Every metric is recorded with `completed`, `not_run`, or `failed`. A missing value is null with a reason; it is never converted to zero. The report bundle includes benchmark, corpus, and configuration SHA-256 checksums, per-query JSON, JSON and Markdown summaries, checksums, and a promotion manifest. Only a complete 40-query report with all four variants and verified checksums is eligible for promotion.

## Exact commands

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m evaluation.ablation --benchmark data/evaluation/benchmark_v2.json --variant all --resume --output-dir data/evaluation/variants
.\.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --variants dense_only hybrid reranked agentic --output-dir evaluation/reports
```

The first command executes each variant and writes resumable query artifacts. The second validates those artifacts, calculates aggregate metrics, and promotes a checksum-valid immutable report. Record the exact benchmark checksum, run ID, and metric statuses in [evaluation_report.md](evaluation_report.md). The dashboard and API at `/admin/evaluations` are administrator-only; ordinary-user research responses do not expose evaluation results.

## Limits

This benchmark is small and query-focused. Classical retrieval metrics do not establish clinical correctness, semantic claim support, or general PubMed performance. Variant results reflect the configured local models, indexes, filters, and provider availability for this run. Optional RAGAS values are only reported when the dependency, required references, and provider adapter are available.
