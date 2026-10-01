"""Build a real PubMed abstract corpus from the PubMed Phrases archive.

The archive supplies phrase-to-PMID mappings, not abstract text.  This script
uses those PMIDs to fetch canonical PubMed XML through NCBI E-utilities, then
writes the CSV schema consumed by the project's normal indexing pipeline.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import hashlib
import html
import json
import os
import re
import shutil
import ssl
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
NCBI_SOURCE = "NCBI PubMed E-utilities"
EUROPE_PMC_SOURCE = "Europe PMC REST API"
FIELDS = [
    "pmid", "title", "abstract", "authors", "journal", "publication_date",
    "publication_date_raw", "year", "study_type", "publication_types",
    "mesh_terms", "keywords", "doi",
]

BROAD_MEDICAL_QUERIES = {
    "mrna_vaccines_respiratory_2020_plus": (
        '("mRNA vaccine"[Title/Abstract] OR "messenger RNA vaccine"[Title/Abstract]) '
        'AND ("Respiratory Tract Infections"[Mesh] OR COVID-19[Mesh] OR respiratory[Title/Abstract]) '
        'AND ("2020/01/01"[Date - Publication] : "3000"[Date - Publication])'
    ),
    "diabetes_cardiovascular_2020_plus": (
        '("Diabetes Mellitus"[Mesh] OR diabetes[Title/Abstract]) '
        'AND ("Cardiovascular Diseases"[Mesh] OR cardiovascular[Title/Abstract]) '
        'AND ("2020/01/01"[Date - Publication] : "3000"[Date - Publication])'
    ),
    "chronic_kidney_disease_sglt2": (
        '("Renal Insufficiency, Chronic"[Mesh] OR "chronic kidney disease"[Title/Abstract]) '
        'AND ("Sodium-Glucose Transporter 2 Inhibitors"[Mesh] OR "SGLT2 inhibitor"[Title/Abstract])'
    ),
    "comparative_treatments_2020_plus": (
        '("Comparative Effectiveness Research"[Mesh] OR "comparative effectiveness"[Title/Abstract] '
        'OR "treatment comparison"[Title/Abstract]) '
        'AND ("2020/01/01"[Date - Publication] : "3000"[Date - Publication])'
    ),
}


def _get_ssl_context() -> ssl.SSLContext:
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def phrase_pmids(archive: Path, phrases: list[str]) -> dict[str, list[str]]:
    wanted = {phrase.casefold(): phrase for phrase in phrases}
    found: dict[str, list[str]] = {}
    with tarfile.open(archive, "r:gz") as bundle:
        member = bundle.getmember("all_dictionary.pmid")
        stream = bundle.extractfile(member)
        if stream is None:
            raise RuntimeError("all_dictionary.pmid could not be opened")
        for raw_line in stream:
            phrase, separator, values = raw_line.decode("utf-8", errors="replace").rstrip().partition("|")
            key = phrase.casefold()
            if separator and key in wanted:
                found[wanted[key]] = [value for value in values.split("|") if value.isdigit()]
                if len(found) == len(wanted):
                    break
    missing = [phrase for phrase in phrases if phrase not in found]
    if missing:
        raise ValueError("Phrases not found in archive: " + ", ".join(missing))
    return found


def select_pmids(mapping: dict[str, list[str]], limit: int) -> list[str]:
    ordered_lists = list(mapping.values())
    shared = set(ordered_lists[0])
    for values in ordered_lists[1:]:
        shared.intersection_update(values)
    selected = [pmid for pmid in ordered_lists[0] if pmid in shared][:limit]
    seen = set(selected)
    if len(selected) >= limit:
        return selected
    for values in ordered_lists:
        for pmid in values:
            if pmid not in seen:
                selected.append(pmid)
                seen.add(pmid)
            if len(selected) >= limit:
                return selected
    return selected[:limit]


def select_pmids_balanced(mapping: dict[str, list[str]], limit: int) -> list[str]:
    """Round-robin PMID lists so each retrieval seed retains representation."""
    selected: list[str] = []
    seen: set[str] = set()
    max_length = max((len(values) for values in mapping.values()), default=0)
    for index in range(max_length):
        for values in mapping.values():
            if index >= len(values):
                continue
            pmid = values[index]
            if pmid in seen:
                continue
            selected.append(pmid)
            seen.add(pmid)
            if len(selected) >= limit:
                return selected
    return selected


def search_pubmed_pmids(query: str, limit: int, email: str = "", attempts: int = 4) -> list[str]:
    """Resolve a PubMed query to PMIDs through NCBI ESearch with verified TLS."""
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "xml",
        "retmax": str(limit),
        "sort": "pub date",
        "tool": "evidence-atlas-capstone",
    }
    if email:
        params["email"] = email
    request = Request(
        ESEARCH_URL + "?" + urlencode(params),
        headers={"User-Agent": "EvidenceAtlasCapstone/1.0"},
    )
    context = _get_ssl_context()
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=90, context=context) as response:
                root = ET.fromstring(response.read())
                return [node.text for node in root.findall(".//IdList/Id") if node.text and node.text.isdigit()]
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError("PubMed search request exhausted its retry budget")


def fetch_pubmed_xml(pmids: list[str], email: str = "", attempts: int = 4) -> bytes:
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
        "tool": "evidence-atlas-capstone",
    }
    if email:
        params["email"] = email
    request = Request(
        EFETCH_URL,
        data=urlencode(params).encode("ascii"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "EvidenceAtlasCapstone/1.0",
        },
    )
    context = _get_ssl_context()
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=90, context=context) as response:
                return response.read()
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))))
    raise RuntimeError("PubMed request exhausted its retry budget")


def parse_articles(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    records: list[dict[str, str]] = []
    for item in root.findall(".//PubmedArticle"):
        citation = item.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        if citation is None or article is None:
            continue
        pmid = _text(citation.find("PMID"))
        title = _text(article.find("ArticleTitle"))
        abstract_parts = []
        for part in article.findall("Abstract/AbstractText"):
            body = _text(part)
            label = part.attrib.get("Label", "").strip()
            if body:
                abstract_parts.append(f"{label}: {body}" if label else body)
        abstract = " ".join(abstract_parts)
        if not pmid or not title or not abstract:
            continue

        authors = []
        for author in article.findall("AuthorList/Author"):
            collective = _text(author.find("CollectiveName"))
            personal = " ".join(
                value for value in (_text(author.find("ForeName")), _text(author.find("LastName"))) if value
            )
            if collective or personal:
                authors.append(collective or personal)

        pubdate = article.find("Journal/JournalIssue/PubDate")
        publication_date_raw = " ".join(
            value for value in (
                _text(pubdate.find("Year")) if pubdate is not None else "",
                _text(pubdate.find("Month")) if pubdate is not None else "",
                _text(pubdate.find("Day")) if pubdate is not None else "",
                _text(pubdate.find("Season")) if pubdate is not None else "",
                _text(pubdate.find("MedlineDate")) if pubdate is not None else "",
            ) if value
        )
        year = _text(pubdate.find("Year")) if pubdate is not None else ""
        medline_date = _text(pubdate.find("MedlineDate")) if pubdate is not None else ""
        if not year and medline_date:
            match = re.search(r"\b(?:19|20)\d{2}\b", medline_date)
            year = match.group(0) if match else ""
        publication_date = "-".join(
            value for value in (
                year,
                _text(pubdate.find("Month")) if pubdate is not None else "",
                _text(pubdate.find("Day")) if pubdate is not None else "",
            ) if value
        ) or medline_date

        publication_types = [_text(node) for node in article.findall("PublicationTypeList/PublicationType")]
        mesh_terms = [_text(node) for node in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")]
        keywords = [_text(node) for node in citation.findall("KeywordList/Keyword")]
        doi = ""
        for identifier in item.findall("PubmedData/ArticleIdList/ArticleId"):
            if identifier.attrib.get("IdType", "").casefold() == "doi":
                doi = _text(identifier)
                break

        records.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": "; ".join(authors),
            "journal": _text(article.find("Journal/Title")),
            "publication_date": publication_date,
            "publication_date_raw": publication_date_raw,
            "year": year,
            "study_type": publication_types[0] if publication_types else "Other",
            "publication_types": "; ".join(publication_types),
            "mesh_terms": "; ".join(mesh_terms),
            "keywords": "; ".join(keywords),
            "doi": doi,
        })
    return records


def _plain_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return " ".join(html.unescape(text).split())


def parse_europe_pmc_results(payload: bytes) -> list[dict[str, str]]:
    results = json.loads(payload.decode("utf-8")).get("resultList", {}).get("result", [])
    records: list[dict[str, str]] = []
    for item in results:
        pmid = str(item.get("pmid") or item.get("id") or "")
        title = _plain_text(item.get("title"))
        abstract = _plain_text(item.get("abstractText"))
        if not pmid or not title or not abstract:
            continue

        journal_info = item.get("journalInfo") or {}
        journal = journal_info.get("journal") or {}
        publication_date_raw = str(
            journal_info.get("dateOfPublication") or item.get("firstPublicationDate") or ""
        )
        publication_date = str(
            item.get("firstPublicationDate")
            or journal_info.get("printPublicationDate")
            or publication_date_raw
        )
        year = str(journal_info.get("yearOfPublication") or item.get("pubYear") or "")
        publication_types = (item.get("pubTypeList") or {}).get("pubType", [])
        mesh_terms = [
            str(entry.get("descriptorName"))
            for entry in (item.get("meshHeadingList") or {}).get("meshHeading", [])
            if entry.get("descriptorName")
        ]
        keywords = (item.get("keywordList") or {}).get("keyword", [])
        records.append({
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": _plain_text(item.get("authorString")),
            "journal": _plain_text(journal.get("title") or journal.get("medlineAbbreviation")),
            "publication_date": publication_date,
            "publication_date_raw": publication_date_raw,
            "year": year,
            "study_type": str(publication_types[0]) if publication_types else "Other",
            "publication_types": "; ".join(map(str, publication_types)),
            "mesh_terms": "; ".join(mesh_terms),
            "keywords": "; ".join(map(str, keywords)),
            "doi": str(item.get("doi") or ""),
        })
    return records


def fetch_europe_pmc_records(pmids: list[str], attempts: int = 8) -> list[dict[str, str]]:
    query = "EXT_ID:(" + " OR ".join(pmids) + ") AND SRC:MED"
    url = EUROPE_PMC_URL + "?" + urlencode({
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": 1000,
    })
    request = Request(url, headers={"User-Agent": "EvidenceAtlasCapstone/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=90) as response:
                return parse_europe_pmc_results(response.read())
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(min(30.0, 1.5 * (2 ** (attempt - 1))))
    raise RuntimeError("Europe PMC request exhausted its retry budget")


def fetch_records(
    pmids: list[str], email: str = "", prefer_europe_pmc: bool = False
) -> tuple[list[dict[str, str]], str]:
    if prefer_europe_pmc:
        return fetch_europe_pmc_records(pmids), EUROPE_PMC_SOURCE
    try:
        return parse_articles(fetch_pubmed_xml(pmids, email)), NCBI_SOURCE
    except HTTPError as exc:
        if exc.code != 403:
            raise
        print(
            "NCBI E-utilities is forbidden by this network; falling back to Europe PMC MED records.",
            flush=True,
        )
        return fetch_europe_pmc_records(pmids), EUROPE_PMC_SOURCE


def _selection_sha256(pmids: list[str]) -> str:
    return hashlib.sha256("\n".join(pmids).encode("ascii")).hexdigest()


def release_ingestion_run_lock(handle) -> None:
    handle.close()


def acquire_ingestion_run_lock(output: Path):
    """Reserve one output target so concurrent extractors cannot share a checkpoint."""
    lock_path = output.with_suffix(".ingestion.lock")
    output.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError(f"PubMed ingestion is already running for {output}") from exc
    # Closing the descriptor or terminating its process releases the OS lock.
    # Keep the file itself to avoid unlink/recreate races between processes.
    return handle


def append_checkpoint_batch(
    checkpoint: Path,
    selected_pmids: list[str],
    requested_pmids: list[str],
    records: list[dict[str, str]],
    source: str,
) -> None:
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "selection_sha256": _selection_sha256(selected_pmids),
        "requested_pmids": requested_pmids,
        "records": records,
        "source": source,
    }
    with checkpoint.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_ingestion_checkpoint(
    checkpoint: Path, selected_pmids: list[str]
) -> tuple[list[dict[str, str]], set[str], str]:
    if not checkpoint.is_file():
        return [], set(), NCBI_SOURCE
    expected_hash = _selection_sha256(selected_pmids)
    records: list[dict[str, str]] = []
    completed: set[str] = set()
    source = NCBI_SOURCE
    with checkpoint.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                break
            if entry.get("selection_sha256") != expected_hash:
                return [], set(), NCBI_SOURCE
            requested_pmids = [str(pmid) for pmid in entry.get("requested_pmids", [])]
            if any(pmid in completed for pmid in requested_pmids):
                # A second process can only create an overlapping batch.  Ignore
                # it during recovery so duplicate checkpoint lines cannot inflate
                # the corpus or cause another re-fetch of completed PMIDs.
                continue
            completed.update(requested_pmids)
            records.extend(entry.get("records", []))
            source = str(entry.get("source") or source)
    return records, completed, source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=PROJECT_ROOT / "PubMed_Phrases.tar.gz")
    parser.add_argument("--profile", choices=("archive", "broad-medical"), default="archive")
    parser.add_argument("--phrase", action="append", dest="phrases")
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/raw/pubmed_sample.csv")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    args = parser.parse_args()
    if not 1 <= args.limit <= 100_000:
        raise ValueError("--limit must be between 1 and 100000")

    phrase_mapping: dict[str, list[str]] = {}
    phrases: list[str] = []
    if args.profile == "archive" or args.phrases:
        phrases = args.phrases or ["sglt2 inhibitor", "chronic kidney disease"]
        if not args.archive.is_file():
            raise FileNotFoundError(args.archive)
        phrase_mapping = phrase_pmids(args.archive, phrases)

    query_mapping: dict[str, list[str]] = {}
    configured_queries: dict[str, str] = {}
    if args.profile == "broad-medical":
        configured_queries.update(BROAD_MEDICAL_QUERIES)
    for index, query in enumerate(args.queries or [], start=1):
        configured_queries[f"custom_query_{index}"] = query
    if configured_queries:
        per_seed_limit = min(args.limit, max(1_000, (args.limit + len(configured_queries) - 1) // len(configured_queries) * 2))
        for label, query in configured_queries.items():
            pmids = search_pubmed_pmids(query, limit=per_seed_limit, email=args.email)
            if not pmids:
                print(f"PubMed search returned no PMIDs for {label}; continuing with other seeds.", flush=True)
                continue
            query_mapping[label] = pmids
            print(f"PubMed search returned {len(pmids)} PMIDs for {label}.", flush=True)
            time.sleep(0.4)

    seed_mapping = {**phrase_mapping, **query_mapping}
    if not seed_mapping:
        raise RuntimeError("No phrase archive or PubMed search seed produced PMIDs")
    selected = select_pmids_balanced(seed_mapping, args.limit)
    lock_path = acquire_ingestion_run_lock(args.output)
    atexit.register(release_ingestion_run_lock, lock_path)
    checkpoint_path = args.output.with_suffix(".ingestion_checkpoint.jsonl")
    records, completed_pmids, record_source = load_ingestion_checkpoint(checkpoint_path, selected)
    if completed_pmids:
        print(
            f"Resuming after {len(completed_pmids)}/{len(selected)} requested PubMed records; "
            f"{len(records)} usable records restored from checkpoint.",
            flush=True,
        )
    pending = [pmid for pmid in selected if pmid not in completed_pmids]
    offset = 0
    while offset < len(pending):
        batch_size = 500 if record_source == EUROPE_PMC_SOURCE else 100
        chunk = pending[offset : offset + batch_size]
        batch_records, record_source = fetch_records(
            chunk,
            args.email,
            prefer_europe_pmc=record_source == EUROPE_PMC_SOURCE,
        )
        records.extend(batch_records)
        append_checkpoint_batch(checkpoint_path, selected, chunk, batch_records, record_source)
        completed_pmids.update(chunk)
        completed = len(completed_pmids)
        if completed == len(selected) or completed % 1000 == 0:
            print(
                f"Fetched {completed}/{len(selected)} requested PubMed records; "
                f"{len(records)} currently have usable abstracts.",
                flush=True,
            )
        offset += len(chunk)
        if offset < len(pending):
            time.sleep(0.4)
    records = list({record["pmid"]: record for record in records}.values())
    if not records:
        raise RuntimeError("The biomedical literature source returned no title-and-abstract records")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    backup = args.output.with_name(f"{args.output.stem}.pre_ingest_backup{args.output.suffix}")
    if args.output.exists() and not backup.exists():
        shutil.copy2(args.output, backup)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", newline="", encoding="utf-8", dir=args.output.parent, delete=False, suffix=".csv"
        ) as handle:
            temp_name = handle.name
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)
        os.replace(temp_name, args.output)
        temp_name = None
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": record_source,
        "source_url": EUROPE_PMC_URL if record_source == EUROPE_PMC_SOURCE else EFETCH_URL,
        "upstream_corpus": "PubMed/MEDLINE",
        "selection_strategy": "balanced round-robin across phrase and query seeds",
        "profile": args.profile,
        "phrase_archive": str(args.archive.resolve()) if phrase_mapping else None,
        "phrase_archive_sha256": sha256_file(args.archive) if phrase_mapping else None,
        "phrases": phrases,
        "phrase_match_counts": {key: len(value) for key, value in phrase_mapping.items()},
        "search_queries": configured_queries,
        "search_match_counts": {key: len(value) for key, value in query_mapping.items()},
        "requested_pmids": len(selected),
        "usable_abstract_records": len(records),
        "unusable_or_missing_records": len(selected) - len(records),
        "output": str(args.output.resolve()),
    }
    default_output = PROJECT_ROOT / "data/raw/pubmed_sample.csv"
    manifest_path = args.manifest or (
        PROJECT_ROOT / "data/manifests/pubmed_ingestion_manifest.json"
        if args.output.resolve() == default_output.resolve()
        else args.output.with_suffix(".ingestion_manifest.json")
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)
    release_ingestion_run_lock(lock_path)
    atexit.unregister(release_ingestion_run_lock)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
