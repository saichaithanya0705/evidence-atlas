# Evaluation report eval-1e50313b8ba2-task13-report-integration

- Run ID: `eval-1e50313b8ba2-task13-report-integration`
- Benchmark checksum: `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`
- Corpus checksum: `de14fbebfb00d541670e1fdf7202deddc60fbe5ae98a2fcc2e8881dc739ebc67`
- Configuration checksum: `8c66492b4ccd3bcfacda4286ad1d7753d6afb8acabd8441bf4c2ee1235e307d7`
- Variants: `dense_only, hybrid, reranked, agentic`
- Query count: `40`

## Metrics

| Metric | Status | Value | Reason |
|---|---|---:|---|
| agentic.answer_completeness | not_run | n/a | answer payload lacks explicit answered subquestion IDs |
| agentic.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| agentic.citation_precision | completed | 0.3076923076923077 |  |
| agentic.citation_validity | completed | 1.0 |  |
| agentic.filter_accuracy | completed | 1.0 |  |
| agentic.latency_ms | completed | {"count":40,"max":67866.05,"mean":27670.1095,"median":20347.655,"min":11367.73} |  |
| agentic.mrr@10 | completed | 0.6875 |  |
| agentic.ndcg@10 | completed | 0.6907732438392864 |  |
| agentic.precision@10 | completed | 0.07000000000000003 |  |
| agentic.ragas.answer_correctness | not_run | n/a | missing required fields: reference |
| agentic.ragas.answer_relevancy | not_run | n/a | provider credentials or adapter unavailable |
| agentic.ragas.context_entity_recall | not_run | n/a | missing required fields: reference |
| agentic.ragas.context_precision | not_run | n/a | missing required fields: reference |
| agentic.ragas.context_recall | not_run | n/a | missing required fields: reference |
| agentic.ragas.faithfulness | not_run | n/a | provider credentials or adapter unavailable |
| agentic.recall@10 | completed | 0.7 |  |
| agentic.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14384726385250002}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.007777777769999998,"query_context_coverage":-0.0085518648}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08359959484250001}}}} |  |
| agentic.route_accuracy | completed | 0.75 |  |
| agentic.route_confusion | completed | {"COMPLEX":{"COMPLEX":19,"MODERATE":0,"SIMPLE":0},"MODERATE":{"COMPLEX":0,"MODERATE":11,"SIMPLE":0},"SIMPLE":{"COMPLEX":0,"MODERATE":10,"SIMPLE":0}} |  |
| agentic.span_precision | completed | 1.0 |  |
| agentic.subquestion_coverage | completed | 0.775 |  |
| agentic.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
| dense_only.answer_completeness | not_run | n/a | answer payload lacks explicit answered subquestion IDs |
| dense_only.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| dense_only.citation_precision | not_run | n/a | no citations were saved |
| dense_only.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| dense_only.filter_accuracy | completed | 1.0 |  |
| dense_only.latency_ms | completed | {"count":40,"max":14701.3,"mean":1889.60825,"median":1460.0149999999999,"min":808.52} |  |
| dense_only.mrr@10 | completed | 0.5833333333333333 |  |
| dense_only.ndcg@10 | completed | 0.5940464876785729 |  |
| dense_only.precision@10 | completed | 0.06250000000000003 |  |
| dense_only.ragas.answer_correctness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.answer_relevancy | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.context_entity_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.context_precision | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.context_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.faithfulness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.recall@10 | completed | 0.625 |  |
| dense_only.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.132061063935}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.006944444437499997,"query_context_coverage":-0.009631410255}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0027777777775}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08567210566500001}}}} |  |
| dense_only.route_accuracy | not_run | n/a | no saved research plan contains a predicted route |
| dense_only.route_confusion | not_run | n/a | no saved research plan contains a predicted route |
| dense_only.span_precision | not_run | n/a | saved evidence contains no supporting spans to check against returned abstracts |
| dense_only.subquestion_coverage | not_run | n/a | saved plan and coverage history do not contain required subquestion IDs and statuses |
| dense_only.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
| hybrid.answer_completeness | not_run | n/a | answer payload lacks explicit answered subquestion IDs |
| hybrid.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| hybrid.citation_precision | not_run | n/a | no citations were saved |
| hybrid.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| hybrid.filter_accuracy | completed | 1.0 |  |
| hybrid.latency_ms | completed | {"count":40,"max":5931.95,"mean":3635.9837500000003,"median":3577.95,"min":2041.15} |  |
| hybrid.mrr@10 | completed | 0.6744047619047618 |  |
| hybrid.ndcg@10 | completed | 0.6866065771726197 |  |
| hybrid.precision@10 | completed | 0.07250000000000004 |  |
| hybrid.ragas.answer_correctness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.answer_relevancy | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.context_entity_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.context_precision | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.context_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.faithfulness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.recall@10 | completed | 0.725 |  |
| hybrid.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14487394550500005}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0080555555475,"query_context_coverage":-0.00505050505}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08432560494500001}}}} |  |
| hybrid.route_accuracy | not_run | n/a | no saved research plan contains a predicted route |
| hybrid.route_confusion | not_run | n/a | no saved research plan contains a predicted route |
| hybrid.span_precision | not_run | n/a | saved evidence contains no supporting spans to check against returned abstracts |
| hybrid.subquestion_coverage | not_run | n/a | saved plan and coverage history do not contain required subquestion IDs and statuses |
| hybrid.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
| reranked.answer_completeness | not_run | n/a | answer payload lacks explicit answered subquestion IDs |
| reranked.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| reranked.citation_precision | not_run | n/a | no citations were saved |
| reranked.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| reranked.filter_accuracy | completed | 1.0 |  |
| reranked.latency_ms | completed | {"count":40,"max":15392.1,"mean":10040.19175,"median":10031.59,"min":6538.19} |  |
| reranked.mrr@10 | completed | 0.7125 |  |
| reranked.ndcg@10 | completed | 0.7157732438392864 |  |
| reranked.precision@10 | completed | 0.07250000000000004 |  |
| reranked.ragas.answer_correctness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.answer_relevancy | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.context_entity_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.context_precision | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.context_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.faithfulness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.recall@10 | completed | 0.725 |  |
| reranked.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14487394550500005}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0080555555475,"query_context_coverage":-0.0116768648}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08432560494500001}}}} |  |
| reranked.route_accuracy | not_run | n/a | no saved research plan contains a predicted route |
| reranked.route_confusion | not_run | n/a | no saved research plan contains a predicted route |
| reranked.span_precision | not_run | n/a | saved evidence contains no supporting spans to check against returned abstracts |
| reranked.subquestion_coverage | not_run | n/a | saved plan and coverage history do not contain required subquestion IDs and statuses |
| reranked.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
