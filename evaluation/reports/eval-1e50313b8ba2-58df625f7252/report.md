# Evaluation report eval-1e50313b8ba2-58df625f7252

- Run ID: `eval-1e50313b8ba2-58df625f7252`
- Benchmark checksum: `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`
- Corpus checksum: `de14fbebfb00d541670e1fdf7202deddc60fbe5ae98a2fcc2e8881dc739ebc67`
- Configuration checksum: `8c66492b4ccd3bcfacda4286ad1d7753d6afb8acabd8441bf4c2ee1235e307d7`
- Variants: `dense_only, hybrid, reranked, agentic`
- Query count: `40`

## Metrics

| Metric | Status | Value | Reason |
|---|---|---:|---|
| agentic.answer_completeness | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| agentic.attribution_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| agentic.citation_precision | completed | 0.2857142857142857 |  |
| agentic.citation_validity | completed | 1.0 |  |
| agentic.filter_accuracy | completed | 1.0 |  |
| agentic.latency_ms | completed | {"count":40,"max":79779.46,"mean":32313.974,"median":26511.525,"min":14501.6} |  |
| agentic.mrr@10 | completed | 0.6875 |  |
| agentic.ndcg@10 | completed | 0.6907732438392864 |  |
| agentic.precision@10 | completed | 0.07000000000000003 |  |
| agentic.ragas.answer_correctness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| agentic.ragas.answer_relevancy | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| agentic.ragas.context_entity_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| agentic.ragas.context_precision | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| agentic.ragas.context_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| agentic.ragas.faithfulness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| agentic.recall@10 | completed | 0.7 |  |
| agentic.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14384726385250002}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.007777777769999998,"query_context_coverage":-0.0085518648}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08359959484250001}}}} |  |
| agentic.route_accuracy | not_run | n/a | saved variant artifacts do not include an independently scored predicted route |
| agentic.route_confusion | not_run | n/a | saved variant artifacts do not include predicted routes |
| agentic.span_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| agentic.subquestion_coverage | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| agentic.supported_claim_rate | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| dense_only.answer_completeness | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| dense_only.attribution_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| dense_only.citation_precision | not_run | n/a | no citations were saved |
| dense_only.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| dense_only.filter_accuracy | completed | 1.0 |  |
| dense_only.latency_ms | completed | {"count":40,"max":10686.87,"mean":1636.51075,"median":1161.41,"min":797.3} |  |
| dense_only.mrr@10 | completed | 0.5833333333333333 |  |
| dense_only.ndcg@10 | completed | 0.5940464876785729 |  |
| dense_only.precision@10 | completed | 0.06250000000000003 |  |
| dense_only.ragas.answer_correctness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| dense_only.ragas.answer_relevancy | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| dense_only.ragas.context_entity_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| dense_only.ragas.context_precision | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| dense_only.ragas.context_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| dense_only.ragas.faithfulness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| dense_only.recall@10 | completed | 0.625 |  |
| dense_only.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.132061063935}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.006944444437499997,"query_context_coverage":-0.009631410255}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0027777777775}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08567210566500001}}}} |  |
| dense_only.route_accuracy | not_run | n/a | saved variant artifacts do not include an independently scored predicted route |
| dense_only.route_confusion | not_run | n/a | saved variant artifacts do not include predicted routes |
| dense_only.span_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| dense_only.subquestion_coverage | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| dense_only.supported_claim_rate | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| hybrid.answer_completeness | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| hybrid.attribution_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| hybrid.citation_precision | not_run | n/a | no citations were saved |
| hybrid.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| hybrid.filter_accuracy | completed | 1.0 |  |
| hybrid.latency_ms | completed | {"count":40,"max":5101.33,"mean":3285.7400000000002,"median":3260.435,"min":2307.41} |  |
| hybrid.mrr@10 | completed | 0.6744047619047618 |  |
| hybrid.ndcg@10 | completed | 0.6866065771726197 |  |
| hybrid.precision@10 | completed | 0.07250000000000004 |  |
| hybrid.ragas.answer_correctness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| hybrid.ragas.answer_relevancy | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| hybrid.ragas.context_entity_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| hybrid.ragas.context_precision | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| hybrid.ragas.context_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| hybrid.ragas.faithfulness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| hybrid.recall@10 | completed | 0.725 |  |
| hybrid.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14487394550500005}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0080555555475,"query_context_coverage":-0.00505050505}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08432560494500001}}}} |  |
| hybrid.route_accuracy | not_run | n/a | saved variant artifacts do not include an independently scored predicted route |
| hybrid.route_confusion | not_run | n/a | saved variant artifacts do not include predicted routes |
| hybrid.span_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| hybrid.subquestion_coverage | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| hybrid.supported_claim_rate | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| reranked.answer_completeness | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| reranked.attribution_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| reranked.citation_precision | not_run | n/a | no citations were saved |
| reranked.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| reranked.filter_accuracy | completed | 1.0 |  |
| reranked.latency_ms | completed | {"count":40,"max":11975.35,"mean":9784.64,"median":9968.69,"min":5965.12} |  |
| reranked.mrr@10 | completed | 0.7125 |  |
| reranked.ndcg@10 | completed | 0.7157732438392864 |  |
| reranked.precision@10 | completed | 0.07250000000000004 |  |
| reranked.ragas.answer_correctness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| reranked.ragas.answer_relevancy | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| reranked.ragas.context_entity_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| reranked.ragas.context_precision | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| reranked.ragas.context_recall | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| reranked.ragas.faithfulness | not_run | n/a | reference answer or configured RAGAS provider is unavailable |
| reranked.recall@10 | completed | 0.725 |  |
| reranked.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14487394550500005}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0080555555475,"query_context_coverage":-0.0116768648}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08432560494500001}}}} |  |
| reranked.route_accuracy | not_run | n/a | saved variant artifacts do not include an independently scored predicted route |
| reranked.route_confusion | not_run | n/a | saved variant artifacts do not include predicted routes |
| reranked.span_precision | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| reranked.subquestion_coverage | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
| reranked.supported_claim_rate | not_run | n/a | saved artifacts do not contain the required validated reference or claim-level fields |
