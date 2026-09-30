"""Atomic, immutable evaluation report persistence and validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from evaluation.benchmark import stable_checksum

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_STATUSES = {"completed", "not_run", "failed"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temp = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def _canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _validate_report(report: Mapping[str, Any], run_id: str) -> None:
    if report.get("run_id") != run_id:
        raise ValueError("report run_id does not match destination")
    for field in ("benchmark_checksum", "corpus_checksum", "configuration_checksum"):
        if not isinstance(report.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", report[field]):
            raise ValueError(f"{field} must be a SHA-256 checksum")
    if not isinstance(report.get("variants"), list) or not isinstance(report.get("query_count"), int) or report["query_count"] < 0:
        raise ValueError("report requires variants and nonnegative query_count")
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("report metrics must be an object")
    for name, metric in metrics.items():
        if not isinstance(metric, Mapping) or metric.get("status") not in _STATUSES:
            raise ValueError(f"metric {name} requires a recognized status")
        status = metric["status"]
        if status == "completed" and (metric.get("value") is None or metric.get("reason") is not None):
            raise ValueError(f"completed metric {name} requires a value and no reason")
        if status != "completed" and (not isinstance(metric.get("reason"), str) or not metric["reason"].strip() or metric.get("value") is not None):
            raise ValueError(f"metric {name} with status {status} requires a reason and null value")


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# Evaluation report {report['run_id']}", "", f"- Run ID: `{report['run_id']}`", f"- Benchmark checksum: `{report['benchmark_checksum']}`", f"- Corpus checksum: `{report['corpus_checksum']}`", f"- Configuration checksum: `{report['configuration_checksum']}`", f"- Variants: `{', '.join(report['variants'])}`", f"- Query count: `{report['query_count']}`", "", "## Metrics", "", "| Metric | Status | Value | Reason |", "|---|---|---:|---|"]
    for name, metric in sorted(report["metrics"].items()):
        value = "n/a" if metric.get("value") is None else str(metric["value"])
        reason = str(metric.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {metric['status']} | {value} | {reason} |")
    return "\n".join(lines) + "\n"


def validate_report_agreement(report: Mapping[str, Any], markdown: str) -> None:
    required = [
        f"- Run ID: `{report['run_id']}`", f"- Benchmark checksum: `{report['benchmark_checksum']}`",
        f"- Corpus checksum: `{report['corpus_checksum']}`", f"- Configuration checksum: `{report['configuration_checksum']}`",
        f"- Variants: `{', '.join(report['variants'])}`", f"- Query count: `{report['query_count']}`",
    ]
    for name, metric in sorted(report["metrics"].items()):
        value = "n/a" if metric.get("value") is None else metric["value"]
        reason = str(metric.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        required.append(f"| {name} | {metric['status']} | {value} | {reason} |")
    if any(fragment not in markdown for fragment in required):
        raise ValueError("Markdown and JSON report disagree")


class ReportStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def publish(
        self,
        run_id: str,
        report: Mapping[str, Any],
        query_artifacts: Mapping[str, Any],
        *,
        expected_checksums: Mapping[str, str] | None = None,
        before_promotion: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if not _RUN_ID.fullmatch(run_id) or run_id in {".", ".."}:
            raise ValueError("invalid run_id")
        _validate_report(report, run_id)
        for field, expected in (expected_checksums or {}).items():
            if report.get(field) != expected:
                raise ValueError(f"{field} checksum mismatch")
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / run_id
        if destination.exists():
            raise FileExistsError(f"immutable report already exists: {run_id}")
        markdown = render_markdown(report)
        validate_report_agreement(report, markdown)
        if len(query_artifacts) != report["query_count"]:
            raise ValueError("query artifact count does not match report query_count")
        for filename in query_artifacts:
            if Path(filename).name != filename or not filename.endswith(".json"):
                raise ValueError("query artifact names must be flat .json filenames")

        staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=self.root))
        try:
            (staging / "queries").mkdir()
            report_bytes = _canonical_json(dict(report))
            markdown_bytes = markdown.encode("utf-8")
            _atomic_bytes(staging / "report.json", report_bytes)
            _atomic_bytes(staging / "report.md", markdown_bytes)
            artifact_hashes: dict[str, str] = {}
            for filename, artifact in sorted(query_artifacts.items()):
                encoded = _canonical_json(artifact)
                target = staging / "queries" / filename
                _atomic_bytes(target, encoded)
                artifact_hashes[filename] = hashlib.sha256(encoded).hexdigest()
            checksums = {
                "report.json": hashlib.sha256(report_bytes).hexdigest(),
                "report.md": hashlib.sha256(markdown_bytes).hexdigest(),
                "queries": artifact_hashes,
            }
            _atomic_bytes(staging / "checksums.json", _canonical_json(checksums))
            # Verify staged bytes before making the immutable directory visible.
            if _sha256(staging / "report.json") != checksums["report.json"] or _sha256(staging / "report.md") != checksums["report.md"]:
                raise ValueError("staged report checksum mismatch")
            if any(_sha256(staging / "queries" / name) != checksum for name, checksum in artifact_hashes.items()):
                raise ValueError("staged query artifact checksum mismatch")
            verify = json.loads((staging / "report.json").read_text(encoding="utf-8"))
            validate_report_agreement(verify, (staging / "report.md").read_text(encoding="utf-8"))
            if before_promotion is not None:
                before_promotion()
            # Windows can deny directory rename even within one volume when a
            # scanner briefly holds a child. Copy the already complete staging
            # tree, verify it, then promote only through the atomic manifest.
            try:
                shutil.copytree(staging, destination)
            except Exception:
                if destination.exists():
                    shutil.rmtree(destination)
                raise
            if _sha256(destination / "report.json") != checksums["report.json"] or _sha256(destination / "report.md") != checksums["report.md"]:
                shutil.rmtree(destination)
                raise ValueError("promoted report checksum mismatch")
            if any(_sha256(destination / "queries" / name) != checksum for name, checksum in artifact_hashes.items()):
                shutil.rmtree(destination)
                raise ValueError("promoted query artifact checksum mismatch")
            manifest_path = self.root / "manifest.json"
            manifest = {"latest_run_id": run_id, "runs": []}
            if manifest_path.exists():
                old = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["runs"] = [row for row in old.get("runs", []) if row.get("run_id") != run_id]
            manifest["runs"].append({"run_id": run_id, "report_checksum": checksums["report.json"], "checksums_checksum": stable_checksum(checksums)})
            _atomic_bytes(manifest_path, _canonical_json(manifest))
            return {"status": "completed", "run_id": run_id, "checksums": checksums}
        finally:
            if staging.exists():
                shutil.rmtree(staging)
