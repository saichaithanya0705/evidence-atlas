"""Measure fresh live agentic calls with stage, provider, and grounding evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.config import get_settings
from backend.app.core.nim_client import create_nim_client
from backend.app.workflow.service import ResearchService
from evaluation.benchmark import load_benchmark
from evaluation.variants import pipeline_source_checksum


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--queries", nargs="+", default=["kidney_stones_ckd_risk", "telehealth_ckd_bp", "aa_amyloidosis_renal_survival", "raas_advanced_ckd_diabetes"])
    parser.add_argument("--max-loops", type=int, default=2)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--no-warmup", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    source_identity = pipeline_source_checksum()
    if settings.LLM_MODE != "nim" or not settings.get_raw_nvidia_api_key() or settings.MEDCPT_ALLOW_MOCK:
        raise SystemExit("This benchmark requires configured live NIM and real MedCPT.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    entries = {entry.id: entry for entry in load_benchmark(ROOT / "data/evaluation/benchmark_v2.json").entries}
    if not args.queries or any(query_id not in entries for query_id in args.queries):
        parser.error("Unknown benchmark query ID")
    secret = settings.get_raw_nvidia_api_key()
    calls = []
    clients = []

    def tracked_client(config):
        client = create_nim_client(config)
        clients.append(client)
        original = client.chat.completions.create

        def complete(**kwargs):
            started = time.perf_counter()
            call = {"model": kwargs.get("model"), "messages": kwargs.get("messages"), "max_tokens": kwargs.get("max_tokens"), "response_format": kwargs.get("response_format"), "extra_body": kwargs.get("extra_body")}
            try:
                response = original(**kwargs)
                call.update({"completed": True, "content": response.choices[0].message.content, "finish_reason": response.choices[0].finish_reason, "usage": response.usage.model_dump() if response.usage else None})
                return response
            except Exception as exc:
                call.update({"completed": False, "error_type": type(exc).__name__})
                raise
            finally:
                call["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
                calls.append(call)

        client.chat.completions.create = complete
        return client

    import backend.app.workflow.judge as judge
    import backend.app.workflow.synthesis as synthesis
    import backend.app.workflow.verification as verification
    for module in (judge, synthesis, verification):
        module.create_nim_client = tracked_client
    service = ResearchService(settings=settings)
    measurements = []

    def measure(query_id, *, warmup=False):
        entry = entries[query_id]
        before = len(calls)
        started = time.perf_counter()
        response, trace = service.research_benchmark_entry(entry, max_loops=args.max_loops)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        measurement = {"query_id": query_id, "warmup": warmup, "wall_ms": elapsed, "answer_status": str(response.answer_status.value), "citation_count": len(response.cited_pmids), "citations_valid": response.citations_valid, "provider_calls": calls[before:], "trace": trace, "response": response.model_dump(mode="json")}
        filename = ("warmup" if warmup else f"query-{len(measurements):02d}-{query_id}") + ".json"
        encoded = json.dumps(measurement, ensure_ascii=False, indent=2).replace(secret, "[REDACTED]")
        (args.output_dir / filename).write_text(encoded, encoding="utf-8")
        if not warmup:
            measurements.append(measurement)
        print(json.dumps({key: measurement[key] for key in ("query_id", "warmup", "wall_ms", "answer_status", "citation_count")} | {"llm_calls": len(measurement["provider_calls"])}), flush=True)

    try:
        if not args.no_warmup:
            measure(args.queries[0], warmup=True)
        for _ in range(args.repeat):
            for query_id in args.queries:
                measure(query_id)
        durations = [row["wall_ms"] for row in measurements]
        if pipeline_source_checksum() != source_identity:
            raise RuntimeError("Pipeline changed during the live benchmark; rerun before comparing results.")
        result = {"model": settings.NVIDIA_MODEL_NAME, "source_checksum": source_identity, "query_count": len(measurements), "max_loops": args.max_loops, "latency_ms": {"median": statistics.median(durations), "mean": statistics.mean(durations), "max": max(durations)}, "answer_status_distribution": dict(Counter(row["answer_status"] for row in measurements)), "llm_calls": sum(len(row["provider_calls"]) for row in measurements), "successful_llm_calls": sum(call["completed"] for row in measurements for call in row["provider_calls"]), "all_citations_valid": all(row["citations_valid"] for row in measurements), "warmup_excluded": not args.no_warmup}
        (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)
    finally:
        service.close()
        for client in clients:
            client.close()


if __name__ == "__main__":
    main()
