"""Build a real PubMed abstract corpus from the PubMed Phrases archive.

The archive supplies phrase-to-PMID mappings, not abstract text.  This script
uses those PMIDs to fetch canonical PubMed XML through NCBI E-utilities, then
writes the CSV schema consumed by the project's normal indexing pipeline.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
FIELDS = [
    "pmid", "title", "abstract", "authors", "journal", "publication_date",
    "publication_date_raw", "year", "study_type", "publication_types",
    "mesh_terms", "keywords", "doi",
]


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
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=90) as response:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=PROJECT_ROOT / "PubMed_Phrases.tar.gz")
    parser.add_argument("--phrase", action="append", dest="phrases")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/raw/pubmed_sample.csv")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--email", default=os.getenv("NCBI_EMAIL", ""))
    args = parser.parse_args()
    phrases = args.phrases or ["sglt2 inhibitor", "chronic kidney disease"]
    if not 1 <= args.limit <= 100_000:
        raise ValueError("--limit must be between 1 and 100000")
    if not args.archive.is_file():
        raise FileNotFoundError(args.archive)

    mapping = phrase_pmids(args.archive, phrases)
    selected = select_pmids(mapping, args.limit)
    records: list[dict[str, str]] = []
    for offset in range(0, len(selected), 100):
        chunk = selected[offset : offset + 100]
        records.extend(parse_articles(fetch_pubmed_xml(chunk, args.email)))
        completed = min(offset + len(chunk), len(selected))
        if completed == len(selected) or completed % 1000 == 0:
            print(
                f"Fetched {completed}/{len(selected)} requested PubMed records; "
                f"{len(records)} currently have usable abstracts.",
                flush=True,
            )
        if offset + 100 < len(selected):
            time.sleep(0.4)
    records = list({record["pmid"]: record for record in records}.values())
    if not records:
        raise RuntimeError("NCBI returned no title-and-abstract records")

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
        "source": "NCBI PubMed E-utilities",
        "source_url": EFETCH_URL,
        "phrase_archive": str(args.archive.resolve()),
        "phrase_archive_sha256": sha256_file(args.archive),
        "phrases": phrases,
        "phrase_match_counts": {key: len(value) for key, value in mapping.items()},
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
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
