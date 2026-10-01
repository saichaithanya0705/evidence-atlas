r"""Measure real HTTP research latency and admin-only backend stage timings.

Run from the repository root while the API is running:
    .venv\Scripts\python scripts\benchmark_research_latency.py --runs 3

The script prints timing metadata only, never the administrator password or answer.
"""

from __future__ import annotations

import argparse
from getpass import getpass
from http.cookiejar import CookieJar
import json
import statistics
import time
from urllib.request import HTTPCookieProcessor, Request, build_opener


def _json_request(opener, url: str, body: dict | None = None, csrf: str = "") -> dict:
    origin = url.rsplit("/", 1)[0] if body is not None else ""
    headers = {}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Origin"] = origin
        if csrf:
            headers["X-CSRF-Token"] = csrf
        data = json.dumps(body).encode("utf-8")
    with opener.open(Request(url, data=data, headers=headers), timeout=180) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="administrator")
    parser.add_argument("--query", default="Empagliflozin kidney outcomes in type 2 diabetes")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-loops", type=int, default=0)
    parser.add_argument("--year-min", type=int)
    parser.add_argument("--year-max", type=int)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    base = args.url.rstrip("/")
    cookies = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookies))
    _json_request(opener, f"{base}/auth/login", {"username": args.username, "password": getpass("Administrator password: ")})
    csrf = next((cookie.value for cookie in cookies if cookie.name == "evidence_csrf"), "")
    if not csrf:
        parser.error("Sign-in did not provide a request token")

    measurements = []
    for run in range(1, args.runs + 1):
        started = time.perf_counter()
        response = _json_request(
            opener,
            f"{base}/research",
            {
                "query": args.query,
                "max_loops": args.max_loops,
                "year_min": args.year_min,
                "year_max": args.year_max,
            }, csrf,
        )
        wall_ms = round((time.perf_counter() - started) * 1000, 2)
        trace = _json_request(opener, f"{base}/trace/{response['request_id']}")
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
