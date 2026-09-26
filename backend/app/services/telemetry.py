"""Small in-process telemetry store for the local FastAPI service."""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Dict


class TelemetryStore:
    """Track bounded request latency without external infrastructure."""

    def __init__(self, window_size: int = 500) -> None:
        self._lock = Lock()
        self._latencies_ms: deque[float] = deque(maxlen=window_size)
        self._total_requests = 0
        self._active_queries = 0
        self._failures = 0

    def begin(self) -> None:
        with self._lock:
            self._total_requests += 1
            self._active_queries += 1

    def end(self, latency_ms: float, failed: bool = False) -> None:
        with self._lock:
            self._active_queries = max(0, self._active_queries - 1)
            self._latencies_ms.append(max(0.0, latency_ms))
            if failed:
                self._failures += 1

    def snapshot(self) -> Dict[str, float | int]:
        with self._lock:
            values = list(self._latencies_ms)
            return {
                "total_requests": self._total_requests,
                "active_queries": self._active_queries,
                "failed_requests": self._failures,
                "avg_latency_ms": round(sum(values) / len(values), 2) if values else 0.0,
            }


telemetry = TelemetryStore()
