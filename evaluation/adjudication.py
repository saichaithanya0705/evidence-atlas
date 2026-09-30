"""Verify benchmark PMID/title labels against live NCBI PubMed records."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Iterable

import httpx
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@dataclass(frozen=True)
class FetchResult:
    records: dict[str, dict[str, str]]
    failed_pmids: list[str]
    failure_reasons: list[str]


@dataclass(frozen=True)
class AdjudicationResult:
    label_status: dict[str, str]
    verified_labels: int
    unverified_labels: int
    failed_pmids: list[str]
    live_efetch_verified_labels: int = 0
    web_source_verified_labels: int = 0
    label_evidence: dict[str, dict[str, str]] | None = None


class PubMedClient:
    """Small EFetch client with capped request rate, retries and ignored cache."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        email: str | None = None,
        cache_dir: str | Path | None = None,
        transport: Callable | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 2,
        timeout: float = 30,
    ) -> None:
        self._api_key = api_key
        self._email = email
        self._transport = transport or self._http_transport
        self._sleep = sleep
        self._retries = min(5, max(0, int(retries)))
        self._timeout = timeout
        self._last_request_at: float | None = None
        self.requests_per_second = 10 if api_key else 3
        self._cache_dir = Path(cache_dir or PROJECT_ROOT / "data" / "temporary" / "pubmed-cache")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _http_transport(url: str, params: dict[str, str], timeout: float) -> str:
        response = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": "EvidenceAtlas/1.0"})
        response.raise_for_status()
        return response.text

    def _params(self, pmids: list[str]) -> dict[str, str]:
        params = {"db": "pubmed", "id": ",".join(pmids), "rettype": "abstract", "retmode": "xml", "tool": "EvidenceAtlas"}
        if self._email:
            params["email"] = self._email
        if self._api_key:
            params["api_key"] = self._api_key
        return params

    def _cache_path(self, pmid: str) -> Path:
        return self._cache_dir / f"{pmid}.json"

    def _read_cache(self, pmid: str) -> dict[str, str] | None:
        path = self._cache_path(pmid)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("pmid") == pmid and isinstance(payload.get("title"), str):
                return payload
        except (OSError, ValueError, AttributeError):
            return None
        return None

    def _write_cache(self, record: dict[str, str]) -> None:
        destination = self._cache_path(record["pmid"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    def _rate_limit(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            wait = (1 / self.requests_per_second) - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _parse_xml(xml_text: str) -> dict[str, dict[str, str]]:
        root = ET.fromstring(xml_text)
        found: dict[str, dict[str, str]] = {}
        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//PMID")
            title_el = article.find(".//ArticleTitle")
            if pmid_el is None or pmid_el.text is None or title_el is None:
                continue
            pmid = pmid_el.text.strip()
            abstract = " ".join("".join(node.itertext()).strip() for node in article.findall(".//Abstract/AbstractText"))
            found[pmid] = {"pmid": pmid, "title": "".join(title_el.itertext()).strip(), "abstract": abstract}
        return found

    def fetch_records_partial(self, pmids: Iterable[str]) -> FetchResult:
        requested = list(dict.fromkeys(str(pmid) for pmid in pmids))
        records: dict[str, dict[str, str]] = {}
        missing: list[str] = []
        for pmid in requested:
            cached = self._read_cache(pmid)
            if cached is None:
                missing.append(pmid)
            else:
                records[pmid] = cached
        failed: list[str] = []
        failure_reasons: list[str] = []
        for offset in range(0, len(missing), 100):
            batch = missing[offset:offset + 100]
            batch_records = None
            last_reason = "request failed"
            for attempt in range(self._retries + 1):
                try:
                    self._rate_limit()
                    response = self._transport(EFETCH_URL, self._params(batch), self._timeout)
                    batch_records = self._parse_xml(response)
                    break
                except (OSError, httpx.HTTPError, ET.ParseError, ValueError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError):
                        last_reason = f"HTTP {exc.response.status_code}"
                    else:
                        last_reason = type(exc).__name__
                    if attempt < self._retries:
                        self._sleep(min(2 ** attempt, 8))
            if batch_records is None:
                failed.extend(batch)
                failure_reasons.append(last_reason)
                continue
            for pmid, record in batch_records.items():
                if pmid in batch:
                    records[pmid] = record
                    self._write_cache(record)
            failed.extend(pmid for pmid in batch if pmid not in records)
        return FetchResult(records=records, failed_pmids=sorted(set(failed)), failure_reasons=failure_reasons)

    def fetch_records(self, pmids: Iterable[str]) -> dict[str, dict[str, str]]:
        return self.fetch_records_partial(pmids).records


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.casefold())


def load_source_verification(artifact_path: str | Path, benchmark_path: str | Path) -> dict[str, dict[str, str]]:
    """Load independently checked PubMed page titles bound to exact benchmark bytes."""
    from evaluation.benchmark import file_checksum, load_benchmark, stable_checksum

    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != "1.0":
        raise ValueError("source verification artifact must have version 1.0")
    if payload.get("benchmark_checksum") != file_checksum(benchmark_path):
        raise ValueError("source verification artifact benchmark checksum mismatch")
    artifact_checksum = payload.get("verification_checksum")
    unsigned_payload = {key: value for key, value in payload.items() if key != "verification_checksum"}
    if not isinstance(artifact_checksum, str) or artifact_checksum != stable_checksum(unsigned_payload):
        raise ValueError("source verification artifact checksum mismatch")
    dataset = load_benchmark(benchmark_path)
    expected = {
        f"{entry.id}:{judgment.pmid}": (entry.id, judgment.pmid)
        for entry in dataset.entries for judgment in entry.judgments
    }
    rows = payload.get("records")
    if not isinstance(rows, list):
        raise ValueError("source verification artifact records must be a list")
    checked: dict[str, dict[str, str]] = {}
    now = datetime.now(timezone.utc)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("source verification record must be an object")
        entry_id, pmid = row.get("entry_id"), str(row.get("pmid", ""))
        key = f"{entry_id}:{pmid}"
        if key not in expected or expected[key] != (entry_id, pmid) or key in checked:
            raise ValueError("source verification contains unknown or duplicate label")
        required = ("source_title", "method", "checked_at", "source_url")
        if any(not isinstance(row.get(field), str) or not row[field].strip() for field in required):
            raise ValueError("source verification record has missing evidence fields")
        if row["method"] != "official_pubmed_page_title_check":
            raise ValueError("unsupported source verification method")
        if row["source_url"] != f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/":
            raise ValueError("source verification URL/PMID mismatch")
        try:
            timestamp = datetime.fromisoformat(row["checked_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid source verification checked_at") from exc
        if timestamp.tzinfo is None or timestamp > now or now - timestamp > timedelta(days=180):
            raise ValueError("source verification timestamp is missing timezone, future, or stale")
        checked[key] = {field: str(row[field]) for field in required}
        checked[key]["pmid"] = pmid
    if set(checked) != set(expected):
        raise ValueError("source verification artifact does not cover every benchmark label")
    return checked


def adjudicate_records(
    dataset,
    records: dict[str, dict[str, str] | str],
    failed_pmids: Iterable[str] = (),
    *,
    source_verification: dict[str, dict[str, str]] | None = None,
    corpus_titles: dict[str, str] | None = None,
) -> AdjudicationResult:
    statuses: dict[str, str] = {}
    verified = 0
    web_verified = 0
    live_verified = 0
    evidence: dict[str, dict[str, str]] = {}
    source_verification = source_verification or {}
    corpus_titles = corpus_titles or {}
    failed = set(failed_pmids)
    for entry in dataset.entries:
        for judgment in entry.judgments:
            key = f"{entry.id}:{judgment.pmid}"
            record = records.get(judgment.pmid)
            if record is None:
                checked = source_verification.get(key)
                if checked is None:
                    statuses[key] = "missing_source_verification_evidence"
                    continue
                if checked.get("pmid") != judgment.pmid or checked.get("source_url") != f"https://pubmed.ncbi.nlm.nih.gov/{judgment.pmid}/":
                    statuses[key] = "source_url_pmid_mismatch"
                    continue
                if _normalized_title(checked.get("source_title", "")) != _normalized_title(judgment.title):
                    statuses[key] = "source_title_mismatch"
                    continue
                local_title = corpus_titles.get(judgment.pmid)
                if local_title is None or _normalized_title(local_title) != _normalized_title(judgment.title):
                    statuses[key] = "corpus_title_mismatch"
                    continue
                if judgment.source_url != checked["source_url"]:
                    statuses[key] = "source_url_pmid_mismatch"
                    continue
                if checked.get("method") != "official_pubmed_page_title_check" or not checked.get("checked_at"):
                    statuses[key] = "missing_source_verification_evidence"
                    continue
                evidence[key] = dict(checked)
                evidence[key].update({"benchmark_title": judgment.title, "corpus_title": local_title})
                statuses[key] = "web_source_verified_efetch_unavailable"
                verified += 1
                web_verified += 1
                continue
            if record is None:
                statuses[key] = "fetch_failed" if judgment.pmid in failed else "missing_record"
                continue
            live_title = record if isinstance(record, str) else record.get("title", "")
            live_pmid = judgment.pmid if isinstance(record, str) else str(record.get("pmid", ""))
            if live_pmid != judgment.pmid:
                statuses[key] = "pmid_mismatch"
                continue
            if _normalized_title(judgment.title) != _normalized_title(live_title):
                statuses[key] = "title_mismatch"
                continue
            local_title = corpus_titles.get(judgment.pmid)
            if corpus_titles and (local_title is None or _normalized_title(local_title) != _normalized_title(judgment.title)):
                statuses[key] = "corpus_title_mismatch"
                continue
            statuses[key] = "verified"
            verified += 1
            live_verified += 1
            evidence[key] = {"method": "ncbi_efetch_title_check", "pmid": judgment.pmid, "source_title": live_title}
    return AdjudicationResult(statuses, verified, len(statuses) - verified, sorted(failed), live_verified, web_verified, evidence)


def load_corpus_pmids(corpus_path: str | Path) -> set[str]:
    frame = pd.read_parquet(corpus_path, columns=["pmid"])
    return {str(value) for value in frame["pmid"].dropna().tolist()}


def load_corpus_titles(corpus_path: str | Path) -> dict[str, str]:
    frame = pd.read_parquet(corpus_path, columns=["pmid", "title"])
    return {str(row.pmid): str(row.title) for row in frame.dropna(subset=["pmid", "title"]).itertuples(index=False)}


def atomic_write_json(path: str | Path, payload: dict) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp", delete=False) as stream:
            temp_name = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def validate_live(benchmark_path: Path, corpus_path: Path, output_path: Path, source_verification_path: Path | None = None) -> dict:
    from evaluation.benchmark import file_checksum, load_benchmark, validate_benchmark

    dataset = load_benchmark(benchmark_path)
    corpus_pmids = load_corpus_pmids(corpus_path)
    corpus_titles = load_corpus_titles(corpus_path)
    structural = validate_benchmark(dataset, corpus_pmids)
    all_pmids = sorted({judgment.pmid for entry in dataset.entries for judgment in entry.judgments})
    client = PubMedClient(api_key=os.environ.get("NCBI_API_KEY") or None, email=os.environ.get("NCBI_EMAIL") or None)
    fetch = client.fetch_records_partial(all_pmids)
    verification_path = source_verification_path or PROJECT_ROOT / "data" / "evaluation" / "benchmark_v2_source_verification.json"
    source_verification_error = None
    try:
        source_verification = load_source_verification(verification_path, benchmark_path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        source_verification = {}
        source_verification_error = str(exc)
    adjudication = adjudicate_records(
        dataset, fetch.records, fetch.failed_pmids, source_verification=source_verification,
        corpus_titles=corpus_titles,
    )
    payload = {
        "benchmark_version": dataset.version,
        "query_count": structural.query_count,
        "label_count": structural.label_count,
        "corpus_record_count": structural.corpus_record_count,
        "corpus_id_mismatches": structural.corpus_id_mismatches,
        "routes": sorted(structural.routes),
        "categories": sorted(structural.categories),
        "study_types": sorted(structural.study_types),
        "corpus_checksum": file_checksum(corpus_path),
        "benchmark_checksum": file_checksum(benchmark_path),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "web-assisted benchmark adjudication against official NCBI PubMed record pages",
        "label_status": adjudication.label_status,
        "label_evidence": adjudication.label_evidence,
        "verified_labels": adjudication.verified_labels,
        "unverified_labels": adjudication.unverified_labels,
        "failed_pmids": adjudication.failed_pmids,
        "efetch_status": "live" if not fetch.failed_pmids else ("partial" if fetch.records else "unavailable"),
        "efetch_failure_reasons": fetch.failure_reasons,
        "live_efetch_verified_labels": adjudication.live_efetch_verified_labels,
        "web_source_verified_labels": adjudication.web_source_verified_labels,
        "source_verification_status": "valid" if source_verification_error is None else "invalid_or_missing",
        "source_verification_error": source_verification_error,
        "source_verification_artifact": str(verification_path),
        "source_verification_checksum": file_checksum(verification_path) if source_verification_error is None else None,
        "validation_method": (
            "Live NCBI EFetch records verified against PubMed labels."
            if not fetch.failed_pmids
            else "NCBI EFetch was attempted; labels are verified only where a checksum-bound official PubMed page title check matches the benchmark and exact active-corpus title."
        ),
        "validation_errors": structural.errors,
    }
    payload["valid"] = structural.valid and adjudication.unverified_labels == 0
    payload["validation_status"] = (
        "valid_with_efetch_unavailable"
        if payload["valid"] and payload["efetch_status"] == "unavailable"
        else ("valid" if payload["valid"] else "invalid")
    )
    atomic_write_json(output_path, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-verification", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate_live(args.benchmark, args.corpus, args.output, args.source_verification)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: report[key] for key in ("valid", "query_count", "label_count", "corpus_record_count", "verified_labels", "unverified_labels")}, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
