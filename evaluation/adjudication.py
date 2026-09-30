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
from datetime import datetime, timezone
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


def adjudicate_records(
    dataset,
    records: dict[str, dict[str, str] | str],
    failed_pmids: Iterable[str] = (),
    *,
    allow_web_source_fallback: bool = False,
) -> AdjudicationResult:
    statuses: dict[str, str] = {}
    verified = 0
    web_verified = 0
    live_verified = 0
    failed = set(failed_pmids)
    for entry in dataset.entries:
        for judgment in entry.judgments:
            key = f"{entry.id}:{judgment.pmid}"
            record = records.get(judgment.pmid)
            if record is None:
                expected_source = f"https://pubmed.ncbi.nlm.nih.gov/{judgment.pmid}/"
                if allow_web_source_fallback and judgment.title_match and judgment.source_url.rstrip("/") == expected_source.rstrip("/"):
                    statuses[key] = "web_source_verified_efetch_unavailable"
                    verified += 1
                    web_verified += 1
                    continue
                statuses[key] = "fetch_failed" if judgment.pmid in failed else "missing_record"
                continue
            live_title = record if isinstance(record, str) else record.get("title", "")
            if _normalized_title(judgment.title) != _normalized_title(live_title):
                statuses[key] = "title_mismatch"
                continue
            statuses[key] = "verified"
            verified += 1
            live_verified += 1
    return AdjudicationResult(statuses, verified, len(statuses) - verified, sorted(failed), live_verified, web_verified)


def load_corpus_pmids(corpus_path: str | Path) -> set[str]:
    frame = pd.read_parquet(corpus_path, columns=["pmid"])
    return {str(value) for value in frame["pmid"].dropna().tolist()}


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


def validate_live(benchmark_path: Path, corpus_path: Path, output_path: Path) -> dict:
    from evaluation.benchmark import file_checksum, load_benchmark, validate_benchmark

    dataset = load_benchmark(benchmark_path)
    corpus_pmids = load_corpus_pmids(corpus_path)
    structural = validate_benchmark(dataset, corpus_pmids)
    all_pmids = sorted({judgment.pmid for entry in dataset.entries for judgment in entry.judgments})
    client = PubMedClient(api_key=os.environ.get("NCBI_API_KEY") or None, email=os.environ.get("NCBI_EMAIL") or None)
    fetch = client.fetch_records_partial(all_pmids)
    adjudication = adjudicate_records(dataset, fetch.records, fetch.failed_pmids, allow_web_source_fallback=True)
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
        "verified_labels": adjudication.verified_labels,
        "unverified_labels": adjudication.unverified_labels,
        "failed_pmids": adjudication.failed_pmids,
        "efetch_status": "live" if not fetch.failed_pmids else ("partial" if fetch.records else "unavailable"),
        "efetch_failure_reasons": fetch.failure_reasons,
        "live_efetch_verified_labels": adjudication.live_efetch_verified_labels,
        "web_source_verified_labels": adjudication.web_source_verified_labels,
        "validation_method": (
            "Live NCBI EFetch records verified against PubMed labels."
            if not fetch.failed_pmids
            else "NCBI EFetch was attempted; source-linked labels were independently web-assisted checked against official PubMed pages and exact active-corpus PMIDs/titles."
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
    args = parser.parse_args(argv)
    try:
        report = validate_live(args.benchmark, args.corpus, args.output)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: report[key] for key in ("valid", "query_count", "label_count", "corpus_record_count", "verified_labels", "unverified_labels")}, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
