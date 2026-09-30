"""Evaluate saved comparable variant artifacts and promote immutable reports.

The bundled corpus and judgments are for software demonstrations, not clinical
evidence or a representative PubMed benchmark. Citation checks run only when
caller-provided answer artifacts are supplied with ``--answers``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.query.query_service import QueryAnalysisService
from backend.app.retrieval.bm25 import BM25Index
from evaluation.citations import evaluate_answer_citations
from evaluation.benchmark import file_checksum, load_benchmark, stable_checksum
from evaluation.metrics import (
    citation_precision, citation_validity, failure_category_counts, latency_summary,
    ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank, route_confusion,
)
from evaluation.reporting import ReportStore
from evaluation.diagnostics import diagnose_failures
from evaluation.robustness import SCENARIOS, evaluate_robustness

logger = logging.getLogger("evaluation")
DEFAULT_QUERY_FILE = PROJECT_ROOT / "data" / "evaluation" / "queries.json"
_ROBUSTNESS_STOP_WORDS = {"a", "an", "and", "are", "does", "for", "in", "is", "of", "on", "the", "to", "with"}


def _default_robustness_scores(_entry: Any, _artifact: Any, sample: dict[str, Any]) -> dict[str, float | None]:
    """Score perturbed saved evidence with deterministic, artifact-backed metrics."""
    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", str(sample.get("query", "")).casefold())
        if token not in _ROBUSTNESS_STOP_WORDS
    }
    context_text = " ".join(map(str, sample.get("contexts", ())))
    context_terms = set(re.findall(r"[a-z0-9]+", context_text.casefold()))
    query_coverage = len(query_terms & context_terms) / len(query_terms) if query_terms else None

    context_pmids = sample.get("context_pmids")
    relevant_pmids = set(map(str, sample.get("relevant_pmids", ())))
    context_precision = (
        sum(str(pmid) in relevant_pmids for pmid in context_pmids) / len(context_pmids)
        if context_pmids else None
    )

    filters = sample.get("filters", {})
    candidates = sample.get("candidate_metadata", ())
    filter_checks: list[bool] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        year = candidate.get("year")
        if year is not None and filters.get("year_from") is not None:
            filter_checks.append(int(year) >= int(filters["year_from"]))
        if year is not None and filters.get("year_to") is not None:
            filter_checks.append(int(year) <= int(filters["year_to"]))
        expected_types = list(filters.get("study_types") or ())
        if filters.get("study_type"):
            expected_types.append(filters["study_type"])
        actual_type = str(candidate.get("study_type") or "").casefold()
        for expected_type in expected_types:
            expected = str(expected_type).casefold()
            if actual_type:
                filter_checks.append(actual_type == expected or actual_type in expected or expected in actual_type)

    filter_compliance = sum(filter_checks) / len(filter_checks) if filter_checks else None
    return {
        "query_context_coverage": query_coverage,
        "context_precision": context_precision,
        "candidate_filter_compliance": filter_compliance,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def evaluate_retrieval_and_router(
    queries: list[dict[str, Any]],
    search: Callable[[str, int], list[tuple[int, float]]],
    route: Callable[[str], str],
    top_k: int = 10,
) -> dict[str, Any]:
    """Compute macro Recall/Precision/MRR/nDCG and labeled router accuracy."""
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    recall_values: list[float] = []
    precision_values: list[float] = []
    mrr_values: list[float] = []
    ndcg_values: list[float] = []
    route_correct = 0
    route_labeled = 0
    rows = []

    for item in queries:
        query = str(item["query"])
        relevant = {str(pmid) for pmid in item.get("relevant_pmids", [])}
        if not relevant:
            raise ValueError(f"Query {item.get('id', query)!r} has no relevance labels")
        ranking = [str(pmid) for pmid, _ in search(query, top_k)[:top_k]]
        hits = [pmid for pmid in ranking if pmid in relevant]
        recall = len(set(hits)) / len(relevant)
        precision = len(hits) / top_k
        reciprocal_rank = next((1.0 / rank for rank, pmid in enumerate(ranking, 1) if pmid in relevant), 0.0)
        dcg = sum(1.0 / math.log2(rank + 1) for rank, pmid in enumerate(ranking, 1) if pmid in relevant)
        ideal_hits = min(len(relevant), top_k)
        ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
        ndcg = dcg / ideal_dcg if ideal_dcg else 0.0

        predicted_route = route(query)
        expected_route = item.get("expected_route")
        if expected_route:
            route_labeled += 1
            is_route_correct = predicted_route == expected_route
            route_correct += int(is_route_correct)
        else:
            is_route_correct = None

        recall_values.append(recall)
        precision_values.append(precision)
        mrr_values.append(reciprocal_rank)
        ndcg_values.append(ndcg)
        rows.append({
            "id": item.get("id"),
            "query": query,
            "relevant_pmids": sorted(relevant),
            "retrieved_pmids": ranking,
            "recall_at_k": recall,
            "precision_at_k": precision,
            "reciprocal_rank": reciprocal_rank,
            "ndcg_at_k": ndcg,
            "expected_route": expected_route,
            "predicted_route": predicted_route,
            "route_correct": is_route_correct,
        })

    return {
        "top_k": top_k,
        "query_count": len(queries),
        "metrics": {
            f"recall@{top_k}": _mean(recall_values),
            f"precision@{top_k}": _mean(precision_values),
            f"mrr@{top_k}": _mean(mrr_values),
            f"ndcg@{top_k}": _mean(ndcg_values),
            "router_accuracy": route_correct / route_labeled if route_labeled else None,
            "router_labeled_query_count": route_labeled,
        },
        "queries": rows,
    }


def evaluate_citation_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    answers = payload.get("answers", payload) if isinstance(payload, dict) else payload
    if not isinstance(answers, list):
        raise ValueError("Citation answer artifact must be a JSON list or an object with an 'answers' list")
    evaluated = [
        {"query_id": answer.get("query_id"), **evaluate_answer_citations(answer)}
        for answer in answers
        if isinstance(answer, dict)
    ]
    citations = sum(item["citation_count"] for item in evaluated)
    valid_pmids = sum(item["valid_pmid_count"] for item in evaluated)
    quotes = sum(item["quoted_span_count"] for item in evaluated)
    valid_quotes = sum(item["valid_quoted_span_count"] for item in evaluated)
    return {
        "answer_count": len(evaluated),
        "citation_count": citations,
        "pmid_precision": valid_pmids / citations if citations else None,
        "quoted_span_count": quotes,
        "quoted_span_precision": valid_quotes / quotes if quotes else None,
        "answers": evaluated,
        "scope": "identifier membership and exact quote membership only; semantic claim support is not measured",
    }


def run(query_file: Path, index_file: Path, top_k: int, answers_file: Path | None = None) -> dict[str, Any]:
    queries = json.loads(query_file.read_text(encoding="utf-8"))
    if not isinstance(queries, list) or not queries:
        raise ValueError(f"Benchmark must be a non-empty JSON list: {query_file}")
    if not index_file.is_file():
        raise FileNotFoundError(f"BM25 index not found: {index_file}. Run start.bat or build the corpus artifacts first.")
    bm25 = BM25Index.load(index_file)
    query_service = QueryAnalysisService()
    is_demo_benchmark = query_file.name == DEFAULT_QUERY_FILE.name

    def predict_route(query: str) -> str:
        plan, _ = query_service.build_query_plan(query, generate_embeddings=False)
        return plan.route

    report: dict[str, Any] = {
        "benchmark": (
            "bundled synthetic demo corpus; manually assigned judgments"
            if is_demo_benchmark
            else "caller-selected corpus benchmark; inspect query labels and provenance"
        ),
        "query_file": str(query_file.relative_to(PROJECT_ROOT)) if query_file.is_relative_to(PROJECT_ROOT) else str(query_file),
        "bm25_index": str(index_file.relative_to(PROJECT_ROOT)) if index_file.is_relative_to(PROJECT_ROOT) else str(index_file),
        "limitations": (
            [
                "This is a small fixture benchmark, not a representative PubMed relevance study.",
                "Bundled fixture PMIDs and abstracts are demo records and are not verified against PubMed.",
                "Classical ranking metrics do not establish clinical correctness or claim grounding.",
            ]
            if is_demo_benchmark
            else [
                "This pilot benchmark is small and its labels are provisional pending independent biomedical review.",
                "The active corpus is query-focused rather than representative of all PubMed.",
                "Classical ranking metrics do not establish clinical correctness or claim grounding.",
            ]
        ),
        **evaluate_retrieval_and_router(queries, bm25.search, predict_route, top_k),
        "citations": evaluate_citation_artifact(answers_file) if answers_file else {"status": "not_run", "reason": "Pass --answers with saved research responses to check citation IDs and exact evidence quotes."},
    }
    return report


def evaluate_saved_variants(
    benchmark_path: str | Path,
    artifacts_dir: str | Path,
    reports_dir: str | Path,
    *,
    run_id: str,
    top_k: int = 10,
    robustness_runner: Callable[[Any, Any, dict[str, Any]], dict[str, float | int | None]] | None = None,
    allow_subset: bool = False,
    ragas_evaluator: Any = None,
) -> dict[str, Any]:
    """Score available Task 7 artifacts and promote only a complete benchmark run."""
    from evaluation.variants import QueryEvaluationArtifact

    dataset = load_benchmark(benchmark_path)
    corpus_checksum = file_checksum(dataset.corpus_path)
    base = Path(artifacts_dir)
    variants = ("dense_only", "hybrid", "reranked", "agentic")
    loaded: dict[str, dict[str, QueryEvaluationArtifact]] = {name: {} for name in variants}
    for variant in variants:
        for entry in dataset.entries:
            path = base / variant / f"{entry.id}.json"
            if not path.is_file():
                continue
            artifact = QueryEvaluationArtifact.model_validate_json(path.read_text(encoding="utf-8"))
            if (
                artifact.variant != variant
                or artifact.query_id != entry.id
                or artifact.query != entry.query
                or artifact.benchmark_version != dataset.version
                or artifact.corpus_identity != corpus_checksum
            ):
                raise ValueError(f"variant artifact identity mismatch: {path}")
            loaded[variant][entry.id] = artifact
        if len(loaded[variant]) not in (0, len(dataset.entries)):
            raise ValueError(f"variant {variant} is partial; refusing to promote an incomplete run")
    active = [name for name in variants if loaded[name]]
    if not allow_subset and set(active) != set(variants):
        missing = [name for name in variants if not loaded[name]]
        raise ValueError(f"report promotion requires complete artifacts for all four variants; missing: {', '.join(missing)}")
    if not active:
        raise ValueError("no complete variant artifacts were found")

    metric_results: dict[str, dict[str, Any]] = {}
    per_query: dict[str, dict[str, Any]] = {entry.id: {"query_id": entry.id, "variants": {}} for entry in dataset.entries}
    failures: list[str] = []
    answer_status_distribution: dict[str, int] = {}
    variant_latencies: dict[str, list[float]] = {name: [] for name in active}
    robustness_results: dict[str, dict[str, Any]] = {name: {} for name in active}
    robustness_errors: dict[str, list[str]] = {name: [] for name in active}
    effective_robustness_runner = robustness_runner or _default_robustness_scores
    corpus_pmids = set()
    try:
        from evaluation.adjudication import load_corpus_pmids
        corpus_pmids = load_corpus_pmids(dataset.corpus_path)
    except (ImportError, OSError, ValueError, KeyError):
        pass
    for variant in active:
        metric_values: dict[str, list[float]] = {name: [] for name in (f"recall@{top_k}", f"precision@{top_k}", f"mrr@{top_k}", f"ndcg@{top_k}")}
        filter_values: list[float] = []
        filter_missing = []
        coverage_values: list[float] = []
        completeness_values: list[float] = []
        attribution_correct = attribution_total = 0
        supported_claims = material_claims = 0
        span_numerator = span_denominator = 0
        for entry in dataset.entries:
            artifact = loaded[variant][entry.id]
            judged = {judgment.pmid: judgment.relevance for judgment in entry.judgments}
            ranking = artifact.candidate_pmids
            query_metrics = {
                f"recall@{top_k}": recall_at_k(ranking, judged, top_k),
                f"precision@{top_k}": precision_at_k(ranking, judged, top_k),
                f"mrr@{top_k}": reciprocal_rank(ranking, judged, top_k),
                f"ndcg@{top_k}": ndcg_at_k(ranking, judged, top_k),
            }
            for name, value in query_metrics.items():
                metric_values[name].append(float(value or 0.0))
            variant_latencies[variant].append(artifact.latency_ms)
            constraints: dict[str, Any] = {"study_types": [entry.study_type]}
            for lower, upper in (("year_min", "year_max"), ("year_from", "year_to")):
                if artifact.metadata_filters.get(lower) is not None:
                    constraints[lower] = artifact.metadata_filters[lower]
                if artifact.metadata_filters.get(upper) is not None:
                    constraints[upper] = artifact.metadata_filters[upper]
            candidate_checks: list[bool] = []
            missing_fields: set[str] = set()
            for candidate in artifact.candidates:
                if not isinstance(candidate, dict) or "filter_satisfied" not in candidate:
                    missing_fields.add("candidate.filter_satisfied")
                    continue
                if not isinstance(candidate["filter_satisfied"], bool):
                    missing_fields.add("candidate.filter_satisfied")
                    continue
                compliant = candidate["filter_satisfied"]
                actual_type = candidate.get("study_type")
                if not actual_type:
                    missing_fields.add("candidate.study_type")
                else:
                    expected_types = constraints["study_types"]
                    compliant = compliant and any(
                        str(actual_type).casefold() == str(expected).casefold()
                        or str(actual_type).casefold() in str(expected).casefold()
                        or str(expected).casefold() in str(actual_type).casefold()
                        for expected in expected_types
                    )
                year = candidate.get("year")
                for low_key, high_key in (("year_min", "year_max"), ("year_from", "year_to")):
                    low = constraints.get(low_key)
                    high = constraints.get(high_key)
                    if low is not None or high is not None:
                        if year is None:
                            missing_fields.add("candidate.year")
                            continue
                        try:
                            numeric_year = int(year)
                        except (TypeError, ValueError):
                            missing_fields.add("candidate.year")
                            continue
                        compliant = compliant and (low is None or numeric_year >= int(low)) and (high is None or numeric_year <= int(high))
                candidate_checks.append(compliant)
            filter_value = (sum(candidate_checks) / len(candidate_checks)) if candidate_checks and not missing_fields else None
            if filter_value is not None:
                filter_values.append(filter_value)
            else:
                filter_missing.append(entry.id)
            evidence_pmids = [str(item.get("pmid")) for item in (artifact.evidence or []) if isinstance(item, dict) and item.get("pmid")]
            answer = artifact.answer or {}
            if variant == "agentic" and isinstance(answer, dict):
                status = answer.get("answer_status")
                if status:
                    answer_status_distribution[str(status)] = answer_status_distribution.get(str(status), 0) + 1
            plan = artifact.research_plan or {}
            plan_questions = plan.get("subquestions", []) if isinstance(plan, dict) else []
            required_ids = [str(item.get("id")) for item in plan_questions if isinstance(item, dict) and item.get("id")]
            coverage_rows = artifact.coverage
            if isinstance(coverage_rows, dict):
                coverage_rows = [
                    {"subquestion_id": key, "status": value.get("status") if isinstance(value, dict) else value}
                    for key, value in coverage_rows.items()
                ]
            elif isinstance(coverage_rows, list) and coverage_rows and isinstance(coverage_rows[-1], dict) and isinstance(coverage_rows[-1].get("coverage"), list):
                coverage_rows = coverage_rows[-1]["coverage"]
            if required_ids and isinstance(coverage_rows, list):
                covered_ids = {
                    str(item.get("subquestion_id")) for item in coverage_rows
                    if isinstance(item, dict) and item.get("status") == "COVERED"
                }
                coverage_value = len(set(required_ids) & covered_ids) / len(set(required_ids))
                coverage_values.append(coverage_value)
            answered_ids = answer.get("answered_subquestions") or answer.get("covered_subquestions") if isinstance(answer, dict) else None
            if required_ids and isinstance(answered_ids, list):
                completeness_values.append(len(set(required_ids) & set(map(str, answered_ids))) / len(set(required_ids)))
            claim_attributions = answer.get("claim_attributions") if isinstance(answer, dict) else None
            if isinstance(claim_attributions, list):
                verdicts = [item.get("correct") for item in claim_attributions if isinstance(item, dict) and isinstance(item.get("correct"), bool)]
                attribution_correct += sum(verdicts)
                attribution_total += len(verdicts)
            claim_verifications = answer.get("claim_verifications") if isinstance(answer, dict) else None
            if isinstance(claim_verifications, list):
                verdicts = [item.get("supported") for item in claim_verifications if isinstance(item, dict) and isinstance(item.get("supported"), bool)]
                supported_claims += sum(verdicts)
                material_claims += len(verdicts)
            evidence_rows = artifact.evidence or []
            candidate_text = " ".join(str(item.get("abstract") or "") for item in artifact.candidates if isinstance(item, dict))
            spans = [str(span) for row in evidence_rows if isinstance(row, dict) for span in (row.get("supporting_text_spans") or []) if str(span).strip()]
            if spans:
                span_denominator += len(spans)
                span_numerator += sum(span in candidate_text for span in spans)
            citations_for_query = answer.get("cited_pmids") if isinstance(answer, dict) else None
            citations = answer.get("cited_pmids") if isinstance(answer, dict) else None
            diagnostic_input = {
                "relevant_pmids": entry.relevant_pmids,
                "candidate_pmids": ranking,
                "claims": answer.get("claims", []) if isinstance(answer, dict) else [],
                "required_subquestions": answer.get("required_subquestions", []) if isinstance(answer, dict) else [],
                "covered_subquestions": answer.get("covered_subquestions", []) if isinstance(answer, dict) else [],
            }
            if artifact.evidence is not None or artifact.answer is not None:
                diagnostic_input["context_pmids"] = evidence_pmids
            query_diagnostics = diagnose_failures(diagnostic_input)
            failures.extend(item["category"] for item in query_diagnostics)
            query_details = {
                "candidate_pmids": ranking,
                "metrics": query_metrics,
                "latency_ms": artifact.latency_ms,
                "configuration_hash": artifact.configuration_hash,
                "diagnostics": query_diagnostics,
            }
            if variant == "agentic" and isinstance(answer, dict):
                query_details["answer_status"] = answer.get("answer_status")
            if filter_value is not None:
                query_details["filter_accuracy"] = {"status": "completed", "value": filter_value, "reason": None}
            else:
                query_details["filter_accuracy"] = {"status": "not_run", "value": None, "reason": f"candidate metadata missing required constraints: {', '.join(sorted(missing_fields)) or 'no returned candidates'}"}
            if required_ids and isinstance(coverage_rows, list):
                query_details["subquestion_coverage"] = {"status": "completed", "value": coverage_value, "reason": None}
            if required_ids and isinstance(answered_ids, list):
                query_details["answer_completeness"] = {"status": "completed", "value": len(set(required_ids) & set(map(str, answered_ids))) / len(set(required_ids)), "reason": None}
            if citations_for_query is not None:
                query_details["citation_precision"] = {"status": "completed", "value": citation_precision(citations_for_query, entry.relevant_pmids), "reason": None} if citations_for_query else {"status": "not_run", "value": None, "reason": "answer contains no citations"}
                query_details["citation_validity"] = {"status": "completed", "value": citation_validity(citations_for_query, corpus_pmids), "reason": None} if citations_for_query and corpus_pmids else {"status": "not_run", "value": None, "reason": "citations or active-corpus PMID membership unavailable"}
            if spans:
                query_details["span_precision"] = {"status": "completed", "value": sum(span in candidate_text for span in spans) / len(spans), "reason": None}
            if isinstance(plan, dict) and plan.get("route"):
                query_details["route_accuracy"] = {"status": "completed", "value": float(plan["route"] == entry.expected_route), "reason": None}
            if effective_robustness_runner is not None:
                contexts = [
                    str(candidate.get("abstract") or candidate.get("context") or candidate.get("title"))
                    for candidate in artifact.candidates
                    if isinstance(candidate, dict) and (candidate.get("abstract") or candidate.get("context") or candidate.get("title"))
                ]
                robustness_sample = {
                    "query": entry.query,
                    "contexts": contexts,
                    "filters": artifact.metadata_filters,
                    "candidate_metadata": artifact.candidates,
                    "context_pmids": list(artifact.candidate_pmids),
                    "relevant_pmids": list(entry.relevant_pmids),
                }
                try:
                    result = evaluate_robustness(
                        robustness_sample,
                        lambda changed: effective_robustness_runner(entry, artifact, changed),
                    )
                    robustness_results[variant][entry.id] = result
                    query_details["robustness"] = result
                except Exception as exc:
                    reason = f"robustness evaluator failed ({type(exc).__name__})"
                    robustness_errors[variant].append(reason)
                    query_details["robustness"] = {"status": "failed", "value": None, "reason": reason}
            if citations is not None:
                query_details["citation_metrics"] = {
                    "citation_validity": citation_validity(citations, corpus_pmids) if corpus_pmids else None,
                    "citation_precision": citation_precision(citations, entry.relevant_pmids),
                }
            per_query[entry.id]["variants"][variant] = query_details
        for name, values in metric_values.items():
            metric_results[f"{variant}.{name}"] = {"status": "completed", "value": sum(values) / len(values), "reason": None}
        metric_results[f"{variant}.filter_accuracy"] = (
            {"status": "completed", "value": sum(filter_values) / len(filter_values), "reason": None}
            if filter_values and not filter_missing else {"status": "not_run", "value": None, "reason": "candidate constraint metadata unavailable for queries: " + ", ".join(filter_missing or ["all queries"])}
        )
        metric_results[f"{variant}.latency_ms"] = {"status": "completed", "value": latency_summary(variant_latencies[variant]), "reason": None}
        route_rows = [item for item in loaded[variant].values() if item.research_plan and item.research_plan.get("route")]
        metric_results[f"{variant}.route_accuracy"] = {"status": "completed", "value": sum(item.research_plan["route"] == item.expected_route for item in route_rows) / len(route_rows), "reason": None} if route_rows else {"status": "not_run", "value": None, "reason": "no saved research plan contains a predicted route"}
        metric_results[f"{variant}.route_confusion"] = {"status": "completed", "value": route_confusion([item.expected_route for item in route_rows], [item.research_plan["route"] for item in route_rows]), "reason": None} if route_rows else {"status": "not_run", "value": None, "reason": "no saved research plan contains a predicted route"}
        metric_results[f"{variant}.subquestion_coverage"] = {"status": "completed", "value": sum(coverage_values) / len(coverage_values), "reason": None} if coverage_values else {"status": "not_run", "value": None, "reason": "saved plan and coverage history do not contain required subquestion IDs and statuses"}
        completeness_missing_reason = "retrieval-only variant has no answer payload" if variant != "agentic" else "answer payload lacks explicit answered subquestion IDs"
        metric_results[f"{variant}.answer_completeness"] = {"status": "completed", "value": sum(completeness_values) / len(completeness_values), "reason": None} if completeness_values else {"status": "not_run", "value": None, "reason": completeness_missing_reason}
        metric_results[f"{variant}.span_precision"] = {"status": "completed", "value": span_numerator / span_denominator, "reason": None} if span_denominator else {"status": "not_run", "value": None, "reason": "saved evidence contains no supporting spans to check against returned abstracts"}
        metric_results[f"{variant}.attribution_precision"] = {"status": "completed", "value": attribution_correct / attribution_total, "reason": None} if attribution_total else {"status": "not_run", "value": None, "reason": "saved response has no claim-to-citation attribution verdicts"}
        metric_results[f"{variant}.supported_claim_rate"] = {"status": "completed", "value": supported_claims / material_claims, "reason": None} if material_claims else {"status": "not_run", "value": None, "reason": "saved response has no validated claim-level support verdicts"}
        if variant != "agentic":
            for metric in ("citation_validity", "citation_precision"):
                metric_results[f"{variant}.{metric}"] = {"status": "not_run", "value": None, "reason": "retrieval-only variant has no answer citations"}
        ragas_names = ("faithfulness", "context_precision", "context_recall", "context_entity_recall", "answer_relevancy", "answer_correctness")
        ragas_per_metric: dict[str, list[float]] = {name: [] for name in ragas_names}
        ragas_missing: dict[str, list[str]] = {name: [] for name in ragas_names}
        ragas_failures: dict[str, list[str]] = {name: [] for name in ragas_names}
        if variant == "agentic":
            if ragas_evaluator is None:
                from evaluation.ragas_metrics import RagasEvaluator
                effective_ragas_evaluator = RagasEvaluator()
            else:
                effective_ragas_evaluator = ragas_evaluator
            for entry in dataset.entries:
                artifact = loaded[variant][entry.id]
                answer = artifact.answer or {}
                contexts = [str(item.get("abstract") or "") for item in artifact.candidates if isinstance(item, dict) and item.get("abstract")]
                sample = {"user_input": entry.query, "response": answer.get("synthesis"), "retrieved_contexts": contexts}
                evaluated = effective_ragas_evaluator.evaluate(sample)
                for metric, result in evaluated.items():
                    if metric in ragas_per_metric and result.get("status") == "completed":
                        ragas_per_metric[metric].append(float(result["value"]))
                    elif metric in ragas_failures and result.get("status") == "failed":
                        ragas_failures[metric].append(str(result.get("reason") or "provider failed"))
                    elif metric in ragas_missing:
                        ragas_missing[metric].append(str(result.get("reason") or result.get("status") or "unavailable"))
        for metric in ragas_names:
            values = ragas_per_metric[metric]
            if variant != "agentic":
                metric_results[f"{variant}.ragas.{metric}"] = {"status": "not_run", "value": None, "reason": "retrieval-only variant has no answer-generation sample"}
            elif ragas_failures[metric]:
                metric_results[f"{variant}.ragas.{metric}"] = {"status": "failed", "value": None, "reason": sorted(set(ragas_failures[metric]))[0]}
            elif values and not ragas_missing[metric]:
                metric_results[f"{variant}.ragas.{metric}"] = {"status": "completed", "value": sum(values) / len(values), "reason": None}
            else:
                reason = sorted(set(ragas_missing[metric]))[0] if ragas_missing[metric] else "configured RAGAS evaluator did not return a result for this metric"
                metric_results[f"{variant}.ragas.{metric}"] = {"status": "not_run", "value": None, "reason": reason}
        if effective_robustness_runner is None:
            metric_results[f"{variant}.robustness"] = {"status": "not_run", "value": None, "reason": "a retrieval and metric callback for perturbed inputs was not supplied"}
        elif robustness_errors[variant]:
            metric_results[f"{variant}.robustness"] = {"status": "failed", "value": None, "reason": robustness_errors[variant][0]}
        else:
            scenario_deltas: dict[str, dict[str, list[float]]] = {scenario: {} for scenario in SCENARIOS}
            for query_result in robustness_results[variant].values():
                for scenario, scenario_result in query_result["scenarios"].items():
                    for metric, delta in scenario_result["metric_deltas"].items():
                        scenario_deltas[scenario].setdefault(metric, []).append(float(delta))
            summary = {
                "scenario_count": len(SCENARIOS),
                "query_count": len(robustness_results[variant]),
                "scenarios": {
                    scenario: {
                        "mean_metric_deltas": {
                            metric: sum(values) / len(values) for metric, values in sorted(metrics.items()) if values
                        }
                    }
                    for scenario, metrics in scenario_deltas.items()
                },
            }
            metric_results[f"{variant}.robustness"] = {"status": "completed", "value": summary, "reason": None}

    for variant in active:
        cited = [str(pmid) for artifact in loaded[variant].values() if artifact.answer for pmid in (artifact.answer.get("cited_pmids") or [])]
        if corpus_pmids and cited:
            metric_results[f"{variant}.citation_validity"] = {"status": "completed", "value": citation_validity(cited, corpus_pmids), "reason": None}
        else:
            metric_results[f"{variant}.citation_validity"] = {"status": "not_run", "value": None, "reason": "no citations were saved or active-corpus PMID membership could not be loaded"}
        relevant = {entry.id: set(entry.relevant_pmids) for entry in dataset.entries}
        judged_citations = [
            (entry.id, str(pmid)) for entry in dataset.entries
            for artifact in [loaded[variant][entry.id]] if artifact.answer
            for pmid in (artifact.answer.get("cited_pmids") or [])
        ]
        if judged_citations:
            metric_results[f"{variant}.citation_precision"] = {"status": "completed", "value": sum(pmid in relevant[query_id] for query_id, pmid in judged_citations) / len(judged_citations), "reason": None}
        else:
            metric_results[f"{variant}.citation_precision"] = {"status": "not_run", "value": None, "reason": "no citations were saved"}
    report = {
        "run_id": run_id,
        "benchmark_checksum": file_checksum(benchmark_path),
        "corpus_checksum": corpus_checksum,
        "configuration_checksum": stable_checksum({variant: sorted(artifact.configuration_hash for artifact in loaded[variant].values()) for variant in active}),
        "variants": active,
        "query_count": len(dataset.entries),
        "metrics": metric_results,
        "latency": {variant: latency_summary(values) for variant, values in variant_latencies.items()},
        "failure_categories": failure_category_counts(failures),
        "answer_status_distribution": answer_status_distribution,
        "robustness": {
            variant: {
                "status": metric_results[f"{variant}.robustness"]["status"],
                "value": metric_results[f"{variant}.robustness"].get("value"),
                "reason": metric_results[f"{variant}.robustness"].get("reason"),
                "queries": {
                    entry.id: per_query[entry.id]["variants"][variant]["robustness"]
                    for entry in dataset.entries
                    if "robustness" in per_query[entry.id]["variants"][variant]
                },
            }
            for variant in active
        },
        "limitations": [
            "Robustness deltas are computed deterministically from saved candidate/context artifacts and do not rerun model inference or production retrieval.",
            "Optional provider metrics remain not_run when references or provider credentials are unavailable.",
        ],
    }
    return ReportStore(reports_dir).publish(run_id, report, {f"{query_id}.json": payload for query_id, payload in per_query.items()})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=Path("data/evaluation/benchmark_v2.json"))
    parser.add_argument("--artifacts-dir", type=Path, default=Path("data/evaluation/variants"))
    parser.add_argument("--variants", nargs="+", choices=("dense_only", "hybrid", "reranked", "agentic"),
                        default=["dense_only", "hybrid", "reranked", "agentic"])
    parser.add_argument("--reports-dir", "--output-dir", dest="reports_dir", type=Path, default=Path("evaluation/reports"))
    parser.add_argument("--run-id", help="Immutable report ID; defaults to a checksum-derived ID")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--allow-subset", action="store_true", help="Explicitly permit a report containing only the complete variants that are present; such reports are not suitable for four-variant promotion.")
    parser.add_argument("--ragas-provider", help="Optional provider factory as module:callable; the callable returns an adapter with score(scorer, sample).")
    args = parser.parse_args(argv)
    if len(args.variants) != 4 or set(args.variants) != {"dense_only", "hybrid", "reranked", "agentic"}:
        parser.error("report promotion requires exactly all four variants: dense_only hybrid reranked agentic")
    try:
        run_id = args.run_id or f"eval-{file_checksum(args.benchmark)[:12]}-{stable_checksum({str(args.artifacts_dir): args.top_k})[:12]}"
        ragas_evaluator = None
        if args.ragas_provider:
            import importlib
            from evaluation.ragas_metrics import RagasEvaluator
            module_name, separator, factory_name = args.ragas_provider.partition(":")
            if not separator or not module_name or not factory_name:
                raise ValueError("--ragas-provider must be formatted as module:callable")
            try:
                factory = getattr(importlib.import_module(module_name), factory_name)
                ragas_evaluator = RagasEvaluator(provider=factory())
            except (ImportError, AttributeError) as exc:
                ragas_evaluator = RagasEvaluator(unavailable_reason=f"configured RAGAS provider unavailable: {type(exc).__name__}")
            except Exception as exc:
                ragas_evaluator = RagasEvaluator(unavailable_reason=f"configured RAGAS provider initialization failed: {type(exc).__name__}")
        report = evaluate_saved_variants(args.benchmark, args.artifacts_dir, args.reports_dir, run_id=run_id, top_k=args.top_k, allow_subset=args.allow_subset, ragas_evaluator=ragas_evaluator)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
