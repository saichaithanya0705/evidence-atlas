r"""Measure real HTTP research latency and admin-only backend stage timings.

Run from the repository root while the API is running:
    .venv\Scripts\python scripts\benchmark_research_latency.py --runs 3

The script prints timing metadata only, never the administrator key or answer.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from urllib.request import Request, urlopen

from dotenv import dotenv_values


def _json_request(url: str, key: str, body: dict | None = None) -> dict:
    headers = {"X-Admin-Key": key}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    with urlopen(Request(url, data=data, headers=headers), timeout=180) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--query", default="Empagliflozin kidney outcomes in type 2 diabetes")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-loops", type=int, default=0)
    parser.add_argument("--year-min", type=int)
    parser.add_argument("--year-max", type=int)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    key = os.environ.get("ADMIN_API_KEY") or dotenv_values(".env").get("ADMIN_API_KEY")
    if not key:
        parser.error("ADMIN_API_KEY must be configured in .env")

    measurements = []
    for run in range(1, args.runs + 1):
        started = time.perf_counter()
        response = _json_request(
            f"{args.url.rstrip('/')}/research",
            key,
            {
                "query": args.query,
                "max_loops": args.max_loops,
                "year_min": args.year_min,
                "year_max": args.year_max,
            },
        )
        wall_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = _json_request(f"{args.url.rstrip('/')}/trace/{response['request_id']}", key)
        measurement = {
            "run": run,
            "wall_ms": wall_ms,
            "backend_total_ms": trace.get("timings_ms", {}).get("total"),
            "stages_ms": [
                {"stage": item["stage"], "iteration": item.get("iteration"), "duration_ms": item["duration_ms"]}
                for item in trace.get("timings_ms", {}).get("stages", [])
            ],
            "retrieval_passes_ms": [
                item.get("timings_ms", {}) for item in trace.get("retrieval_iterations", [])
            ],
            "synthesis_ms": trace.get("synthesis_metadata", {}).get("timings_ms"),
            "synthesis_mode": trace.get("synthesis_metadata", {}).get("mode"),
            "citations_valid": response.get("citations_valid"),
        }
        measurements.append(measurement)
        print(json.dumps(measurement))

    print(json.dumps({
        "runs": len(measurements),
        "wall_median_ms": round(statistics.median(item["wall_ms"] for item in measurements), 2),
        "wall_max_ms": max(item["wall_ms"] for item in measurements),
    }))


if __name__ == "__main__":
    main()
