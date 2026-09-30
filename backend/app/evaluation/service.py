"""Fail-closed, read-only access to complete promoted evaluation reports."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from backend.app.core.config import get_settings
from evaluation.benchmark import stable_checksum
from evaluation.reporting import validate_report_agreement

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VARIANTS = {"dense_only", "hybrid", "reranked", "agentic"}
_SCENARIOS = {"irrelevant_context", "conflicting_evidence", "incomplete_evidence", "misleading_context", "noisy_query", "acronym_query", "filter_pressure"}
_FAILURES = {"retriever_miss", "context_noise", "missing_evidence", "extraction_miss", "unsupported_generation", "citation_mismatch", "incomplete_answer"}
_METRIC_STATUSES = {"completed", "not_run", "failed"}
_METRIC_SUFFIXES = {
    "filter_accuracy", "latency_ms", "route_accuracy", "route_confusion", "subquestion_coverage",
    "answer_completeness", "span_precision", "attribution_precision", "supported_claim_rate",
    "citation_validity", "citation_precision", "robustness",
    *(f"ragas.{name}" for name in ("faithfulness", "context_precision", "context_recall", "context_entity_recall", "answer_relevancy", "answer_correctness")),
}
_ROBUSTNESS_METRICS = {"query_context_coverage", "context_precision", "candidate_filter_compliance"}


class _StrictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationSummary(_StrictResponse):
    run_id: str
    report_checksum: str
    benchmark_checksum: str
    corpus_checksum: str
    configuration_checksum: str
    variants: list[str]
    query_count: int
    metrics: dict[str, dict[str, Any]]
    latency: dict[str, dict[str, Any]]
    failure_categories: dict[str, int]
    robustness: dict[str, dict[str, Any]]
    limitations: list[str]


class EvaluationQuery(_StrictResponse):
    query_id: str
    variants: dict[str, dict[str, Any]]


class EvaluationReport(EvaluationSummary):
    queries: list[EvaluationQuery]


class EvaluationList(_StrictResponse):
    items: list[EvaluationSummary]


class _InvalidBundle(Exception):
    pass


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _contained_digest(root: Path, path: Path) -> str:
    if path.is_symlink():
        raise _InvalidBundle
    resolved = path.resolve(strict=False)
    if not _inside(root, resolved) or not path.is_file():
        raise _InvalidBundle
    return _digest(path)


def _safe_identifier(run_id: str) -> bool:
    return bool(_RUN_ID.fullmatch(run_id)) and run_id not in {".", ".."} and "/" not in run_id and "\\" not in run_id and Path(run_id).name == run_id


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _InvalidBundle from exc


def _json_file(root: Path, path: Path) -> Any:
    if path.is_symlink():
        raise _InvalidBundle
    resolved = path.resolve(strict=False)
    if not _inside(root, resolved) or not path.is_file():
        raise _InvalidBundle
    return _read_json(path)


def _report_root() -> Path:
    return Path(get_settings().EVALUATION_REPORTS_DIR).resolve(strict=False)


def _metric_value(name: str, value: Any) -> Any:
    if value is None or isinstance(value, (int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            raise _InvalidBundle
        return value
    if not isinstance(value, Mapping):
        raise _InvalidBundle
    if name.endswith(".latency_ms") or name == "latency":
        return {key: value[key] for key in ("count", "min", "median", "mean", "max") if isinstance(value.get(key), (int, float)) and math.isfinite(value[key])}
    if name.endswith(".robustness") or name == "robustness":
        result: dict[str, Any] = {}
        for field in ("scenario_count", "query_count"):
            if isinstance(value.get(field), int):
                result[field] = value[field]
        scenarios = value.get("scenarios")
        if isinstance(scenarios, Mapping):
            selected = {}
            for scenario, details in scenarios.items():
                if scenario not in _SCENARIOS or not isinstance(details, Mapping):
                    continue
                deltas = details.get("mean_metric_deltas")
                if isinstance(deltas, Mapping):
                    selected[scenario] = {metric: float(delta) for metric, delta in deltas.items() if metric in _ROBUSTNESS_METRICS and isinstance(delta, (int, float)) and math.isfinite(delta)}
            result["scenarios"] = selected
        return result
    raise _InvalidBundle


def _is_metric_name(name: str, variants: list[str]) -> bool:
    if "." not in name:
        return False
    variant, suffix = name.split(".", 1)
    return variant in variants and (suffix in _METRIC_SUFFIXES or bool(re.fullmatch(r"(?:recall|precision|mrr|ndcg)@\d+", suffix)))


def _valid_query_metric(name: Any) -> bool:
    return isinstance(name, str) and (name in {"filter_accuracy", "route_accuracy", "subquestion_coverage", "answer_completeness", "span_precision", "attribution_precision", "supported_claim_rate", "citation_validity", "citation_precision", *_ROBUSTNESS_METRICS} or bool(re.fullmatch(r"(?:recall|precision|mrr|ndcg)@\d+", name)))


def _valid_robustness_metric(name: Any) -> bool:
    return isinstance(name, str) and name in _ROBUSTNESS_METRICS


def _metric_records(metrics: Any, variants: list[str]) -> dict[str, Any]:
    if not isinstance(metrics, Mapping):
        raise _InvalidBundle
    result = {}
    for name, metric in metrics.items():
        if not isinstance(name, str) or len(name) > 120 or not _is_metric_name(name, variants) or not isinstance(metric, Mapping):
            raise _InvalidBundle
        status, value, reason = metric.get("status"), metric.get("value"), metric.get("reason")
        if status not in _METRIC_STATUSES:
            raise _InvalidBundle
        if status == "completed" and (value is None or reason is not None):
            raise _InvalidBundle
        if status != "completed" and (value is not None or not isinstance(reason, str) or not reason.strip()):
            raise _InvalidBundle
        result[name] = {"status": status, "value": _metric_value(name, value), "reason": (reason.strip()[:300] if isinstance(reason, str) else None)}
    return result


def _robustness(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _InvalidBundle
    status = value.get("status")
    if status not in _METRIC_STATUSES:
        raise _InvalidBundle
    result: dict[str, Any] = {"status": status}
    reason = value.get("reason")
    if status != "completed":
        if not isinstance(reason, str) or not reason.strip():
            raise _InvalidBundle
        result["reason"] = reason.strip()[:300]
        return result
    raw = value.get("value")
    result["value"] = _metric_value("robustness", raw)
    return result


def _project_report(report: Mapping[str, Any], report_checksum: str) -> dict[str, Any]:
    run_id = report.get("run_id")
    variants = report.get("variants")
    if not _safe_identifier(run_id) or not isinstance(variants, list) or not variants or any(item not in _VARIANTS for item in variants) or len(set(variants)) != len(variants):
        raise _InvalidBundle
    for field in ("benchmark_checksum", "corpus_checksum", "configuration_checksum"):
        if not isinstance(report.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", report[field]):
            raise _InvalidBundle
    if not isinstance(report.get("query_count"), int) or report["query_count"] < 0:
        raise _InvalidBundle
    latency = report.get("latency", {})
    if not isinstance(latency, Mapping):
        raise _InvalidBundle
    projected_latency = {variant: _metric_value("latency", value) for variant, value in latency.items() if variant in variants and isinstance(value, Mapping)}
    failures = report.get("failure_categories", {})
    if not isinstance(failures, Mapping):
        raise _InvalidBundle
    projected_failures = {name: count for name, count in failures.items() if name in _FAILURES and isinstance(count, int) and count >= 0}
    robustness = report.get("robustness", {})
    if not isinstance(robustness, Mapping):
        raise _InvalidBundle
    projected_robustness = {variant: _robustness(value) for variant, value in robustness.items() if variant in variants}
    limitations = report.get("limitations", [])
    if not isinstance(limitations, list) or any(not isinstance(item, str) for item in limitations):
        raise _InvalidBundle
    return {
        "run_id": run_id,
        "report_checksum": report_checksum,
        "benchmark_checksum": report["benchmark_checksum"],
        "corpus_checksum": report["corpus_checksum"],
        "configuration_checksum": report["configuration_checksum"],
        "variants": list(variants),
        "query_count": report["query_count"],
        "metrics": _metric_records(report.get("metrics"), variants),
        "latency": projected_latency,
        "failure_categories": projected_failures,
        "robustness": projected_robustness,
        "limitations": [item.strip()[:300] for item in limitations[:30]],
    }


def _query_projection(root: Path, query_dir: Path, checksummed_queries: Mapping[str, str], variants: list[str], expected_count: int) -> list[dict[str, Any]]:
    if len(checksummed_queries) != expected_count:
        raise _InvalidBundle
    rows = []
    for filename in sorted(checksummed_queries):
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith(".json") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json", filename):
            raise _InvalidBundle
        path = query_dir / filename
        if _contained_digest(root, path) != checksummed_queries[filename]:
            raise _InvalidBundle
        artifact = _json_file(root, path)
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("query_id"), str):
            raise _InvalidBundle
        raw_variants = artifact.get("variants")
        if not isinstance(raw_variants, Mapping):
            raise _InvalidBundle
        projected_variants = {}
        for variant in variants:
            detail = raw_variants.get(variant)
            if not isinstance(detail, Mapping):
                continue
            item: dict[str, Any] = {}
            if "metrics" in detail:
                metrics = detail["metrics"]
                if not isinstance(metrics, Mapping):
                    raise _InvalidBundle
                item["metrics"] = {name: _metric_value(name, value) for name, value in metrics.items() if _valid_query_metric(name) and isinstance(value, (int, float, bool))}
            diagnostics = detail.get("diagnostics", [])
            if not isinstance(diagnostics, list):
                raise _InvalidBundle
            item["diagnostics"] = [
                {"category": diagnostic["category"], **({"reason": diagnostic["reason"].strip()[:300]} if isinstance(diagnostic.get("reason"), str) else {})}
                for diagnostic in diagnostics
                if isinstance(diagnostic, Mapping) and diagnostic.get("category") in _FAILURES
            ]
            if "robustness" in detail:
                raw_robustness = detail["robustness"]
                if not isinstance(raw_robustness, Mapping):
                    raise _InvalidBundle
                scenarios = raw_robustness.get("scenarios", {})
                safe_scenarios = {}
                if isinstance(scenarios, Mapping):
                    for scenario, result in scenarios.items():
                        if scenario not in _SCENARIOS or not isinstance(result, Mapping):
                            continue
                        deltas = result.get("metric_deltas", {})
                        if isinstance(deltas, Mapping):
                            safe_scenarios[scenario] = {name: float(delta) for name, delta in deltas.items() if _valid_robustness_metric(name) and isinstance(delta, (int, float)) and math.isfinite(delta)}
                item["robustness"] = {"status": raw_robustness.get("status", "completed"), "scenarios": safe_scenarios}
            projected_variants[variant] = item
        rows.append({"query_id": artifact["query_id"][:128], "variants": projected_variants})
    return rows


def _load_bundle(root: Path, run_id: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    run_dir = root / run_id
    if run_dir.is_symlink() or not run_dir.is_dir() or not _inside(root, run_dir.resolve(strict=False)):
        raise _InvalidBundle
    report_path = run_dir / "report.json"
    checksums_path = run_dir / "checksums.json"
    report = _json_file(root, report_path)
    checksums = _json_file(root, checksums_path)
    if not isinstance(report, Mapping) or report.get("run_id") != run_id or not isinstance(checksums, Mapping):
        raise _InvalidBundle
    report_checksum = _digest(report_path)
    checksums_checksum = stable_checksum(checksums)
    if entry.get("report_checksum") != report_checksum or entry.get("checksums_checksum") != checksums_checksum:
        raise _InvalidBundle
    if checksums.get("report.json") != report_checksum:
        raise _InvalidBundle
    markdown = run_dir / "report.md"
    if checksums.get("report.md") != _contained_digest(root, markdown):
        raise _InvalidBundle
    try:
        validate_report_agreement(report, markdown.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise _InvalidBundle from exc
    query_hashes = checksums.get("queries")
    if not isinstance(query_hashes, Mapping):
        raise _InvalidBundle
    if set(checksums) != {"report.json", "report.md", "queries"}:
        raise _InvalidBundle
    result = _project_report(report, report_checksum)
    result["queries"] = _query_projection(root, run_dir / "queries", query_hashes, result["variants"], result["query_count"])
    return result


def _manifest_entries(root: Path) -> tuple[list[Mapping[str, Any]], str | None]:
    manifest_path = root / "manifest.json"
    if manifest_path.is_symlink():
        raise _InvalidBundle
    if not manifest_path.exists():
        return [], None
    manifest = _json_file(root, manifest_path)
    if not isinstance(manifest, Mapping) or not isinstance(manifest.get("runs"), list):
        raise _InvalidBundle
    latest = manifest.get("latest_run_id")
    entries = manifest["runs"]
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not _safe_identifier(entry.get("run_id")) or entry["run_id"] in seen:
            raise _InvalidBundle
        seen.add(entry["run_id"])
        for field in ("report_checksum", "checksums_checksum"):
            if not isinstance(entry.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", entry[field]):
                raise _InvalidBundle
    if latest is not None and latest not in seen:
        raise _InvalidBundle
    return entries, latest


def _fail_closed() -> HTTPException:
    return HTTPException(status_code=503, detail="Evaluation reports are unavailable")


def list_evaluations() -> dict[str, Any]:
    root = _report_root()
    if not root.exists():
        return {"items": []}
    try:
        entries, latest = _manifest_entries(root)
        values = [_load_bundle(root, entry["run_id"], entry) for entry in entries]
        values.sort(key=lambda report: (report["run_id"] == latest, report["run_id"]), reverse=True)
        return {"items": [{key: value for key, value in report.items() if key != "queries"} for report in values]}
    except (_InvalidBundle, OSError, ValueError, TypeError, KeyError):
        raise _fail_closed() from None


def get_evaluation(run_id: str) -> dict[str, Any]:
    if not _safe_identifier(run_id):
        raise HTTPException(status_code=400, detail="Invalid evaluation run identifier")
    root = _report_root()
    try:
        entries, _ = _manifest_entries(root)
        entry = next((item for item in entries if item["run_id"] == run_id), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="Evaluation report not found")
        return _load_bundle(root, run_id, entry)
    except HTTPException:
        raise
    except (_InvalidBundle, OSError, ValueError, TypeError, KeyError):
        raise _fail_closed() from None
