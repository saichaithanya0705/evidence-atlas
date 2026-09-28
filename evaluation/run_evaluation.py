"""Run BM25 retrieval and adaptive-router checks against frozen demo labels.

The bundled corpus and judgments are for software demonstrations, not clinical
evidence or a representative PubMed benchmark. Citation checks run only when
caller-provided answer artifacts are supplied with ``--answers``.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.query.query_service import QueryAnalysisService
from backend.app.retrieval.bm25 import BM25Index
from evaluation.citations import evaluate_answer_citations

logger = logging.getLogger("evaluation")
DEFAULT_QUERY_FILE = PROJECT_ROOT / "data" / "evaluation" / "queries.json"


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERY_FILE, help="Frozen benchmark JSON")
    parser.add_argument("--index", type=Path, default=PROJECT_ROOT / "data" / "processed" / "bm25_index.pkl", help="Built BM25 pickle")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--answers", type=Path, help="Optional JSON answer artifacts for deterministic citation checks")
    parser.add_argument("--output", type=Path, help="Write report JSON (defaults to stdout)")
    args = parser.parse_args(argv)
    try:
        report = run(args.queries.resolve(), args.index.resolve(), args.top_k, args.answers.resolve() if args.answers else None)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
        print(f"Wrote evaluation report to {output_path}")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
