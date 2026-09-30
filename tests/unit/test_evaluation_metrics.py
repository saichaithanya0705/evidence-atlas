from __future__ import annotations

import math

import pytest


def test_rank_metrics_use_binary_relevance_and_fixed_k_denominator():
    from evaluation.metrics import recall_at_k, precision_at_k, reciprocal_rank, ndcg_at_k

    ranking = ["a", "x", "b", "c"]
    relevance = {"a": 3, "b": 1, "c": 2}
    assert recall_at_k(ranking, relevance, 3) == pytest.approx(2 / 3)
    assert precision_at_k(ranking, relevance, 3) == pytest.approx(2 / 3)
    assert reciprocal_rank(ranking, relevance, 3) == 1.0
    ideal = 3 + 2 / math.log2(3) + 1 / math.log2(4)
    actual = 3 + 1 / math.log2(4)
    assert ndcg_at_k(ranking, relevance, 3) == pytest.approx(actual / ideal)


def test_rank_metrics_define_empty_reference_and_empty_ranking_behavior():
    from evaluation.metrics import recall_at_k, precision_at_k, reciprocal_rank, ndcg_at_k

    assert recall_at_k([], {}, 5) is None
    assert precision_at_k([], {"a": 1}, 5) == 0
    assert reciprocal_rank([], {"a": 1}, 5) == 0
    assert ndcg_at_k([], {"a": 1}, 5) == 0


def test_route_confusion_and_accuracy_ignore_unlabeled_rows():
    from evaluation.metrics import route_confusion, route_accuracy

    expected = ["SIMPLE", "COMPLEX", None]
    predicted = ["SIMPLE", "MODERATE", "SIMPLE"]
    assert route_confusion(expected, predicted) == {
        "SIMPLE": {"SIMPLE": 1, "MODERATE": 0, "COMPLEX": 0},
        "MODERATE": {"SIMPLE": 0, "MODERATE": 0, "COMPLEX": 0},
        "COMPLEX": {"SIMPLE": 0, "MODERATE": 1, "COMPLEX": 0},
    }
    assert route_accuracy(expected, predicted) == 0.5


def test_filter_accuracy_and_subquestion_coverage_are_explicit_for_empty_inputs():
    from evaluation.metrics import filter_accuracy, subquestion_coverage, answer_completeness

    assert filter_accuracy({"year": 2020, "study_type": "trial"}, {"year": 2020, "study_type": "cohort"}) == 0.5
    assert filter_accuracy({}, {}) is None
    assert subquestion_coverage(["a", "b"], ["a"]) == 0.5
    assert answer_completeness(["a", "b"], ["a"]) == 0.5
    assert subquestion_coverage([], []) is None


def test_citation_span_attribution_and_grounding_metrics_use_validated_counts():
    from evaluation.metrics import citation_validity, citation_precision, span_precision, attribution_precision, supported_claim_rate

    assert citation_validity(["1", "bad"], {"1", "2"}) == 0.5
    assert citation_precision(["1", "1", "bad"], {"1"}) == pytest.approx(2 / 3)
    assert span_precision(2, 3) == pytest.approx(2 / 3)
    assert attribution_precision(1, 2) == 0.5
    assert supported_claim_rate(2, 3) == pytest.approx(2 / 3)
    assert span_precision(0, 0) is None


def test_latency_summary_and_failure_category_counts_are_deterministic():
    from evaluation.metrics import latency_summary, failure_category_counts

    assert latency_summary([10, 20, 30]) == {"count": 3, "min": 10, "median": 20, "mean": 20, "max": 30}
    assert latency_summary([]) == {"count": 0, "min": None, "median": None, "mean": None, "max": None}
    assert failure_category_counts(["retriever_miss", "retriever_miss", "unsupported_generation"]) == {
        "retriever_miss": 2,
        "unsupported_generation": 1,
    }


def test_ragas_adapter_validates_fields_and_isolates_metric_provider_errors():
    from evaluation.ragas_metrics import RagasEvaluator

    class Provider:
        def score(self, scorer, sample):
            if scorer == "faithfulness":
                raise RuntimeError("provider offline")
            return 0.75

    evaluator = RagasEvaluator(provider=Provider())
    evaluator._scorers = {
        "Faithfulness": "faithfulness", "ContextPrecision": "context_precision",
        "ContextRecall": "context_recall", "ContextEntityRecall": "context_entity_recall",
        "AnswerRelevancy": "answer_relevancy", "AnswerCorrectness": "answer_correctness",
    }
    sample = {"user_input": "question", "response": "answer", "retrieved_contexts": ["context"], "reference": "reference"}
    results = evaluator.evaluate(sample, metrics=["faithfulness", "context_precision"])
    assert results["faithfulness"] == {"status": "failed", "value": None, "reason": "provider offline"}
    assert results["context_precision"] == {"status": "completed", "value": 0.75, "reason": None}

    missing = evaluator.evaluate({"user_input": "question"}, metrics=["answer_correctness"])
    assert missing["answer_correctness"]["status"] == "not_run"
    assert "reference" in missing["answer_correctness"]["reason"]


def test_ragas_missing_dependency_is_not_reported_as_a_zero(monkeypatch):
    from evaluation.ragas_metrics import RagasEvaluator

    evaluator = RagasEvaluator(provider=object())
    monkeypatch.setattr(evaluator, "_load_scorers", lambda: (_ for _ in ()).throw(ImportError("ragas missing")))
    result = evaluator.evaluate({"user_input": "q", "response": "a", "retrieved_contexts": ["c"]}, metrics=["faithfulness"])
    assert result["faithfulness"]["status"] == "not_run"
    assert result["faithfulness"]["value"] is None
    assert "ragas missing" in result["faithfulness"]["reason"]


def test_ragas_scorers_have_explicit_required_sample_fields():
    from evaluation.ragas_metrics import RagasEvaluator, SCORERS

    evaluator = RagasEvaluator()
    full_sample = {
        "user_input": "q", "response": "a", "retrieved_contexts": ["c"], "reference": "r",
    }
    results = evaluator.evaluate(full_sample, metrics=list(SCORERS))
    assert set(results) == set(SCORERS)
    assert all(result["status"] == "not_run" and result["value"] is None for result in results.values())
    for name, (_scorer, required) in SCORERS.items():
        missing_sample = {key: value for key, value in full_sample.items() if key not in required}
        result = evaluator.evaluate(missing_sample, metrics=[name])[name]
        assert result["status"] == "not_run"
        assert result["reason"].startswith("missing required fields:")


def test_diagnostics_assign_only_known_failure_categories_without_prompt_storage():
    from evaluation.diagnostics import diagnose_failures

    results = diagnose_failures({
        "relevant_pmids": ["1"], "candidate_pmids": [],
        "context_pmids": [], "claims": [{"supported": False, "citation_valid": False}],
        "required_subquestions": ["mechanism"], "covered_subquestions": [],
        "prompt": "private prompt", "reasoning": "hidden reasoning",
    })
    assert {item["category"] for item in results} >= {"retriever_miss", "missing_evidence", "incomplete_answer"}
    assert all("prompt" not in item and "reasoning" not in item for item in results)


def test_diagnostics_cover_context_noise_and_extraction_miss_categories():
    from evaluation.diagnostics import diagnose_failures

    noisy = diagnose_failures({"relevant_pmids": ["1"], "candidate_pmids": ["2"], "context_pmids": ["2"]})
    extraction = diagnose_failures({"extraction_miss": True})
    assert noisy[0]["category"] == "context_noise"
    assert extraction == [{"category": "extraction_miss", "reason": "source evidence was not extracted"}]
