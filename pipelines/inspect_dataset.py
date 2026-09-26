"""
pipelines/inspect_dataset.py
Profiles raw PubMed CSV datasets: schema detection, missingness, duplicate rates, and data quality metrics.
"""
import argparse
import json
import logging
import os
import re
from typing import Dict, Any
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("inspect_dataset")


def profile_raw_dataset(csv_path: str) -> Dict[str, Any]:
    """Inspects a raw PubMed CSV file and outputs a comprehensive quality profile."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Input CSV not found at: {csv_path}")

    logger.info("Inspecting raw dataset: %s", csv_path)
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    total_rows = len(df)
    columns = list(df.columns)

    # Detect PMID column
    pmid_col = next((c for c in columns if c.lower() in ["pmid", "id", "pubmed_id"]), None)
    title_col = next((c for c in columns if c.lower() in ["title", "article_title"]), None)
    abstract_col = next((c for c in columns if c.lower() in ["abstract", "abstract_text"]), None)

    # Calculate duplicate rates
    duplicate_pmids = 0
    if pmid_col:
        valid_pmids = df[pmid_col].str.strip()
        duplicate_pmids = int(valid_pmids[valid_pmids != ""].duplicated().sum())

    duplicate_title_abstract = 0
    if title_col and abstract_col:
        text_pairs = df[title_col].str.strip().str.lower() + "|||" + df[abstract_col].str.strip().str.lower()
        duplicate_title_abstract = int(text_pairs.duplicated().sum())

    empty_titles = int((df[title_col].str.strip() == "").sum()) if title_col else total_rows
    empty_abstracts = int((df[abstract_col].str.strip() == "").sum()) if abstract_col else total_rows
    both_empty = 0
    if title_col and abstract_col:
        both_empty = int(((df[title_col].str.strip() == "") & (df[abstract_col].str.strip() == "")).sum())

    profile = {
        "file_path": csv_path,
        "total_rows": total_rows,
        "columns_found": columns,
        "identified_mappings": {
            "pmid": pmid_col,
            "title": title_col,
            "abstract": abstract_col,
        },
        "duplicate_pmid_count": duplicate_pmids,
        "duplicate_title_abstract_count": duplicate_title_abstract,
        "empty_title_count": empty_titles,
        "empty_abstract_count": empty_abstracts,
        "both_title_and_abstract_empty": both_empty,
        "usable_rows_estimated": total_rows - max(duplicate_pmids, duplicate_title_abstract) - both_empty,
    }

    logger.info("Dataset inspection complete:\n%s", json.dumps(profile, indent=2))
    return profile


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Profile raw PubMed CSV dataset.")
    parser.add_argument("--input", default="data/raw/pubmed_sample.csv", help="Path to raw CSV")
    parser.add_argument("--output", default="data/manifests/dataset_profile.json", help="Path to profile JSON")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    res = profile_raw_dataset(args.input)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    logger.info("Profile saved to %s", args.output)
