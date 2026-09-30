from __future__ import annotations

import json

import pytest


def _report(run_id="run-1", **extra):
    result = {
        "run_id": run_id,
        "benchmark_checksum": "a" * 64,
        "corpus_checksum": "b" * 64,
        "configuration_checksum": "c" * 64,
        "variants": ["dense_only"],
        "query_count": 1,
        "metrics": {"recall@5": {"status": "completed", "value": 0.5, "reason": None}, "faithfulness": {"status": "not_run", "value": None, "reason": "credentials missing"}},
    }
    result.update(extra)
    return result


def test_report_promotion_writes_immutable_checksummed_run_and_manifest_atomically(tmp_path):
    from evaluation.reporting import ReportStore

    store = ReportStore(tmp_path)
    result = store.publish("run-1", _report(), {"q1.json": {"query_id": "q1", "score": 0.5}})
    run_dir = tmp_path / "run-1"
    assert result["status"] == "completed"
    assert json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["run_id"] == "run-1"
    assert (run_dir / "queries" / "q1.json").exists()
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["latest_run_id"] == "run-1"
    original = (run_dir / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        store.publish("run-1", _report(), {})
    assert (run_dir / "report.json").read_bytes() == original


def test_report_json_and_markdown_agree_on_identity_counts_and_metric_status(tmp_path):
    from evaluation.reporting import render_markdown, validate_report_agreement

    report = _report()
    markdown = render_markdown(report)
    validate_report_agreement(report, markdown)
    with pytest.raises(ValueError, match="disagree"):
        validate_report_agreement(report, markdown.replace("run-1", "run-2"))


def test_incomplete_or_checksum_mismatched_run_is_never_promoted(tmp_path):
    from evaluation.reporting import ReportStore

    store = ReportStore(tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        store.publish("run-1", _report(benchmark_checksum="wrong"), {"q1.json": {"query_id": "q1"}}, expected_checksums={"benchmark_checksum": "a" * 64})
    assert not (tmp_path / "manifest.json").exists()
    store.publish("run-1", _report("run-1"), {"q1.json": {"query_id": "q1"}})
    with pytest.raises(RuntimeError, match="interrupted"):
        store.publish("run-2", _report("run-2"), {"q1.json": {"query_id": "q1"}}, before_promotion=lambda: (_ for _ in ()).throw(RuntimeError("interrupted")))
    assert json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))["latest_run_id"] == "run-1"
    assert not (tmp_path / "run-2").exists()


def test_metric_records_require_status_and_reason_for_noncompleted_results(tmp_path):
    from evaluation.reporting import ReportStore

    invalid = _report(metrics={"faithfulness": {"status": "not_run", "value": None, "reason": None}})
    with pytest.raises(ValueError, match="reason"):
        ReportStore(tmp_path).publish("run-1", invalid, {"q1.json": {"query_id": "q1"}})


def test_markdown_metric_values_remain_agreeing_after_json_round_trip():
    from evaluation.reporting import render_markdown, validate_report_agreement

    report = _report(metrics={"latency": {"status": "completed", "value": {"count": 1, "min": 10.0, "median": 12.0, "mean": 12.0, "max": 14.0}, "reason": None}})
    markdown = render_markdown(report)
    validate_report_agreement(json.loads(json.dumps(report, sort_keys=True)), markdown)


def test_admin_report_projection_exposes_only_documented_metrics_and_fields():
    from backend.app.evaluation.service import _InvalidBundle, _project_report

    report = {
        "run_id": "run-1",
        "benchmark_checksum": "a" * 64,
        "corpus_checksum": "b" * 64,
        "configuration_checksum": "c" * 64,
        "variants": ["dense_only", "hybrid", "reranked", "agentic"],
        "query_count": 0,
        "metrics": {"dense_only.recall@5": {"status": "completed", "value": 0.5, "reason": None}},
        "latency": {},
        "failure_categories": {},
        "robustness": {},
        "limitations": [],
        "prompt": "must not appear",
        "model_output": "must not appear",
    }
    projected = _project_report(report, "d" * 64)
    assert set(projected) == {
        "run_id", "report_checksum", "benchmark_checksum", "corpus_checksum", "configuration_checksum",
        "variants", "query_count", "metrics", "latency", "failure_categories", "robustness", "limitations",
        "answer_status_distribution",
    }
    assert projected["metrics"] == {"dense_only.recall@5": {"status": "completed", "value": 0.5, "reason": None}}
    report["metrics"]["dense_only.prompt"] = {"status": "completed", "value": "private prompt", "reason": None}
    with pytest.raises(_InvalidBundle):
        _project_report(report, "d" * 64)
