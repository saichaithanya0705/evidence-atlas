"""Focused tests for query-only telemetry semantics."""

from backend.app.services.telemetry import TelemetryStore


def test_telemetry_active_queries_return_to_zero() -> None:
    store = TelemetryStore()
    store.begin()
    assert store.snapshot()["active_queries"] == 1

    store.end(25.0)
    snapshot = store.snapshot()
    assert snapshot == {
        "total_requests": 1,
        "active_queries": 0,
        "failed_requests": 0,
        "avg_latency_ms": 25.0,
    }


def test_telemetry_counts_failed_queries() -> None:
    store = TelemetryStore()
    store.begin()
    store.end(10.0, failed=True)
    assert store.snapshot()["failed_requests"] == 1
