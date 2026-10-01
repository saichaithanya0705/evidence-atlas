"""
backend/app/query/extractor.py
PICO and Non-PICO Biomedical Concept Extraction and Research Intent Classification.
Implements:
- FEAT-R3-07: PICO Concept Extraction (with strict None for missing components).
- FEAT-R3-08: Non-PICO Biomedical Concept Extraction (disease, exposure, treatment, etc.).
- FEAT-R3-09: Research Intent Classification (discovery, comparison, effectiveness, safety, association, mechanism, evidence summary).
"""
import re
from typing import Dict, List, Optional, Tuple

from backend.app.query.models import IntentCategory, NonPICOConcepts, PICOModel


# Comparison triggers for PICO comparator detection
COMPARISON_REGEX = re.compile(
    r"\b(?:vs\.?|versus|compared\s+(?:with|to)|comparison\s+of|superiority\s+of|head-to-head)\b",
    re.IGNORECASE
)

# Intent classification regular expressions
INTENT_PATTERNS = [
    # 1. Comparison
    (
        re.compile(r"\b(?:vs\.?|versus|compared\s+(?:with|to)|comparison|head-to-head|superiority|non-inferiority)\b", re.IGNORECASE),
        "comparison"
    ),
    # 2. Mechanism
    (
        re.compile(r"\b(?:mechanisms?|pathway|resistance|mutations?|signaling|receptor|inhibition|cascade|molecular|pharmacodynamics|pharmacokinetics)\b", re.IGNORECASE),
        "mechanism"
    ),
    # 3. Safety
    (
        re.compile(r"\b(?:safety|adverse|toxicity|tolerability|side\s+effects?|myopericarditis|risk\s+of\s+(?:death|adverse|harm)|toxicities)\b", re.IGNORECASE),
        "safety"
    ),
    # 4. Evidence Summary
    (
        re.compile(r"\b(?:systematic\s+reviews?|meta-analys(?:is|es)|evidence\s+summary|overview|guidelines?|consensus)\b", re.IGNORECASE),
        "evidence summary"
    ),
    # 5. Association
    (
        re.compile(r"\b(?:association|correlated?|incidence|predicts?|predictor|relationship|cohort\s+study|risk\s+factors?)\b", re.IGNORECASE),
        "association"
    ),
    # 6. Effectiveness
    (
        re.compile(r"\b(?:efficacy|effectiveness|benefit|response\s+rate|reduces?|prevention|therapeutic\s+effects?|remission)\b", re.IGNORECASE),
        "effectiveness"
    ),
]


class PICOExtractor:
    """
    Extracts Population, Intervention, Comparator, and Outcome from query text.
    Enforces None for missing elements (FEAT-R3-07).
    """

    def extract(self, query: str, clean_query: Optional[str] = None) -> PICOModel:
        """
        Extracts PICO components from query.

        Args:
            query: Raw or clean query string.
            clean_query: Optional clean query string.

        Returns:
            PICOModel instance with extracted or None components.
        """
        text = clean_query or query
        if not text or not text.strip():
            return PICOModel()

        q = text.strip()
        q_lower = q.lower()

        population: Optional[str] = None
        intervention: Optional[str] = None
        comparator: Optional[str] = None
        outcome: Optional[str] = None

        # ---------------------------------------------------------------------
        # 1. Comparator & Intervention Extraction
        # ---------------------------------------------------------------------
        comp_match = COMPARISON_REGEX.search(q)
        if comp_match:
            # We have an explicit comparison
            left_part = q[:comp_match.start()].strip()
            right_part = q[comp_match.end():].strip()

            # Clean left part: extract intervention
            interv_match = re.search(r"\b(?:efficacy|safety|outcomes?|effects?)\s+of\s+(.+)$", left_part, re.IGNORECASE)
            if interv_match:
                intervention = interv_match.group(1).strip()
            else:
                intervention = left_part.strip()

            # Clean right part: extract comparator and trailing population/outcomes
            right_pop_match = re.search(r"^(.*?)\s+(?:in|among|for)\s+(.+)$", right_part, re.IGNORECASE)
            if right_pop_match:
                comparator = right_pop_match.group(1).strip()
                population = right_pop_match.group(2).strip()
            else:
                comparator = right_part.strip()
        else:
            # Single-arm / non-comparative query -> comparator MUST be None
            comparator = None

            # Detect intervention from phrasing: "efficacy of X in Y" or "X in Y" or "reduction with X"
            with_match = re.search(
                r"\b(?:with|using|of)\s+([A-Za-z0-9][A-Za-z0-9\-\s]*?)"
                r"(?=\s+(?:in|for|after|monotherapy)\b|[?,;.]|$)",
                q,
                re.IGNORECASE,
            )
            if "risk reduction with" in q_lower:
                m = re.search(r"risk reduction with\s+([A-Za-z0-9\-]+)", q, re.IGNORECASE)
                if m:
                    intervention = m.group(1).strip()
            elif "efficacy of" in q_lower or "safety of" in q_lower:
                m = re.search(
                    r"(?:efficacy|safety|effect)\s+of\s+([A-Za-z0-9][A-Za-z0-9\-\s]*?)"
                    r"(?=\s+(?:in|for|vs|versus)\b|[?,;.]|$)",
                    q,
                    re.IGNORECASE,
                )
                if m:
                    intervention = m.group(1).strip()
            elif "resistance mechanisms in" in q_lower:
                m = re.search(r"^([A-Za-z0-9\-]+)\s+resistance", q, re.IGNORECASE)
                if m:
                    intervention = m.group(1).strip()
            elif with_match:
                cand = with_match.group(1).strip()
                association_objective = re.search(
                    r"\b(?:association|associated|correlat\w*|incidence|prevalence|predictors?|prognosis)\b",
                    q, re.IGNORECASE,
                )
                population_with = re.search(
                    r"\b(?:patients?|people|cohorts?|individuals?|adults|children|infants)\s*$",
                    q[:with_match.start()], re.IGNORECASE,
                )
                if not association_objective and not population_with and cand.lower() not in ("patients", "kidney damage", "ckd", "diabetes", "tau"):
                    intervention = cand

        # ---------------------------------------------------------------------
        # 2. Population Extraction
        # ---------------------------------------------------------------------
        if not population:
            # Pattern: "in [patients with / cohorts with] X"
            pop_match = re.search(
                r"\b(?:in|among|for)\s+(?:patients\s+(?:with\s+)?|people\s+(?:with\s+)?|cohorts?\s+(?:with\s+)?|individuals?\s+(?:with\s+)?|adults\s+(?:with\s+)?|children\s+(?:with\s+)?|infants\s+(?:with\s+)?)?\s*([^,;.?]+?)(?:\s+(?:published|after|receiving|treated)|[?]|$)",
                q,
                re.IGNORECASE
            )
            if pop_match:
                cand = pop_match.group(1).strip()
                # Exclude outcomes if accidentally captured
                if cand.lower() not in ("remission", "mortality", "mace", "safety"):
                    population = cand

            # Specific known clinical populations
            if not population:
                if "t2d" in q_lower or "type 2 diabetes" in q_lower:
                    population = "Type 2 Diabetes Mellitus"
                elif "nsclc" in q_lower or "lung cancer" in q_lower:
                    population = "Non-Small Cell Lung Cancer"
                elif "pediatric" in q_lower or "infants" in q_lower or "children" in q_lower:
                    population = "Pediatric cohorts"
                elif "hypertension" in q_lower:
                    population = "Hypertension"
                elif "alzheimer" in q_lower:
                    population = "Alzheimer Disease"
                elif "breast cancer" in q_lower:
                    population = "Breast Cancer"
                elif "colitis" in q_lower:
                    population = "Ulcerative Colitis"

        # ---------------------------------------------------------------------
        # 3. Outcome Extraction
        # ---------------------------------------------------------------------
        outcome_cues = [
            ("kidney outcomes", "Kidney outcomes"),
            ("renal outcomes", "Renal outcomes"),
            ("cardiovascular outcomes", "Cardiovascular outcomes"),
            ("heart attack risk reduction", "Myocardial infarction risk reduction"),
            ("risk reduction", "Risk reduction"),
            ("resistance mechanisms", "Resistance mechanisms"),
            ("safety", "Safety and adverse events"),
            ("progression-free survival", "Progression-free survival"),
            ("mortality", "All-cause mortality"),
            ("mace", "Major Adverse Cardiovascular Events"),
            ("remission", "Remission induction"),
            ("blood pressure", "Blood pressure reduction"),
        ]
        for cue, label in outcome_cues:
            if cue in q_lower:
                outcome = label
                break


        # Dynamic reversal / clearance endpoint detection
        if not outcome:
            rev_match = re.search(
                r"\b(?:revers(?:ing|al|e|es|ed)|clear(?:ance|ing|s|ed))\s+(?:of\s+)?(.*?)(?:\s+(?:in|for|among|with|published)|$)",
                q,
                re.IGNORECASE
            )
            if rev_match:
                cand = rev_match.group(1).strip()
                if cand and len(cand) >= 3:
                    outcome = f"Reversal of {cand}"

        # Dynamic pathology phrase detection (e.g. "Bone pathology", "Thyroid pathology")
        if not outcome:
            path_match = re.search(r"\b([A-Za-z0-9\-]+\s+pathology)\b", q, re.IGNORECASE)
            if path_match:
                outcome = path_match.group(1).strip().capitalize()

        # Preserve the direction actually stated by the user. Merely naming
        # tau/pathology is not evidence that reversal was requested.
        if outcome is None:
            tau_match = re.search(
                r"\b(?:(revers(?:e|es|ed|ing|al)|clear(?:ance|ing|s|ed)|reduc(?:e|es|ed|ing|tion))\s+(?:of\s+)?(?:advanced\s+)?tau\s+pathology|tau\s+pathology)\b",
                q,
                re.IGNORECASE,
            )
            if tau_match:
                action = tau_match.group(1)
                outcome = "Tau pathology" if action is None else f"{action.capitalize()} of tau pathology"

        # Fallback defaults for standard single intervention queries if missing
        if intervention and not outcome and "efficacy" in q_lower:
            outcome = "Clinical efficacy endpoints"

        return PICOModel(
            population=population,
            intervention=intervention,
            comparator=comparator,
            outcome=outcome
        )


class NonPICOExtractor:
    """
    Extracts non-PICO biomedical concepts (disease_topic, exposure, treatment,
    population, outcome, relationship, study_type) per FEAT-R3-08.
    """

    def extract(self, query: str, clean_query: Optional[str] = None) -> NonPICOConcepts:
        """Extracts general biomedical concepts for non-intervention queries."""
        text = clean_query or query
        q_lower = text.lower()

        disease_topic: Optional[str] = None
        exposure: Optional[str] = None
        treatment: Optional[str] = None
        population: Optional[str] = None
        outcome: Optional[str] = None
        relationship: Optional[str] = None
        study_type: Optional[str] = None

        # 1. Disease / Topic (exact word-boundary matching)
        if re.search(r"\b(?:t2d|type\s+2\s+diabetes|type\s+ii\s+diabetes)\b", q_lower):
            disease_topic = "Type 2 Diabetes Mellitus"
        elif re.search(r"\b(?:t1d|type\s+1\s+diabetes|type\s+i\s+diabetes)\b", q_lower):
            disease_topic = "Type 1 Diabetes Mellitus"
        elif re.search(r"\bdiabetes\b", q_lower):
            disease_topic = "Diabetes Mellitus"
        elif re.search(r"\b(?:nsclc|non-small\s+cell\s+lung\s+cancer)\b", q_lower):
            disease_topic = "Non-Small Cell Lung Cancer"
        elif re.search(r"\b(?:sclc|small\s+cell\s+lung\s+cancer)\b", q_lower):
            disease_topic = "Small Cell Lung Cancer"
        elif re.search(r"\blung\s+cancer\b", q_lower):
            disease_topic = "Lung Neoplasms"
        elif re.search(r"\b(?:hypertension|high\s+blood\s+pressure)\b", q_lower):
            disease_topic = "Hypertension"
        elif re.search(r"\balzheimer\b", q_lower):
            disease_topic = "Alzheimer Disease"
        elif re.search(r"\bbreast\s+cancer\b", q_lower):
            disease_topic = "Breast Neoplasms"
        elif re.search(r"\bosteoporosis\b", q_lower):
            disease_topic = "Osteoporosis"
        elif re.search(r"\bulcerative\s+colitis\b", q_lower):
            disease_topic = "Ulcerative Colitis"
        elif re.search(r"\bcolitis\b", q_lower):
            disease_topic = "Colitis"
        elif re.search(r"\basthma\b", q_lower):
            disease_topic = "Asthma"
        elif dis_match := re.search(r"\b(?:(?:in|with|for|among|of)\s+)?([A-Za-z\-]+(?:\s+[A-Za-z\-]+)?\s+(?:syndrome|disease|disorder|cancer|carcinoma|neoplasm))\b", text, re.IGNORECASE):
            disease_topic = dis_match.group(1).title()

        # 2. Exposure / Genetics (dynamic gene & mutation extraction)
        known_genes = "KRAS|EGFR|BRAF|HER2|TP53|PIK3CA|ALK|ROS1|RET"
        mut_match = re.search(rf"\b({known_genes})\s+([A-Z0-9]{{2,6}})\b", text, re.IGNORECASE)
        if mut_match:
            exposure = f"{mut_match.group(1).upper()} {mut_match.group(2).upper()} mutation"
        elif gen_match := re.search(rf"\b({known_genes})\s+mutat(?:ion|ed)\b", text, re.IGNORECASE):
            exposure = f"{gen_match.group(1).upper()} mutation"
        elif re.search(r"\b(?:mrna|covid(?:-19)?|viral)\s+vaccine\b", q_lower):
            exposure = "mRNA vaccine exposure" if "mrna" in q_lower else "Vaccine exposure"
        elif re.search(r"\bstage\s+(?:iv|4)\s+tau\b", q_lower):
            exposure = "Stage IV tau pathology"
        elif re.search(r"\btau\s+(?:pathology|aggregation|tangles?)\b", q_lower):
            exposure = "Tau pathology"
        elif exp_match := re.search(r"\b(smoking|tobacco|radiation|asbestos|air\s+pollution)\b", q_lower):
            exposure = exp_match.group(1).capitalize()

        # 3. Treatment
        if "sotorasib" in q_lower:
            treatment = "Sotorasib"
        elif "metformin" in q_lower:
            treatment = "Metformin"
        elif "glp-1" in q_lower and "sglt2" in q_lower:
            treatment = "GLP-1 RA / SGLT2 inhibitors"
        elif "glp-1" in q_lower:
            treatment = "GLP-1 receptor agonist"
        elif "sglt2" in q_lower:
            treatment = "SGLT2 inhibitor"
        elif "hyperbaric" in q_lower or "hbot" in q_lower:
            treatment = "Hyperbaric Oxygen Therapy"
        elif "renal denervation" in q_lower:
            treatment = "Renal denervation"
        elif "catheter ablation" in q_lower:
            treatment = "Catheter ablation"
        elif rx_match := re.search(r"\b(?:treatment|therapy)\s+with\s+([A-Za-z0-9\-]+)\b", text, re.IGNORECASE):
            treatment = rx_match.group(1).capitalize()

        # 4. Population
        if any(w in q_lower for w in ["pediatric", "infant", "infants", "children", "child"]):
            population = "Pediatric cohort"
        elif any(w in q_lower for w in ["geriatric", "elderly"]):
            population = "Geriatric cohort"
        elif "ckd" in q_lower or "kidney damage" in q_lower:
            population = "Patients with chronic kidney disease"
        elif pop_match := re.search(r"\b(?:in|among)\s+(?:patients\s+with\s+|cohorts?\s+with\s+)?([A-Za-z0-9\-\s]{3,35}?)(?:\s+(?:published|after|receiving|treated)|\b|$)", text, re.IGNORECASE):
            cand_pop = pop_match.group(1).strip()
            if cand_pop.lower() not in ("safety", "mortality", "remission", "trial", "rct"):
                population = f"Patients with {cand_pop}"

        # 5. Outcome
        if "heart attack" in q_lower or "myocardial infarction" in q_lower:
            outcome = "Myocardial Infarction"
        elif "resistance" in q_lower:
            outcome = "Drug resistance"
        elif "safety" in q_lower or "adverse" in q_lower:
            outcome = "Adverse events / safety profile"
        elif "mortality" in q_lower or "death" in q_lower:
            outcome = "All-cause mortality"
        elif path_m := re.search(r"\b([A-Za-z0-9\-]+\s+pathology)\b", text, re.IGNORECASE):
            outcome = path_m.group(1).capitalize()

        # 6. Relationship
        if "resistance" in q_lower and ("mechanism" in q_lower or "pathway" in q_lower):
            relationship = "Molecular resistance mechanism"
        elif "resistance" in q_lower:
            relationship = "Drug resistance mechanism"
        elif "vs" in q_lower or "versus" in q_lower or "compared" in q_lower:
            relationship = "Comparative effectiveness"
        elif "risk reduction" in q_lower or "reduces" in q_lower:
            relationship = "Therapeutic risk reduction"
        elif "association" in q_lower or "correlation" in q_lower:
            relationship = "Observational correlation"
        elif "revers" in q_lower or "clearance" in q_lower:
            relationship = "Pathology reversal hypothesis"

        # 7. Study Type
        if "randomized" in q_lower or "rct" in q_lower or "trial" in q_lower:
            study_type = "Randomized Controlled Trial"
        elif "review" in q_lower or "meta-analysis" in q_lower:
            study_type = "Systematic Review"
        elif "cohort" in q_lower or "observational" in q_lower:
            study_type = "Observational Cohort Study"

        return NonPICOConcepts(
            disease_topic=disease_topic,
            exposure=exposure,
            treatment=treatment,
            population=population,
            outcome=outcome,
            relationship=relationship,
            study_type=study_type
        )


class IntentClassifier:
    """
    Classifies biomedical research query into one of 7 canonical intent categories (FEAT-R3-09):
    discovery, comparison, effectiveness, safety, association, mechanism, evidence summary.
    """

    def classify(self, query: str, clean_query: Optional[str] = None, pico: Optional[PICOModel] = None) -> IntentCategory:
        """
        Classifies query intent using prioritized deterministic pattern matching.

        Args:
            query: User's raw query string.
            clean_query: Normalized query string.
            pico: Extracted PICO model.

        Returns:
            IntentCategory string.
        """
        text = f"{query} {clean_query or ''}".strip()

        # If PICO has an explicit comparator, intent is definitely comparison
        if pico and pico.comparator:
            return "comparison"

        for pattern, intent in INTENT_PATTERNS:
            if pattern.search(text):
                return intent

        # Fallback to broad discovery
        return "discovery"
