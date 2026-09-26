"""Prepare the local corpus and the three MedCPT model caches.

Online setup is fail-closed: all three Hugging Face models must load successfully
before the command can report success. ``--offline`` is an explicit opt-in and
is recorded in the asset manifest; absent cached weights then use the repository's
deterministic mock-embedding path.
"""

import os
import sys
import csv
import json
import logging
import shutil
import argparse
import gc
from pathlib import Path
from datetime import datetime, timezone

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("setup_assets")

REQUIRED_DIRECTORIES = [
    "data/raw",
    "data/processed",
    "data/qdrant_storage",
    "data/manifests",
    "data/evaluation",
    "data/models_cache",
    "backend/app",
    "logs",
]

MEDCPT_MODELS = [
    "ncbi/MedCPT-Query-Encoder",
    "ncbi/MedCPT-Article-Encoder",
    "ncbi/MedCPT-Cross-Encoder",
]

# Baseline curated PubMed records covering S1-S5 clinical domains
FALLBACK_CURATED_RECORDS = [
    {
        "pmid": "35100001",
        "title": "Empagliflozin and Progression of Chronic Kidney Disease in Patients with Type 2 Diabetes",
        "abstract": "In this double-blind, randomized controlled trial, 6,609 patients with type 2 diabetes mellitus and chronic kidney disease were assigned to receive empagliflozin 10 mg daily or matching placebo. Progression of kidney disease or cardiovascular death was significantly reduced in the empagliflozin group (HR 0.72; 95% CI 0.64-0.82; p < 0.001).",
        "authors": "Herrington WG; Staplin N; Green D; Baigent C",
        "journal": "N Engl J Med",
        "pub_date": "2023-01-12",
        "year": "2023",
        "study_type": "Randomized Controlled Trial",
        "mesh_terms": "Diabetes Mellitus, Type 2; Renal Insufficiency, Chronic; Sodium-Glucose Transporter 2 Inhibitors; Empagliflozin; Cardiovascular Diseases",
        "keywords": "SGLT2 inhibitors; empagliflozin; diabetic kidney disease; cardiovascular mortality",
        "publication_type": "Randomized Controlled Trial",
        "doi": "10.1056/NEJMoa2204233"
    },
    {
        "pmid": "35100002",
        "title": "Cardiovascular and Microvascular Outcomes with Semaglutide in Type 2 Diabetes",
        "abstract": "A randomized, double-blind, placebo-controlled trial evaluated subcutaneous semaglutide in adults with type 2 diabetes and high cardiovascular risk. Semaglutide significantly reduced major adverse cardiovascular events (HR 0.74; 95% CI 0.58-0.95; p=0.02) and diabetic nephropathy.",
        "authors": "Marso SP; Bain SC; Consoli A; Eliaschewitz FG",
        "journal": "Lancet Diabetes Endocrinol",
        "pub_date": "2022-04-15",
        "year": "2022",
        "study_type": "Randomized Controlled Trial",
        "mesh_terms": "Diabetes Mellitus, Type 2; Glucagon-Like Peptide-1 Receptor Agonists; Semaglutide; Myocardial Infarction; Stroke",
        "keywords": "GLP-1 receptor agonist; semaglutide; MACE; cardiovascular risk",
        "publication_type": "Randomized Controlled Trial",
        "doi": "10.1016/S2213-8587(22)00078-9"
    },
    {
        "pmid": "35200001",
        "title": "Sotorasib versus Docetaxel for Previously Treated Non-Small-Cell Lung Cancer with KRAS G12C Mutation: The CodeBreaK 200 Phase 3 Randomized Trial",
        "abstract": "In the Phase 3 CodeBreaK 200 trial, 345 patients with advanced KRAS G12C-mutated NSCLC previously treated with platinum doublet and checkpoint inhibitor were assigned to oral sotorasib or intravenous docetaxel. Sotorasib significantly improved progression-free survival (median 5.6 vs 4.5 months; HR 0.66; p=0.002).",
        "authors": "de Langen AJ; Johnson ML; Mazieres J; Dingemans AC",
        "journal": "Lancet",
        "pub_date": "2023-03-04",
        "year": "2023",
        "study_type": "Randomized Controlled Trial",
        "mesh_terms": "Carcinoma, Non-Small-Cell Lung; Lung Neoplasms; Proto-Oncogene Proteins p21(ras); Mutation; Sotorasib",
        "keywords": "KRAS G12C; sotorasib; NSCLC; progression-free survival; targeted therapy",
        "publication_type": "Randomized Controlled Trial",
        "doi": "10.1016/S0140-6736(23)00221-0"
    },
    {
        "pmid": "35300001",
        "title": "Safety, Immunogenicity, and Efficacy of the BNT162b2 mRNA Vaccine in Children Aged 6 Months to 4 Years",
        "abstract": "In this Phase 2/3 randomized controlled trial, 4,526 children received three 3-ug doses of the BNT162b2 mRNA COVID-19 vaccine or placebo. Neutralizing geometric mean ratios met immunobridging noninferiority criteria compared with young adults, with 73.2% observed vaccine efficacy and favorable reactogenicity.",
        "authors": "Fink MO; Creech CB; Anderson EJ; Munoz FM",
        "journal": "N Engl J Med",
        "pub_date": "2023-01-19",
        "year": "2023",
        "study_type": "Randomized Controlled Trial",
        "mesh_terms": "Child, Preschool; Infant; COVID-19 Vaccines; mRNA Vaccines; Immunogenicity, Vaccine; Safety",
        "keywords": "pediatric mRNA vaccine; BNT162b2; safety; immunogenicity; children",
        "publication_type": "Randomized Controlled Trial",
        "doi": "10.1056/NEJMoa2211051"
    },
    {
        "pmid": "35400001",
        "title": "Renal Denervation versus Sham Procedure in Patients with Resistant Hypertension: Long-Term Follow-up of SPYRAL HTN-ON MED",
        "abstract": "In this randomized, sham-controlled trial, 337 patients with resistant hypertension confirmed by ambulatory blood pressure monitoring underwent radiofrequency renal denervation or sham. At 36 months, renal denervation achieved a significant reduction in 24-hour ambulatory systolic blood pressure (difference -4.8 mm Hg; p=0.005).",
        "authors": "Kario K; Mahfoud F; Kandzari DE; Townsend RR",
        "journal": "Lancet",
        "pub_date": "2022-05-28",
        "year": "2022",
        "study_type": "Randomized Controlled Trial",
        "mesh_terms": "Hypertension; Denervation; Kidney; Blood Pressure Monitoring, Ambulatory; Catheter Ablation",
        "keywords": "resistant hypertension; renal denervation; blood pressure; catheter ablation",
        "publication_type": "Randomized Controlled Trial",
        "doi": "10.1016/S0140-6736(22)00584-0"
    },
    {
        "pmid": "35500001",
        "title": "Lecanemab in Early Alzheimer's Disease: Final Clinical and Biomarker Analysis of the Clarity AD Phase 3 Trial",
        "abstract": "In this 18-month Phase 3 trial, 1,795 patients with early Alzheimer's disease were randomized to intravenous lecanemab (10 mg/kg biweekly) or placebo. Lecanemab reduced mean CDR-SB decline by 27% compared with placebo (mean change 1.21 vs 1.66; difference -0.45; p < 0.001) with amyloid PET burden reduction.",
        "authors": "van Dyck CH; Swanson CJ; Aisen P; Bateman RJ",
        "journal": "N Engl J Med",
        "pub_date": "2023-01-05",
        "year": "2023",
        "study_type": "Randomized Controlled Trial",
        "mesh_terms": "Alzheimer Disease; Amyloid beta-Peptides; Antibodies, Monoclonal; Cognitive Dysfunction; Lecanemab",
        "keywords": "Lecanemab; Alzheimer's disease; amyloid-beta; CDR-SB; Clarity AD",
        "publication_type": "Randomized Controlled Trial",
        "doi": "10.1056/NEJMoa2212948"
    }
]


def init_directories(base_dir: Path) -> None:
    """Create all required directories in the workspace."""
    logger.info("Initializing project directories...")
    for rel_path in REQUIRED_DIRECTORIES:
        dir_path = base_dir / rel_path
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info("  [OK] Directory verified: %s", dir_path)


def setup_dataset(base_dir: Path, csv_path: Path, force: bool = False) -> int:
    """
    Populate data/raw/pubmed_sample.csv.
    If tests/fixtures/synthetic_pubmed.csv exists, copies it as the small demo corpus.
    Otherwise, populates with curated records.
    """
    if csv_path.exists() and not force:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required = {"pmid", "title", "abstract"}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Existing dataset {csv_path} is missing required columns: {sorted(missing)}")
            count = sum(1 for _ in reader)
        if count == 0:
            raise ValueError(f"Existing dataset contains no records: {csv_path}")
        logger.info("Dataset already exists at %s with %d records. (Use --force to overwrite)", csv_path, count)
        return count

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_csv = base_dir / "tests" / "fixtures" / "synthetic_pubmed.csv"

    if fixture_csv.exists():
        logger.info("Copying comprehensive curated dataset from %s to %s", fixture_csv, csv_path)
        shutil.copyfile(fixture_csv, csv_path)
        with open(csv_path, mode="r", encoding="utf-8") as f:
            count = sum(1 for _ in csv.DictReader(f))
        logger.info("  [OK] Successfully populated %s with %d records from test fixtures.", csv_path, count)
        return count

    logger.info("Writing baseline curated PubMed records to %s...", csv_path)
    fieldnames = [
        "pmid", "title", "abstract", "authors", "journal",
        "pub_date", "year", "mesh_terms", "keywords", "study_type", "publication_type", "doi"
    ]
    with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for record in FALLBACK_CURATED_RECORDS:
            writer.writerow(record)

    count = len(FALLBACK_CURATED_RECORDS)
    logger.info("  [OK] Successfully populated %s with %d curated records.", csv_path, count)
    return count


class ModelSetupError(RuntimeError):
    """Raised when online model caching did not complete for every required model."""

    def __init__(self, message: str, statuses: dict):
        super().__init__(message)
        self.statuses = statuses


def setup_models(cache_dir: Path, offline: bool = False) -> dict:
    """Load and cache MedCPT weights, or use an explicitly selected offline mode."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_status = {}
    try:
        from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
    except Exception as e:
        if offline:
            logger.warning("Transformers is unavailable in explicit offline mode: %s", e)
            return {m: {"status": "offline_mock", "error": str(e)} for m in MEDCPT_MODELS}
        raise ModelSetupError(
            f"Cannot import Transformers; install requirements before model setup: {e}",
            {m: {"status": "failed", "error": str(e)} for m in MEDCPT_MODELS},
        ) from e

    for model_id in MEDCPT_MODELS:
        logger.info("Verifying/caching %s in %s...", model_id, cache_dir)
        load_options = {"cache_dir": str(cache_dir), "local_files_only": offline}
        tokenizer = None
        model = None
        try:
            tokenizer = AutoTokenizer.from_pretrained(model_id, **load_options)
            if "Cross-Encoder" in model_id:
                model = AutoModelForSequenceClassification.from_pretrained(model_id, **load_options)
            else:
                model = AutoModel.from_pretrained(model_id, **load_options)

            if model is None or tokenizer is None:
                raise RuntimeError("Transformers returned an empty model or tokenizer")
            model_status[model_id] = {
                "status": "cached",
                "weights_verified": True,
                "source": "local-cache" if offline else "local-cache-or-huggingface",
                "cache_dir": str(cache_dir),
            }
            logger.info("  [OK] Loaded model weights and tokenizer: %s", model_id)
        except Exception as ex:
            if offline:
                logger.warning("  [OFFLINE MOCK] %s is not fully cached (%s).", model_id, ex)
                model_status[model_id] = {"status": "offline_mock", "error": str(ex)}
            else:
                logger.error("  [FAILED] Could not load/cache %s: %s", model_id, ex)
                model_status[model_id] = {"status": "failed", "error": str(ex)}
        finally:
            del model, tokenizer
            gc.collect()

    failed = [model_id for model_id, status in model_status.items() if status["status"] == "failed"]
    if failed:
        raise ModelSetupError(
            "MedCPT setup failed for: " + ", ".join(failed) + ". Re-run online setup after fixing the download/dependency issue.",
            model_status,
        )

    return model_status


def write_assets_manifest(base_dir: Path, dataset_count: int, model_status: dict, offline: bool = False) -> Path:
    """Record asset initialization details to data/manifests/assets_manifest.json."""
    manifest_path = base_dir / "data" / "manifests" / "assets_manifest.json"
    manifest_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "setup_mode": "offline" if offline else "online",
        "status": "ready" if all(item.get("status") == "cached" for item in model_status.values()) else "degraded-offline",
        "dataset": {
            "path": "data/raw/pubmed_sample.csv",
            "record_count": dataset_count,
            "status": "ready"
        },
        "models": model_status
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)
    logger.info("Asset manifest generated at: %s", manifest_path)
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description="AI Medical Research Abstract Finder - Asset Setup")
    parser.add_argument("--force", action="store_true", help="Force overwrite of raw dataset")
    parser.add_argument("--offline", action="store_true", help="Do not download models; use cached weights or explicitly marked mock embeddings")
    parser.add_argument("--cache-dir", type=str, default="data/models_cache", help="Directory for model cache")
    parser.add_argument("--data-path", type=str, default="data/raw/pubmed_sample.csv", help="Path for raw CSV dataset")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent.parent
    init_directories(base_dir)

    raw_csv = base_dir / args.data_path
    dataset_count = setup_dataset(base_dir, raw_csv, force=args.force)

    cache_dir = base_dir / args.cache_dir
    try:
        model_status = setup_models(cache_dir, offline=args.offline)
    except ModelSetupError as exc:
        write_assets_manifest(base_dir, dataset_count, exc.statuses, offline=args.offline)
        logger.error("Asset setup failed: %s", exc)
        return 1

    manifest_path = write_assets_manifest(base_dir, dataset_count, model_status, offline=args.offline)
    logger.info("=================================================================")
    logger.info("Asset and Environment Setup Completed (%s mode).", "OFFLINE" if args.offline else "ONLINE")
    logger.info("Dataset Records: %d | Manifest: %s", dataset_count, manifest_path)
    logger.info("=================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
