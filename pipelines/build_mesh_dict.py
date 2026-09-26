"""
pipelines/build_mesh_dict.py
Builds in-memory MeSH lookup table and synonym inverted index from corpus descriptors.
Implements FEAT-R2-04.
"""
import argparse
import json
import logging
import os
from collections import Counter
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_mesh_dict")

CURATED_BIOMEDICAL_SYNONYMS: Dict[str, Dict[str, Any]] = {
    "Diabetes Mellitus, Type 2": {
        "canonical_name": "Type 2 Diabetes Mellitus",
        "synonyms": ["T2DM", "T2D", "Type 2 Diabetes", "NIDDM", "Non-Insulin-Dependent Diabetes Mellitus", "Adult-Onset Diabetes"],
        "category": "Nutritional and Metabolic Diseases",
        "tree_numbers": ["C18.452.394.750"],
    },
    "Diabetes Mellitus, Type 1": {
        "canonical_name": "Type 1 Diabetes Mellitus",
        "synonyms": ["T1DM", "T1D", "Type 1 Diabetes", "IDDM", "Insulin-Dependent Diabetes Mellitus", "Juvenile Diabetes"],
        "category": "Nutritional and Metabolic Diseases",
        "tree_numbers": ["C18.452.394.750.500"],
    },
    "Metformin": {
        "canonical_name": "Metformin",
        "synonyms": ["Glucophage", "Dimethylbiguanide", "Biguanide"],
        "category": "Chemical Actions and Uses",
        "tree_numbers": ["D02.065.199.124"],
    },
    "Sodium-Glucose Transporter 2 Inhibitors": {
        "canonical_name": "Sodium-Glucose Transporter 2 Inhibitors",
        "synonyms": ["SGLT2 inhibitors", "SGLT2i", "SGLT-2 Inhibitor", "SGLT2", "Gliflozins", "Empagliflozin", "Dapagliflozin"],
        "category": "Chemical Actions and Uses",
        "tree_numbers": ["D27.505.519.895"],
    },
    "Glucagon-Like Peptide-1 Receptor Agonists": {
        "canonical_name": "Glucagon-Like Peptide-1 Receptor Agonists",
        "synonyms": ["GLP-1 RA", "GLP-1 receptor agonists", "GLP-1 agonists", "GLP-1", "Semaglutide", "Liraglutide", "Incretin Mimetics"],
        "category": "Chemical Actions and Uses",
        "tree_numbers": ["D27.505.519.895.400"],
    },
    "Myocardial Infarction": {
        "canonical_name": "Myocardial Infarction",
        "synonyms": ["Heart Attack", "MI", "Acute Myocardial Infarction", "Coronary Thrombosis"],
        "category": "Cardiovascular Diseases",
        "tree_numbers": ["C14.280.647.500"],
    },
    "Heart Failure": {
        "canonical_name": "Heart Failure",
        "synonyms": ["HF", "CHF", "Congestive Heart Failure", "Cardiac Failure", "Heart Decompensation"],
        "category": "Cardiovascular Diseases",
        "tree_numbers": ["C14.280.434"],
    },
    "Hypertension": {
        "canonical_name": "Hypertension",
        "synonyms": ["High Blood Pressure", "HTN", "Arterial Hypertension", "Essential Hypertension"],
        "category": "Cardiovascular Diseases",
        "tree_numbers": ["C14.907.489"],
    },
    "Renal Insufficiency, Chronic": {
        "canonical_name": "Chronic Kidney Disease",
        "synonyms": ["CKD", "Chronic Kidney Disease", "Chronic Renal Disease", "Chronic Renal Failure"],
        "category": "Male Urogenital Diseases / Female Urogenital Diseases",
        "tree_numbers": ["C12.777.419.780"],
    },
    "Pulmonary Disease, Chronic Obstructive": {
        "canonical_name": "Chronic Obstructive Pulmonary Disease",
        "synonyms": ["COPD", "Chronic Obstructive Lung Disease", "Chronic Airflow Obstruction"],
        "category": "Respiratory Tract Diseases",
        "tree_numbers": ["C08.381.495.389"],
    },
    "Carcinoma, Non-Small-Cell Lung": {
        "canonical_name": "Non-Small Cell Lung Carcinoma",
        "synonyms": ["NSCLC", "Non-Small Cell Lung Cancer", "Non-Small-Cell Lung Carcinoma"],
        "category": "Neoplasms",
        "tree_numbers": ["C04.588.894.797.520"],
    },
    "COVID-19": {
        "canonical_name": "COVID-19",
        "synonyms": ["SARS-CoV-2 Infection", "Coronavirus Disease 2019", "2019 Novel Coronavirus Disease"],
        "category": "Virus Diseases",
        "tree_numbers": ["C01.925.782.600.550.200"],
    },
    "COVID-19 Vaccines": {
        "canonical_name": "COVID-19 Vaccines",
        "synonyms": ["SARS-CoV-2 Vaccine", "Coronavirus Vaccine", "mRNA vaccine", "BNT162b2", "mRNA-1273"],
        "category": "Immunological Factors",
        "tree_numbers": ["D20.215.894"],
    },
    "Alzheimer Disease": {
        "canonical_name": "Alzheimer's Disease",
        "synonyms": ["AD", "Alzheimer's", "Alzheimers Disease", "Senile Dementia, Alzheimer Type"],
        "category": "Nervous System Diseases",
        "tree_numbers": ["C10.228.140.380.100"],
    },
    "Parkinson Disease": {
        "canonical_name": "Parkinson's Disease",
        "synonyms": ["PD", "Parkinson's", "Parkinsons Disease", "Paralysis Agitans"],
        "category": "Nervous System Diseases",
        "tree_numbers": ["C10.228.662.600"],
    },
    "Asthma": {
        "canonical_name": "Asthma",
        "synonyms": ["Bronchial Asthma"],
        "category": "Respiratory Tract Diseases",
        "tree_numbers": ["C08.127.108"],
    },
    "Breast Neoplasms": {
        "canonical_name": "Breast Cancer",
        "synonyms": ["Mammary Neoplasms", "Breast Neoplasm", "Breast Tumors"],
        "category": "Neoplasms",
        "tree_numbers": ["C04.588.180"],
    },
    "Colitis, Ulcerative": {
        "canonical_name": "Ulcerative Colitis",
        "synonyms": ["UC", "Idiopathic Proctocolitis"],
        "category": "Digestive System Diseases",
        "tree_numbers": ["C06.405.469.432"],
    },
    "Randomized Controlled Trial": {
        "canonical_name": "Randomized Controlled Trial",
        "synonyms": ["RCT", "Randomized Trial", "Controlled Clinical Trial"],
        "category": "Publication Characteristics",
        "tree_numbers": ["V03.175.750"],
    },
}


def build_mesh_dictionary(
    clean_jsonl_or_parquet: str,
    output_dict_path: str,
) -> Dict[str, Any]:
    """Extracts corpus descriptors, computes document frequencies, merges synonyms, and builds inverted index."""
    logger.info("Building MeSH dictionary from: %s", clean_jsonl_or_parquet)

    records = []
    if clean_jsonl_or_parquet.endswith(".jsonl"):
        with open(clean_jsonl_or_parquet, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
    else:
        import pandas as pd
        df = pd.read_parquet(clean_jsonl_or_parquet)
        records = df.to_dict(orient="records")

    logger.info("Read %d clean records.", len(records))

    mesh_counter = Counter()
    for rec in records:
        terms = rec.get("mesh_terms", [])
        for t in terms:
            if t:
                mesh_counter[t] += 1

    logger.info("Discovered %d unique MeSH terms in corpus.", len(mesh_counter))

    descriptors_dict: Dict[str, Any] = {}
    synonym_inverted_index: Dict[str, str] = {}

    for term, count in mesh_counter.items():
        curated = CURATED_BIOMEDICAL_SYNONYMS.get(term, {})
        canonical_name = curated.get("canonical_name", term)
        synonyms = curated.get("synonyms", [])
        category = curated.get("category", "General Medical Concept")
        tree_numbers = curated.get("tree_numbers", [])

        descriptors_dict[term] = {
            "name": term,
            "canonical_name": canonical_name,
            "frequency": count,
            "synonyms": synonyms,
            "category": category,
            "tree_numbers": tree_numbers,
        }

        synonym_inverted_index[term.lower()] = term
        if canonical_name != term:
            synonym_inverted_index[canonical_name.lower()] = term

        for syn in synonyms:
            synonym_inverted_index[syn.lower()] = term

    for term, curated in CURATED_BIOMEDICAL_SYNONYMS.items():
        if term not in descriptors_dict:
            descriptors_dict[term] = {
                "name": term,
                "canonical_name": curated.get("canonical_name", term),
                "frequency": 0,
                "synonyms": curated.get("synonyms", []),
                "category": curated.get("category", "Curated Concept"),
                "tree_numbers": curated.get("tree_numbers", []),
            }
            synonym_inverted_index[term.lower()] = term
            if curated.get("canonical_name"):
                synonym_inverted_index[curated["canonical_name"].lower()] = term
            for syn in curated.get("synonyms", []):
                synonym_inverted_index[syn.lower()] = term

    output_data = {
        "version": "1.0",
        "total_descriptors": len(descriptors_dict),
        "total_inverted_keys": len(synonym_inverted_index),
        "corpus_terms_count": len(mesh_counter),
        "descriptors": descriptors_dict,
        "synonym_index": synonym_inverted_index,
    }

    os.makedirs(os.path.dirname(output_dict_path), exist_ok=True)
    with open(output_dict_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    logger.info("Saved MeSH dictionary to %s with %d descriptors and %d synonym mappings.",
                output_dict_path, len(descriptors_dict), len(synonym_inverted_index))
    return output_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate MeSH dictionary and synonym index.")
    parser.add_argument("--input", default="data/processed/cleaned_pubmed.jsonl")
    parser.add_argument("--output", default="data/processed/mesh_dictionary.json")
    args = parser.parse_args()

    build_mesh_dictionary(args.input, args.output)
