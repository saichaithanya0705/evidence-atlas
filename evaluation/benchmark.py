"""Loading and deterministic validation for the frozen benchmark."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from evaluation.models import BenchmarkDataset


def stable_checksum(value: object) -> str:
    """Return SHA-256 over a canonical JSON representation."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_checksum(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_benchmark(path: str | Path) -> BenchmarkDataset:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BenchmarkDataset.model_validate(payload)


@dataclass(frozen=True)
class BenchmarkValidationReport:
    valid: bool
    query_count: int
    corpus_record_count: int
    corpus_id_mismatches: list[str]
    routes: set[str]
    categories: set[str]
    study_types: set[str]
    label_count: int
    errors: list[str]

    def to_dict(self) -> dict:
        result = asdict(self)
        for key in ("routes", "categories", "study_types"):
            result[key] = sorted(result[key])
        return result


def validate_benchmark(
    dataset: BenchmarkDataset,
    corpus_pmids: Iterable[str],
    *,
    enforce_size: bool = True,
) -> BenchmarkValidationReport:
    entries = dataset.entries
    errors: list[str] = []
    if enforce_size and not 30 <= len(entries) <= 50:
        errors.append("benchmark must contain between 30 and 50 entries")
    ids = [entry.id for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark entry IDs must be unique")
    routes = {entry.expected_route for entry in entries}
    categories = {entry.category for entry in entries}
    study_types = {entry.study_type for entry in entries}
    if enforce_size:
        missing_routes = {"SIMPLE", "MODERATE", "COMPLEX"} - routes
        if missing_routes:
            errors.append(f"missing expected routes: {', '.join(sorted(missing_routes))}")
        if len(categories) < 3:
            errors.append("benchmark must cover at least three biomedical categories")
        if len(study_types) < 3:
            errors.append("benchmark must cover at least three study types")
    corpus = {str(pmid) for pmid in corpus_pmids}
    relevant_pmids = {pmid for entry in entries for pmid in entry.relevant_pmids}
    mismatches = sorted(relevant_pmids - corpus)
    return BenchmarkValidationReport(
        valid=not errors and not mismatches,
        query_count=len(entries),
        corpus_record_count=len(corpus),
        corpus_id_mismatches=mismatches,
        routes=routes,
        categories=categories,
        study_types=study_types,
        label_count=sum(len(entry.judgments) for entry in entries),
        errors=errors,
    )
