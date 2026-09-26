"""
backend/app/query/normalizer.py
Biomedical Acronym and Spelling Normalizer (FEAT-R3-01 & FEAT-R3-02).
Preserves the raw original query immutably, normalizes whitespace, expands 15+ core
clinical acronyms and colloquial phrases, and corrects biomedical typos.
"""
import re
from typing import Dict, List, Optional, Tuple


# Core clinical acronyms and standard expansions per FEAT-R3-02
CURATED_ACRONYMS: Dict[str, str] = {
    # Metabolic & Endocrine
    "T2D": "Type 2 Diabetes Mellitus",
    "T2DM": "Type 2 Diabetes Mellitus",
    "T1D": "Type 1 Diabetes Mellitus",
    "T1DM": "Type 1 Diabetes Mellitus",
    "NIDDM": "Type 2 Diabetes Mellitus",
    "IDDM": "Type 1 Diabetes Mellitus",
    "GLP1": "Glucagon-Like Peptide-1",
    "GLP-1": "Glucagon-Like Peptide-1",
    "GLP-1 RA": "Glucagon-Like Peptide-1 Receptor Agonists",
    "GLP1RA": "Glucagon-Like Peptide-1 Receptor Agonists",
    "GLP1-RA": "Glucagon-Like Peptide-1 Receptor Agonists",
    "GLP-1-RA": "Glucagon-Like Peptide-1 Receptor Agonists",
    "SGLT2": "Sodium-Glucose Cotransporter-2",
    "SGLT-2": "Sodium-Glucose Cotransporter-2",
    "SGLT2i": "Sodium-Glucose Cotransporter-2 Inhibitors",
    # Cardiovascular
    "HTN": "Hypertension",
    "BP": "Blood Pressure",
    "MI": "Myocardial Infarction",
    "MACE": "Major Adverse Cardiovascular Events",
    "HF": "Heart Failure",
    "CHF": "Congestive Heart Failure",
    "CAD": "Coronary Artery Disease",
    "AF": "Atrial Fibrillation",
    "AFib": "Atrial Fibrillation",
    "AFIB": "Atrial Fibrillation",
    # Renal
    "CKD": "Chronic Kidney Disease",
    "eGFR": "Estimated Glomerular Filtration Rate",
    "ESRD": "End-Stage Renal Disease",
    # Oncology & Immunology
    "NSCLC": "Non-Small Cell Lung Cancer",
    "KRAS": "Kirsten Rat Sarcoma Viral Oncogene Homolog",
    "JAK": "Janus Kinase",
    "HER2": "Human Epidermal Growth Factor Receptor 2",
    "RA": "Rheumatoid Arthritis",
    "SLE": "Systemic Lupus Erythematosus",
    "UC": "Ulcerative Colitis",
    # Neurology
    "AD": "Alzheimer Disease",
    "PD": "Parkinson Disease",
    "ARIA": "Amyloid-Related Imaging Abnormalities",
    # Respiratory & Infectious
    "COPD": "Chronic Obstructive Pulmonary Disease",
    "RSV": "Respiratory Syncytial Virus",
    "mRNA": "Messenger Ribonucleic Acid",
    "HBOT": "Hyperbaric Oxygen Therapy",
    # Study Design
    "RCT": "Randomized Controlled Trial",
}

# Common colloquial phrases to formal clinical terms
COLLOQUIAL_CLINICAL_PHRASES: Dict[str, str] = {
    "heart attack": "Myocardial Infarction",
    "high blood pressure": "Hypertension",
    "kidney damage": "Chronic Kidney Disease",
    "lung cancer": "Non-Small Cell Lung Cancer",
    "blood pressure": "Blood Pressure",
    "sugar diabetes": "Type 2 Diabetes Mellitus",
    "memory loss": "Alzheimer Disease",
}

# Known biomedical typo dictionary for deterministic correction
KNOWN_BIOMEDICAL_TYPOS: Dict[str, str] = {
    "metfromin": "metformin",
    "metfomin": "metformin",
    "empagliflozen": "empagliflozin",
    "empaglifosin": "empagliflozin",
    "dapagliflozen": "dapagliflozin",
    "sotorasib": "sotorasib",
    "adagrasib": "adagrasib",
    "lecanemab": "lecanemab",
    "donanemab": "donanemab",
    "tezepelumab": "tezepelumab",
    "upadacitinib": "upadacitinib",
    "diabeets": "diabetes",
    "diabtes": "diabetes",
    "hypertenstion": "hypertension",
    "hypertention": "hypertension",
    "cardiovascualr": "cardiovascular",
    "cardiovascualar": "cardiovascular",
    "alzhiemer": "alzheimer",
    "alzhiemers": "alzheimers",
    "alzhiemer's": "alzheimer's",
    "alzheimr": "alzheimer",
    "infarcton": "infarction",
    "infartion": "infarction",
    "myocadial": "myocardial",
}

# Standard medical reference vocabulary for Levenshtein spell checking
REFERENCE_MEDICAL_VOCABULARY = {
    "metformin", "empagliflozin", "dapagliflozin", "canagliflozin", "semaglutide",
    "liraglutide", "tirzepatide", "sotorasib", "adagrasib", "lecanemab",
    "donanemab", "tezepelumab", "upadacitinib", "baxdrostat", "trastuzumab",
    "deruxtecan", "hypertension", "diabetes", "cardiovascular", "myocardial",
    "infarction", "alzheimer", "parkinson", "pediatric", "immunization",
    "catheter", "ablation", "remission", "colitis", "ulcerative", "resistance",
    "inhibitor", "inhibitors", "randomized", "controlled", "trial", "trials"
}


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Computes basic Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


class AcronymSpellingNormalizer:
    """
    Biomedical Acronym and Spelling Normalizer.
    Preserves original query (FEAT-R3-01) and performs acronym expansion (FEAT-R3-02).
    """

    def __init__(
        self,
        custom_acronyms: Optional[Dict[str, str]] = None,
        custom_colloquials: Optional[Dict[str, str]] = None,
    ):
        self.acronyms: Dict[str, str] = dict(CURATED_ACRONYMS)
        if custom_acronyms:
            self.acronyms.update(custom_acronyms)

        self.colloquials: Dict[str, str] = dict(COLLOQUIAL_CLINICAL_PHRASES)
        if custom_colloquials:
            self.colloquials.update(custom_colloquials)

    def normalize(self, raw_query: str) -> Tuple[str, str, Dict[str, str]]:
        """
        Normalizes a raw user query.

        Args:
            raw_query: Verbatim user query string.

        Returns:
            Tuple of:
            - original_query: Immutable original query string.
            - clean_query: Acronym-expanded, spelling-corrected, whitespace-normalized query.
            - acronyms_expanded: Dictionary mapping detected acronyms/phrases to their full expansions.

        Raises:
            ValueError: If raw_query is empty or contains only whitespace.
        """
        if not raw_query or not raw_query.strip():
            raise ValueError("Query cannot be empty or whitespace only")

        original_query = raw_query
        acronyms_expanded: Dict[str, str] = {}

        # 1. Normalize excessive whitespace for working copy
        clean_text = re.sub(r"\s+", " ", raw_query.strip())

        # 2. Check colloquial clinical phrases (case-insensitive)
        for phrase, expansion in sorted(self.colloquials.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
            match = pattern.search(clean_text)
            if match:
                matched_text = match.group(0)
                acronyms_expanded[matched_text] = expansion
                # If mid-sentence and original was lowercase, keep lowercase in clean_query
                replacement = expansion.lower() if matched_text.islower() else expansion
                clean_text = pattern.sub(replacement, clean_text, count=1)

        # 3. Check curated medical acronyms
        # Sort by length descending to match composite acronyms like "GLP-1 RA" before "GLP-1"
        for acr, expansion in sorted(self.acronyms.items(), key=lambda x: len(x[0]), reverse=True):
            # Acronyms with 2 characters (e.g. AD, BP, HF, MI, RA, UC) should be case-sensitive
            # to avoid false positives with common English words ("ad", "in", etc.)
            flags = 0 if len(acr) <= 2 else re.IGNORECASE
            pattern = re.compile(r"\b" + re.escape(acr) + r"\b", flags)
            match = pattern.search(clean_text)
            if match:
                matched_token = match.group(0)
                if matched_token not in acronyms_expanded:
                    acronyms_expanded[matched_token] = expansion
                clean_text = pattern.sub(expansion, clean_text, count=1)

        # 4. Spelling correction
        tokens = clean_text.split()
        corrected_tokens = []
        for token in tokens:
            # Preserve punctuation-stripped base token
            m = re.match(r"^(\W*)([\w\-]+)(\W*)$", token)
            if not m:
                corrected_tokens.append(token)
                continue

            prefix, word, suffix = m.groups()
            word_lower = word.lower()

            # Skip acronyms, genes, drug codes (all caps, containing digits or hyphens like KRAS, G12C, T-DM1)
            if (word.isupper() and len(word) <= 5) or any(char.isdigit() for char in word) or "-" in word:
                corrected_tokens.append(token)
                continue

            # Check direct known typos dictionary
            if word_lower in KNOWN_BIOMEDICAL_TYPOS:
                replacement = KNOWN_BIOMEDICAL_TYPOS[word_lower]
                if word[0].isupper():
                    replacement = replacement.capitalize()
                corrected_tokens.append(f"{prefix}{replacement}{suffix}")
                continue

            # Check Levenshtein distance for words >= 6 chars
            if len(word_lower) >= 6:
                best_match = None
                min_dist = 99
                for candidate in REFERENCE_MEDICAL_VOCABULARY:
                    dist = _levenshtein_distance(word_lower, candidate)
                    if dist <= 1 and dist < min_dist:
                        min_dist = dist
                        best_match = candidate

                if best_match:
                    replacement = best_match.capitalize() if word[0].isupper() else best_match
                    corrected_tokens.append(f"{prefix}{replacement}{suffix}")
                    continue

            corrected_tokens.append(token)

        clean_query = " ".join(corrected_tokens)
        clean_query = re.sub(r"\s+", " ", clean_query).strip()

        return original_query, clean_query, acronyms_expanded
