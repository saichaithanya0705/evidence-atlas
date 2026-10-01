# Evaluation report

## Latest verified run

- Run ID: `eval-20261001-live-latency`
- Benchmark SHA-256: `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`
- Run corpus SHA-256: `2628237f352f7cf014fd82b09619771d02eaf17a161261569ebb5e0c57e174f6`
- Configuration SHA-256: `2d2bbe87c77b9a1fccdcefff9dfffc02528865da856bdf9b5916eca08c0697ec`
- Pipeline source SHA-256: `8b44d66b9285653c08c0cc91ea7f324ed6185ce3b9754fb5b11b87932e75d019`
- Report JSON SHA-256: `92be809b96cee7bebc0523fc29a904379b08cc14806d3fd93de92304d397eaa0`

The promotion manifest selects this immutable run. Historical reports remain available in the administrator evaluation dashboard. Each of all four variants evaluated all 40 frozen benchmark questions: 160 fresh artifacts, zero resumed artifacts. This restored local corpus contains 29,939 abstracts; the benchmark's original corpus had 29,994. The report identifies the corpus actually used.

## Measured aggregate results

These macro averages use k=10 and the frozen PMID judgments. Latencies are per-query elapsed milliseconds including live inference for agentic answers; the first retrieval includes cold loading.

| Variant | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Filter accuracy | Mean latency ms | Median latency ms | Max latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dense_only | 0.625 | 0.06250000000000003 | 0.5958333333333333 | 0.6032732438392865 | 1.0 | 1602.96075 | 1255.54 | 15112.74 |
| hybrid | 0.725 | 0.07250000000000004 | 0.6739583333333333 | 0.6861598657589296 | 1.0 | 2737.8565 | 2715.365 | 4233.37 |
| reranked | 0.725 | 0.07250000000000004 | 0.725 | 0.725 | 1.0 | 3433.4075 | 3411.605 | 5465.45 |
| agentic | 0.725 | 0.07250000000000004 | 0.725 | 0.725 | 1.0 | 15418.760750000001 | 15065.465 | 25810.87 |

Agentic answers: {"INSUFFICIENT": 3, "LIMITED": 12, "SUPPORTED": 25}. Citation validity and exact-span precision are both 1.0; citation precision against frozen PMID judgments is 0.2978723404255319. Route accuracy is 0.75 and subquestion coverage is 0.76875. The runner supplies the expected route as a minimum floor, so route accuracy does not measure unconstrained initial routing.

Compared with `eval-20260930-browser-fixes-2628237f352f`, supported answers rose from 9 to 25, limited answers from 2 to 12, and insufficient answers fell from 29 to 3. Recall rose from 0.7 to 0.725; mean agentic latency fell from 17302.4445 to 15418.760750000001 ms and maximum latency from 47950.94 to 25810.87 ms. Median latency rose from 14081.685 to 15065.465 ms during a provider-overload period. Citation precision fell from 0.36065573770491804 to 0.2978723404255319, and coverage fell slightly from 0.775 to 0.76875. More released evidence therefore does not prove a general increase in medical correctness or relevance. Source-grounded adjudication of answer relevance remains necessary.

## Execution and limitations

Metric records: 34 completed, 54 not_run, 0 failed. Completed means the calculation ran, not that answers passed. RAGAS has no configured evaluator or reference answers; answer completeness and claim attribution lack required saved fields. Missing metrics retain null values and explicit reasons. No references or scores were invented.

Seven robustness scenarios use deterministic perturbations of saved artifacts. They do not rerun production retrieval or model inference. Browser guardrail checks are recorded separately in the local performance evidence. NVIDIA NIM returned 500/503 overload errors, malformed selections and timeouts. Citation and semantic validation retained fail-closed behavior. Provider deadlines bound waiting; they do not guarantee an end-to-end maximum because retrieval, local inference and SDK phases take additional time.

Benchmark construction previously used web-assisted PubMed source verification. This run reused its frozen judgments without independent clinical adjudication. These questions and the dated local corpus do not establish representative PubMed coverage or clinical accuracy. PMID membership and exact source quotations also do not alone establish semantic correctness.

## Reproduction and verification

```powershell
.venv\Scripts\python.exe -m evaluation.ablation --benchmark data/evaluation/benchmark_v2.json --variant all --output-dir output/live-performance-2026-09-30/variants
.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --artifacts-dir output/live-performance-2026-09-30/variants --reports-dir evaluation/reports --run-id ('eval-recheck-' + (Get-Date -Format yyyyMMdd-HHmmss))
```

The published bundle is `evaluation/reports/eval-20261001-live-latency/`; `checksums.json` covers all 40 query summaries and both report files. The source checksum is part of configuration identity, so changed code invalidates resumed artifacts. Full regression, live call traces, administrator dashboard comparison and browser screenshots are recorded in `output/live-performance-2026-09-30/REPORT.md`. The ignored local evidence is not required in a fresh clone. The previous immutable report remains available for comparison.
