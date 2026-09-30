# Evaluation report

## Run identity

- Run ID: `eval-1e50313b8ba2-58df625f7252`
- Benchmark: `data/evaluation/benchmark_v2.json` (40 queries)
- Benchmark SHA-256: `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`
- Corpus SHA-256: `de14fbebfb00d541670e1fdf7202deddc60fbe5ae98a2fcc2e8881dc739ebc67`
- Configuration SHA-256: `8c66492b4ccd3bcfacda4286ad1d7753d6afb8acabd8441bf4c2ee1235e307d7`
- Variants: `dense_only`, `hybrid`, `reranked`, `agentic`
- Evaluated query artifacts: 40 per variant (160 total)
- Metric statuses: 30 `completed`, 58 `not_run`, 0 `failed`
- Promoted report JSON SHA-256: `80e050dcf30ec75010acf4f439683e050293ff865430a8bbcbc95f5cc8c76c33`
- Promoted report Markdown SHA-256: `34d087975c7735b054a2eecf9aa5c44a16270684727e3e571725a29b2bff6b7c`
- Bundle checksum manifest SHA-256: `235a23900b9936040e7d1c4d87218dda8f4a5d98eb62b84154b392788f124aba`
- Promotion manifest references this run as `latest_run_id` and records report checksum `80e050dcf30ec75010acf4f439683e050293ff865430a8bbcbc95f5cc8c76c33`.

## Measured aggregate results

The following values are copied from the promoted JSON report. Retrieval measures are macro averages over the 40 benchmark queries at k=10. Latency is the saved artifact's per-query elapsed time, summarized in milliseconds.

| Variant | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Filter accuracy | Mean latency ms | Median latency ms | Max latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dense_only | 0.625 | 0.06250000000000003 | 0.5833333333333333 | 0.5940464876785729 | 1.0 | 1636.51075 | 1161.41 | 10686.87 |
| hybrid | 0.725 | 0.07250000000000004 | 0.6744047619047618 | 0.6866065771726197 | 1.0 | 3285.7400000000002 | 3260.435 | 5101.33 |
| reranked | 0.725 | 0.07250000000000004 | 0.7125 | 0.7157732438392864 | 1.0 | 9784.64 | 9968.69 | 11975.35 |
| agentic | 0.7 | 0.07000000000000003 | 0.6875 | 0.6907732438392864 | 1.0 | 32313.974 | 26511.525 | 79779.46 |

Agentic citation validity was `completed` at `1.0`; agentic citation precision was `completed` at `0.2857142857142857`. These counts come from saved citations compared with the active corpus PMID set and benchmark labels. Citation precision was `not_run` for dense-only, hybrid, and reranked because no citations were saved for those variants.

All seven robustness scenarios were scored from saved candidate/context artifacts for each variant. This is deterministic perturbation scoring over saved artifacts; it does not rerun production retrieval or model inference. Each variant also has a completed filter accuracy of `1.0`.

The `dense_only`, `hybrid`, and `reranked` variants are retrieval-only. Their saved artifacts are expected to have `answer: null`; answer-completeness, subquestion-coverage, span-precision, attribution-precision, and supported-claim metrics are therefore `not_run` with null values, not zero and not product failures. The agentic artifacts do contain answers. Their saved status distribution was 8 `SUPPORTED`, 3 `LIMITED`, and 29 `INSUFFICIENT` out of 40 (72.5% `INSUFFICIENT`).

Inference from the saved artifacts: the high `INSUFFICIENT` share appears largely related to conservative PICO/conflict release gates. Most insufficient responses cite missing explicit population, intervention, or outcome fields, or state that no claim passed citation and semantic verification; agentic retrieval still measured Recall@10 of `0.7`. This does not mean retrieval was flawless: the aggregate failure categories include 12 `missing_evidence` and 49 `context_noise` counts. The status distribution describes this run and is not a clinical outcome.

## Not-run metrics and limitations

The 58 `not_run` statuses retain null values and reasons. This includes route and claim-level metrics without independently scored route/reference or validated claim fields, citation checks for variants without saved citations, and six optional RAGAS metrics per variant. The report gives RAGAS metrics the reason `reference answer or configured RAGAS provider is unavailable`. A separate import smoke for `ragas.metrics.collections` failed with `ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'`; RAGAS scores were not inferred or set to zero.

During the agentic run, NVIDIA NIM returned transient 502/503 and internal errors and some synthesis selections failed validation. The workflow retained deterministic evidence-span fallback where available and applied its claim validation. Those provider events are a limitation of this run; they are not a separate measured quality score. Results remain a small, query-focused retrieval evaluation and do not establish clinical correctness or performance on a representative PubMed sample.

Benchmark construction used web-assisted PubMed source verification. The 40 PMID/title records were checked against official PubMed pages and matched to the local corpus; this establishes source traceability, not independent medical adjudication.

Evaluation reports and metrics are visible only to administrators through the UI and API. Ordinary-user research responses and views do not expose this report or its metrics.

## Reproduction commands

Run from the repository root in PowerShell. The first command wrote 160 artifacts (`written: 160`, `skipped: 0`); the second produced the promoted run above.

```powershell
.\.venv\Scripts\python.exe -m evaluation.ablation --benchmark data/evaluation/benchmark_v2.json --variant all --resume --output-dir data/evaluation/variants
.\.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --variants dense_only hybrid reranked agentic --output-dir evaluation/reports
npx -y @mermaid-js/mermaid-cli@11.12.0 -i docs/architecture.mmd -o docs/architecture.svg
```

The report bundle is stored in `evaluation/reports/eval-1e50313b8ba2-58df625f7252/`; its `checksums.json` lists each query artifact hash. The summary Markdown and JSON agree on run ID, checksums, variants, query count, and every metric status/value/reason.
