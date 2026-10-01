# Evaluation report eval-20260930-browser-fixes-2628237f352f

- Run ID: `eval-20260930-browser-fixes-2628237f352f`
- Benchmark checksum: `1e50313b8ba20cb92114bf47c73392bc26142c0a2ae6282b82213d74fc1b8d84`
- Corpus checksum: `2628237f352f7cf014fd82b09619771d02eaf17a161261569ebb5e0c57e174f6`
- Configuration checksum: `bbab44cbb109f6542b24954fa1f24bf7cbd5922d3ef353d41e98191d607072f3`
- Variants: `dense_only, hybrid, reranked, agentic`
- Query count: `40`

## Metrics

| Metric | Status | Value | Reason |
|---|---|---:|---|
| agentic.answer_completeness | not_run | n/a | answer payload lacks explicit answered subquestion IDs |
| agentic.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| agentic.citation_precision | completed | 0.36065573770491804 |  |
| agentic.citation_validity | completed | 1.0 |  |
| agentic.filter_accuracy | completed | 1.0 |  |
| agentic.latency_ms | completed | {"count":40,"max":47950.94,"mean":17302.4445,"median":14081.685,"min":7455.2} |  |
| agentic.mrr@10 | completed | 0.7 |  |
| agentic.ndcg@10 | completed | 0.7 |  |
| agentic.precision@10 | completed | 0.07000000000000003 |  |
| agentic.ragas.answer_correctness | not_run | n/a | missing required fields: reference |
| agentic.ragas.answer_relevancy | not_run | n/a | provider credentials or adapter unavailable |
| agentic.ragas.context_entity_recall | not_run | n/a | missing required fields: reference |
| agentic.ragas.context_precision | not_run | n/a | missing required fields: reference |
| agentic.ragas.context_recall | not_run | n/a | missing required fields: reference |
| agentic.ragas.faithfulness | not_run | n/a | provider credentials or adapter unavailable |
| agentic.recall@10 | completed | 0.7 |  |
| agentic.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.14378024753750002}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.007777777769999998,"query_context_coverage":-0.020526071150000002}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.0063636363699999966,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08385843322750001}}}} |  |
| agentic.route_accuracy | completed | 0.75 |  |
| agentic.route_confusion | completed | {"COMPLEX":{"COMPLEX":19,"MODERATE":0,"SIMPLE":0},"MODERATE":{"COMPLEX":0,"MODERATE":11,"SIMPLE":0},"SIMPLE":{"COMPLEX":0,"MODERATE":10,"SIMPLE":0}} |  |
| agentic.span_precision | completed | 1.0 |  |
| agentic.subquestion_coverage | completed | 0.775 |  |
| agentic.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
| dense_only.answer_completeness | not_run | n/a | retrieval-only variant has no answer payload |
| dense_only.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| dense_only.citation_precision | not_run | n/a | no citations were saved |
| dense_only.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| dense_only.filter_accuracy | completed | 1.0 |  |
| dense_only.latency_ms | completed | {"count":40,"max":28847.39,"mean":1958.8267499999997,"median":1260.37,"min":1222.18} |  |
| dense_only.mrr@10 | completed | 0.5958333333333333 |  |
| dense_only.ndcg@10 | completed | 0.6032732438392865 |  |
| dense_only.precision@10 | completed | 0.06250000000000003 |  |
| dense_only.ragas.answer_correctness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.answer_relevancy | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.context_entity_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.context_precision | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.context_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.ragas.faithfulness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| dense_only.recall@10 | completed | 0.625 |  |
| dense_only.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.1305059523825}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.006944444437499997,"query_context_coverage":-0.006856060605}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0027777777775}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.005681818187499997,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08539432788750001}}}} |  |
| dense_only.route_accuracy | not_run | n/a | no saved research plan contains a predicted route |
| dense_only.route_confusion | not_run | n/a | no saved research plan contains a predicted route |
| dense_only.span_precision | not_run | n/a | saved evidence contains no supporting spans to check against returned abstracts |
| dense_only.subquestion_coverage | not_run | n/a | saved plan and coverage history do not contain observed subquestion IDs and statuses |
| dense_only.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
| hybrid.answer_completeness | not_run | n/a | retrieval-only variant has no answer payload |
| hybrid.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| hybrid.citation_precision | not_run | n/a | no citations were saved |
| hybrid.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| hybrid.filter_accuracy | completed | 1.0 |  |
| hybrid.latency_ms | completed | {"count":40,"max":4719.77,"mean":2897.1305,"median":2814.76,"min":2280.49} |  |
| hybrid.mrr@10 | completed | 0.6739583333333333 |  |
| hybrid.ndcg@10 | completed | 0.6861598657589296 |  |
| hybrid.precision@10 | completed | 0.07250000000000004 |  |
| hybrid.ragas.answer_correctness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.answer_relevancy | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.context_entity_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.context_precision | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.context_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.ragas.faithfulness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| hybrid.recall@10 | completed | 0.725 |  |
| hybrid.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.1448423798475}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0080555555475,"query_context_coverage":-0.0027777777775}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08710338272250001}}}} |  |
| hybrid.route_accuracy | not_run | n/a | no saved research plan contains a predicted route |
| hybrid.route_confusion | not_run | n/a | no saved research plan contains a predicted route |
| hybrid.span_precision | not_run | n/a | saved evidence contains no supporting spans to check against returned abstracts |
| hybrid.subquestion_coverage | not_run | n/a | saved plan and coverage history do not contain observed subquestion IDs and statuses |
| hybrid.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
| reranked.answer_completeness | not_run | n/a | retrieval-only variant has no answer payload |
| reranked.attribution_precision | not_run | n/a | saved response has no claim-to-citation attribution verdicts |
| reranked.citation_precision | not_run | n/a | no citations were saved |
| reranked.citation_validity | not_run | n/a | no citations were saved or active-corpus PMID membership could not be loaded |
| reranked.filter_accuracy | completed | 1.0 |  |
| reranked.latency_ms | completed | {"count":40,"max":5264.78,"mean":3567.5099999999998,"median":3503.675,"min":2976.48} |  |
| reranked.mrr@10 | completed | 0.725 |  |
| reranked.ndcg@10 | completed | 0.725 |  |
| reranked.precision@10 | completed | 0.07250000000000004 |  |
| reranked.ragas.answer_correctness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.answer_relevancy | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.context_entity_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.context_precision | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.context_recall | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.ragas.faithfulness | not_run | n/a | retrieval-only variant has no answer-generation sample |
| reranked.recall@10 | completed | 0.725 |  |
| reranked.robustness | completed | {"query_count":40,"scenario_count":7,"scenarios":{"acronym_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.1448423798475}},"conflicting_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"filter_pressure":{"mean_metric_deltas":{"candidate_filter_compliance":-0.4625,"context_precision":0.0,"query_context_coverage":0.0}},"incomplete_evidence":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0080555555475,"query_context_coverage":-0.0126283438775}},"irrelevant_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"misleading_context":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":-0.006590909097499996,"query_context_coverage":0.0}},"noisy_query":{"mean_metric_deltas":{"candidate_filter_compliance":0.0,"context_precision":0.0,"query_context_coverage":-0.08710338272250001}}}} |  |
| reranked.route_accuracy | not_run | n/a | no saved research plan contains a predicted route |
| reranked.route_confusion | not_run | n/a | no saved research plan contains a predicted route |
| reranked.span_precision | not_run | n/a | saved evidence contains no supporting spans to check against returned abstracts |
| reranked.subquestion_coverage | not_run | n/a | saved plan and coverage history do not contain observed subquestion IDs and statuses |
| reranked.supported_claim_rate | not_run | n/a | saved response has no validated claim-level support verdicts |
