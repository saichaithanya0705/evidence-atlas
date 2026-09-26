"""
pipelines/preprocess.py
Production preprocessing engine for PubMed / MEDLINE abstract datasets.
Implements FEAT-R2-01, FEAT-R2-02, FEAT-R2-03.
"""
import argparse
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dateutil import parser as date_parser

from backend.app.models.paper import StudyType

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("preprocess")

COLUMN_ALIASES = {
    "pmid": ["pmid", "PMID", "id", "pubmed_id"],
    "title": ["title", "Title", "article_title"],
    "abstract": ["abstract", "Abstract", "abstract_text"],
    "authors": ["authors", "Authors", "author_list"],
    "journal": ["journal", "Journal", "journal_title", "source"],
    "pubdate": ["publication_date", "pubdate", "pub_date", "date", "year"],
    "mesh": ["mesh_terms", "mesh", "MeSH", "mesh_headings"],
    "keywords": ["keywords", "Keywords", "author_keywords"],
    "pub_type": ["study_type", "publication_type", "publication_types", "pub_type"],
    "doi": ["doi", "DOI"],
}

STUDY_DESIGN_PATTERNS = [
    (re.compile(r"systematic review", re.IGNORECASE), StudyType.SYSTEMATIC_REVIEW.value),
    (re.compile(r"meta-analysis", re.IGNORECASE), StudyType.META_ANALYSIS.value),
    (re.compile(r"randomized controlled trial|clinical trial, phase|rct\b", re.IGNORECASE), StudyType.RCT.value),
    (re.compile(r"cohort study|prospective study|retrospective study|observational", re.IGNORECASE), StudyType.OBSERVATIONAL.value),
    (re.compile(r"clinical trial", re.IGNORECASE), StudyType.CLINICAL_TRIAL.value),
    (re.compile(r"preclinical|in vitro|murine|xenograft|rodent", re.IGNORECASE), StudyType.PRECLINICAL.value),
    (re.compile(r"review\b", re.IGNORECASE), StudyType.REVIEW.value),
]


def resolve_columns(df_columns: List[str]) -> Dict[str, str]:
    """Maps standardized canonical keys to actual CSV column names."""
    mapping = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        found = next((col for col in df_columns if col in aliases or col.lower() in [a.lower() for a in aliases]), None)
        if found:
            mapping[canonical] = found
    return mapping


def normalize_unicode_and_whitespace(text: str) -> str:
    """Normalizes Unicode (NFKC) and collapses whitespace while preserving medical syntax."""
    if not text or not isinstance(text, str):
        return ""
    norm = unicodedata.normalize("NFKC", text)
    # Remove null bytes or non-printable ASCII control characters except \n and \t
    norm = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", norm)
    # Normalize varied whitespace characters to standard space
    norm = re.sub(r"[ \t\u00a0\u2000-\u200b\u202f\u205f]+", " ", norm)
    # Strip leading/trailing whitespace
    return norm.strip()


def parse_date_and_year(date_str: str) -> Tuple[Optional[int], Optional[str]]:
    """
    Extracts standardized integer year (1900-2026) and ISO date string (YYYY-MM-DD).
    Returns (year, iso_date).
    """
    if not date_str or not isinstance(date_str, str):
        return None, None
    s = date_str.strip()
    if not s:
        return None, None

    # Step 1: Extract 4-digit year via strict regex
    year_match = re.search(r"\b(19\d\d|20[0-2]\d)\b", s)
    year = int(year_match.group(1)) if year_match else None

    # Step 2: Try parsing full ISO date
    iso_date = None
    try:
        ref_year = year if year else 2000
        dt = date_parser.parse(s, fuzzy=True, default=datetime(ref_year, 1, 1))
        iso_date = dt.strftime("%Y-%m-%d")
        if not year:
            year = dt.year if 1900 <= dt.year <= 2026 else None
    except Exception:
        if year:
            iso_date = f"{year:04d}-01-01"

    return year, iso_date


def parse_mesh_terms(mesh_str: str) -> Tuple[List[str], List[str]]:
    """
    Parses MeSH string into clean descriptors and full qualified descriptors.
    Returns (clean_descriptors, full_descriptors).
    """
    if not mesh_str or not isinstance(mesh_str, str):
        return [], []

    raw_items = [t.strip() for t in re.split(r"[;\n]", mesh_str) if t.strip()]
    clean_descriptors = []
    full_descriptors = []

    for item in raw_items:
        clean_full = item.replace("*", "").strip()
        if clean_full:
            full_descriptors.append(clean_full)

        # Base descriptor (stripping subheadings after slash '/')
        base = re.sub(r"/[^;]+", "", item).replace("*", "").strip()
        if base and base not in clean_descriptors:
            clean_descriptors.append(base)

    return clean_descriptors, full_descriptors


def parse_keyword_array(kw_str: str) -> List[str]:
    """Parses semicolon- or comma-delimited keywords while preserving display casing."""
    if not kw_str or not isinstance(kw_str, str):
        return []
    delimiter = ";" if ";" in kw_str else ("|" if "|" in kw_str else ",")
    items = [k.strip() for k in kw_str.split(delimiter) if k.strip()]
    unique_items = []
    seen = set()
    for item in items:
        norm = item.lower()
        if norm not in seen:
            seen.add(norm)
            unique_items.append(item)
    return unique_items


def parse_authors_array(authors_str: str) -> List[str]:
    """Parses authors string into a clean list of author names."""
    if not authors_str or not isinstance(authors_str, str):
        return []
    delimiter = ";" if ";" in authors_str else ("|" if "|" in authors_str else ",")
    return [a.strip() for a in authors_str.split(delimiter) if a.strip()]


def infer_study_type(pub_types: List[str], title: str, abstract: str) -> str:
    """Infers canonical study design category from publication types and text."""
    combined = " ".join(pub_types) + " " + title + " " + abstract
    for pattern, label in STUDY_DESIGN_PATTERNS:
        if pattern.search(combined):
            return label
    return StudyType.OTHER.value


def preprocess_corpus(
    input_csv: str,
    output_parquet: str,
    output_jsonl: str,
    manifest_path: str,
) -> Dict[str, Any]:
    """Full preprocessing pipeline execution."""
    if not os.path.exists(input_csv):
        raise FileNotFoundError(f"Source CSV not found: {input_csv}")

    logger.info("Loading raw data from: %s", input_csv)
    df_raw = pd.read_csv(input_csv, dtype=str, keep_default_na=False)
    initial_count = len(df_raw)
    logger.info("Total raw records read: %d", initial_count)

    col_map = resolve_columns(list(df_raw.columns))
    logger.info("Resolved column mappings: %s", col_map)

    if "pmid" not in col_map:
        raise ValueError(f"Required PMID column not found among headers: {list(df_raw.columns)}")

    records: List[Dict[str, Any]] = []
    seen_pmids = set()
    seen_text_hashes = set()
    dropped_empty = 0
    dropped_duplicate_pmid = 0
    dropped_duplicate_text = 0

    for idx, row in df_raw.iterrows():
        # 1. Clean PMID
        raw_pmid = str(row[col_map["pmid"]]).strip()
        pmid_match = re.search(r"\b(\d+)\b", raw_pmid)
        if not pmid_match:
            dropped_empty += 1
            continue
        pmid = pmid_match.group(1)

        if pmid in seen_pmids:
            dropped_duplicate_pmid += 1
            continue

        # 2. Clean Title & Abstract
        title_raw = str(row[col_map["title"]]) if "title" in col_map else ""
        abstract_raw = str(row[col_map["abstract"]]) if "abstract" in col_map else ""
        title = normalize_unicode_and_whitespace(title_raw)
        abstract = normalize_unicode_and_whitespace(abstract_raw)

        # Drop if both are empty
        if not title and not abstract:
            dropped_empty += 1
            continue

        # Check duplicate content
        text_signature = f"{title.lower()}|||{abstract[:100].lower()}"
        if text_signature in seen_text_hashes:
            dropped_duplicate_text += 1
            continue

        seen_pmids.add(pmid)
        seen_text_hashes.add(text_signature)

        # 3. Embedding Text
        if title and abstract:
            embedding_text = f"{title}\n\n{abstract}"
        else:
            embedding_text = title if title else abstract

        # 4. Dates
        # Keep the source representation intact for auditability; the parser
        # normalizes independently and strips whitespace before interpreting it.
        pubdate_raw = str(row[col_map["pubdate"]]) if "pubdate" in col_map else ""
        year, iso_date = parse_date_and_year(pubdate_raw)

        # 5. MeSH Terms
        mesh_raw = str(row[col_map["mesh"]]) if "mesh" in col_map else ""
        mesh_terms, mesh_qualifiers = parse_mesh_terms(mesh_raw)

        # 6. Keywords
        kw_raw = str(row[col_map["keywords"]]) if "keywords" in col_map else ""
        keywords = parse_keyword_array(kw_raw)

        # 7. Authors & Journal
        authors_raw = str(row[col_map["authors"]]) if "authors" in col_map else ""
        authors = parse_authors_array(authors_raw)
        journal = normalize_unicode_and_whitespace(str(row[col_map["journal"]])) if "journal" in col_map else ""

        # 8. Publication Types & Study Type
        pub_type_raw = str(row[col_map["pub_type"]]) if "pub_type" in col_map else ""
        pub_types = [p.strip() for p in re.split(r"[;\n]", pub_type_raw) if p.strip()]
        study_type = infer_study_type(pub_types, title, abstract)

        # 9. DOI
        doi = str(row[col_map["doi"]]).strip() if "doi" in col_map else None
        if doi and not doi.lower().startswith("10."):
            doi = None

        record = {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "embedding_text": embedding_text,
            "authors": authors,
            "journal": journal,
            "pubdate_raw": pubdate_raw,
            "publication_date": iso_date,
            "year": year,
            "mesh_terms": mesh_terms,
            "mesh_qualifiers": mesh_qualifiers,
            "keywords": keywords,
            "publication_types": pub_types,
            "study_type": study_type,
            "doi": doi,
        }
        records.append(record)

    clean_count = len(records)
    logger.info("Preprocessing completed: %d clean records.", clean_count)
    logger.info("Dropped: %d empty, %d duplicate PMIDs, %d duplicate texts.", dropped_empty, dropped_duplicate_pmid, dropped_duplicate_text)

    # Save to JSONL
    os.makedirs(os.path.dirname(output_jsonl), exist_ok=True)
    with open(output_jsonl, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    logger.info("Saved clean corpus to JSONL: %s", output_jsonl)

    # Save to Parquet if pyarrow/fastparquet is available
    parquet_saved = False
    try:
        os.makedirs(os.path.dirname(output_parquet), exist_ok=True)
        clean_df = pd.DataFrame(records)
        clean_df.to_parquet(output_parquet, index=False)
        parquet_saved = True
        logger.info("Saved clean corpus to Parquet: %s", output_parquet)
    except Exception as e:
        logger.warning("Parquet engine save encountered warning (%s); JSONL saved successfully.", e)

    # Write Manifest
    stats = {
        "source_file": input_csv,
        "total_raw_rows": initial_count,
        "clean_records_count": clean_count,
        "dropped_corrupt_or_empty": dropped_empty,
        "dropped_duplicate_pmids": dropped_duplicate_pmid,
        "dropped_duplicate_content": dropped_duplicate_text,
        "parquet_path": output_parquet if parquet_saved else None,
        "jsonl_path": output_jsonl,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess PubMed abstract corpus.")
    parser.add_argument("--input", default="data/raw/pubmed_sample.csv")
    parser.add_argument("--output-parquet", default="data/processed/cleaned_pubmed.parquet")
    parser.add_argument("--output-jsonl", default="data/processed/cleaned_pubmed.jsonl")
    parser.add_argument("--manifest", default="data/manifests/preprocessing_manifest.json")
    args = parser.parse_args()

    preprocess_corpus(args.input, args.output_parquet, args.output_jsonl, args.manifest)
