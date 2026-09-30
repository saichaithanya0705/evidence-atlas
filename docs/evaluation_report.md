# Evaluation report

## Run identity

- Run ID: `eval-1e50313b8ba2-task13-final`
- Benchmark: `data/evaluation/benchmark_v2.json` (40 queries)
- Benchmark SHA-256: `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`
- Corpus SHA-256: `de14fbebfb00d541670e1fdf7202deddc60fbe5ae98a2fcc2e8881dc739ebc67`
- Configuration SHA-256: `8c66492b4ccd3bcfacda4286ad1d7753d6afb8acabd8441bf4c2ee1235e307d7`
- Variants: `dense_only`, `hybrid`, `reranked`, `agentic`
- Evaluated query artifacts: 40 per variant (160 total)
- Metric statuses: 34 `completed`, 54 `not_run`, 0 `failed`
- Promoted report JSON SHA-256: `b20c351eb0d8dbbc06b26b63b364931bb723c6eb966ca868e173444908924aae`
- Promoted report Markdown SHA-256: `1d774d1553a4c6f3eeeb59a1f30e61286a73b0180bcd5a5e8211bedb5ed5322b`
- `checksums.json` SHA-256: `a57202a1ddcd5095b293f85fcd08c21657f9605189da056cd79625a5726da786`
- Promotion manifest `checksums_checksum`: `2c0661f249a12763720a4927254a52c4c0fa2d6d93c2b4bbc6ecfc4dcced49a5`
- The promotion manifest points `latest_run_id` at this run and records report checksum `b20c351eb0d8dbbc06b26b63b364931bb723c6eb966ca868e173444908924aae`.

## Measured aggregate results

The following values are copied from the promoted JSON report. Retrieval measures are macro averages over the 40 benchmark queries at k=10. Latency is the saved artifact's per-query elapsed time, summarized in milliseconds.

| Variant | Recall@10 | Precision@10 | MRR@10 | nDCG@10 | Filter accuracy | Mean latency ms | Median latency ms | Max latency ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dense_only | 0.625 | 0.06250000000000003 | 0.5833333333333333 | 0.5940464876785729 | 1.0 | 1889.60825 | 1460.0149999999999 | 14701.3 |
| hybrid | 0.725 | 0.07250000000000004 | 0.6744047619047618 | 0.6866065771726197 | 1.0 | 3635.9837500000003 | 3577.95 | 5931.95 |
| reranked | 0.725 | 0.07250000000000004 | 0.7125 | 0.7157732438392864 | 1.0 | 10040.19175 | 10031.59 | 15392.1 |
| agentic | 0.7 | 0.07000000000000003 | 0.6875 | 0.6907732438392864 | 1.0 | 27670.1095 | 20347.655 | 67866.05 |

Agentic citation validity was `completed` at `1.0`; citation precision was `completed` at `0.3076923076923077`. These scores use the saved citations, active-corpus PMID set, and benchmark relevance labels. Citation checks were `not_run` for dense-only, hybrid, and reranked because those retrieval-only artifacts contain no answers or citations.

The regenerated filter accuracy is computed from returned candidate study type/year metadata and each candidate's `filter_satisfied` value. It was `completed` at `1.0` for each variant. The agentic route accuracy was `0.75`; its confusion counts were 19 COMPLEX predicted as COMPLEX, 11 MODERATE predicted as MODERATE, and 10 SIMPLE predicted as MODERATE. Agentic subquestion coverage was `0.775` and exact-span precision was `1.0`. Answer completeness, claim attribution precision, and supported-claim rate remain `not_run` because the artifacts contain no explicit answered-subquestion IDs or validated claim-level verdicts.

All seven robustness scenarios were scored from saved candidate/context artifacts for each variant. This is deterministic perturbation scoring over saved artifacts; it does not rerun production retrieval or model inference. Each variant also has a completed filter accuracy of `1.0`.

The `dense_only`, `hybrid`, and `reranked` variants are retrieval-only. Their saved artifacts are expected to have `answer: null`; answer-generation metrics are therefore `not_run` with null values, not zero and not product failures. The regenerated agentic status distribution is 10 `SUPPORTED`, 3 `LIMITED`, and 27 `INSUFFICIENT` out of 40 (67.5% `INSUFFICIENT`). This distribution is embedded in the promoted JSON report and can also be recomputed from the per-query `answer_status` fields.

Inference from the saved artifacts: the `INSUFFICIENT` responses largely reflect conservative PICO and evidence-release gates. The system abstains when no safe claim passes validation or evidence conflict remains unresolved. That behavior follows the agent design: conflicts must be exposed rather than averaged into a conclusion. The status distribution is not a clinical outcome. Agentic retrieval still measured Recall@10 of `0.7`; failure categories included 12 `missing_evidence` and 49 `context_noise` counts.

The recorded agentic route is the final route in each saved research plan. Benchmark execution supplies the expected route as a minimum complexity floor, so the route score does not represent an unconstrained initial-router classification measurement.

## Not-run metrics and limitations

The 54 `not_run` statuses retain null values and specific reasons. Dense-only, hybrid, and reranked have no answer sample for generation metrics. Agentic faithfulness and answer relevancy lacked a configured RAGAS provider; reference-dependent RAGAS metrics (`context_precision`, `context_recall`, `context_entity_recall`, and `answer_correctness`) lacked reference answers in the frozen benchmark. No reference answers were invented. RAGAS scores were not inferred or set to zero.

During the agentic run, NVIDIA NIM returned transient 502/503 and internal errors and some synthesis selections failed validation. The workflow retained deterministic evidence-span fallback where available and applied its claim validation. Those provider events are a limitation of this run; they are not a separate measured quality score. Results remain a small, query-focused retrieval evaluation and do not establish clinical correctness or performance on a representative PubMed sample.

Benchmark construction used web-assisted PubMed source verification. The 40 PMID/title records were checked against official PubMed pages and matched to the local corpus; this establishes source traceability, not independent medical adjudication.

Evaluation reports and metrics are visible only to administrators through the UI and API. Ordinary-user research responses and views do not expose this report or its metrics.

## Reproduction commands

Run from the repository root in PowerShell. The first command wrote 160 artifacts (`written: 160`, `skipped: 0`); the second produced the promoted run above.

```powershell
.\.venv\Scripts\python.exe -m evaluation.ablation --benchmark data/evaluation/benchmark_v2.json --variant all --resume --output-dir data/evaluation/variants
.\.venv\Scripts\python.exe -m evaluation.run_evaluation --benchmark data/evaluation/benchmark_v2.json --variants dense_only hybrid reranked agentic --output-dir evaluation/reports --run-id eval-1e50313b8ba2-task13-final
npx -y @mermaid-js/mermaid-cli@11.12.0 -i docs/architecture.mmd -o docs/architecture.svg
```

The report bundle is stored in `evaluation/reports/eval-1e50313b8ba2-task13-final/`; its `checksums.json` lists each query artifact hash. The summary Markdown and JSON agree on run ID, checksums, variants, query count, and every metric status/value/reason.
