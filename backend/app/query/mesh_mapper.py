"""
backend/app/query/mesh_mapper.py
MeSH Concept Identification Module (FEAT-R3-03).
Maps raw and normalized query concepts to canonical MeSH descriptors using local
mesh_dictionary.json lookup, synonym matching, and augmented biomedical aliases.
"""
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from backend.app.services.mesh_service import MeshDictionaryService


# Augmented alias mapping to bridge colloquial expressions and clinical subphrases
# to controlled descriptors without assuming a disease context not in the query.
AUGMENTED_MESH_ALIASES: Dict[str, str] = {
    # Renal
    "kidney damage": "Renal Insufficiency, Chronic",
    "chronic kidney disease": "Renal Insufficiency, Chronic",
    "renal disease": "Renal Insufficiency, Chronic",
    "renal failure": "Renal Insufficiency, Chronic",
    "ckd": "Renal Insufficiency, Chronic",
    # Oncology & Genetics
    "lung cancer": "Carcinoma, Non-Small-Cell Lung",
    "non-small cell lung cancer": "Carcinoma, Non-Small-Cell Lung",
    "nsclc": "Carcinoma, Non-Small-Cell Lung",
    "kras g12c": "Mutation",
    "kras": "Mutation",
    "mutation": "Mutation",
    "mutated": "Mutation",
    "metastatic breast cancer": "Breast Neoplasms",
    "breast cancer": "Breast Neoplasms",
    # Pediatrics & Vaccines
    "pediatric": "Child, Preschool",
    "pediatric cohorts": "Child, Preschool",
    "children": "Child",
    "infants": "Infant",
    "mrna immunization": "mRNA Vaccines",
    "mrna vaccine": "mRNA Vaccines",
    "mrna vaccines": "mRNA Vaccines",
    "covid-19 vaccine": "COVID-19 Vaccines",
    "covid-19 vaccines": "COVID-19 Vaccines",
    # Cardiovascular & Metabolic
    "high blood pressure": "Hypertension",
    "resistant hypertension": "Hypertension",
    "hypertension": "Hypertension",
    "htn": "Hypertension",
    "catheter ablation": "Catheter Ablation",
    "myocardial infarction": "Myocardial Infarction",
    "heart attack": "Myocardial Infarction",
    "t2d": "Diabetes Mellitus, Type 2",
    "t2dm": "Diabetes Mellitus, Type 2",
    "type 2 diabetes": "Diabetes Mellitus, Type 2",
    "type 2 diabetes mellitus": "Diabetes Mellitus, Type 2",
    "diabetes": "Diabetes Mellitus, Type 2",
    "diabetic": "Diabetes Mellitus, Type 2",
    # Neurology & Respiratory
    "alzheimer": "Alzheimer Disease",
    "alzheimer's": "Alzheimer Disease",
    "memory loss": "Alzheimer Disease",
    "severe asthma": "Asthma",
    "asthma": "Asthma",
    "ulcerative colitis": "Colitis, Ulcerative",
    "colitis": "Colitis, Ulcerative",
}

# Stopwords to exclude when extracting raw concept phrases
CONCEPT_STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after", "above", "below",
    "to", "from", "up", "down", "of", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will",
    "just", "don", "should", "now", "vs", "versus", "and", "or", "what", "which",
    "efficacy", "outcomes", "risk", "reduction", "treatment", "published", "trials",
    "studies", "patients", "cohort", "cohorts"
}


class MeSHConceptIdentifier:
    """
    Identifies controlled MeSH descriptors and high-priority biomedical concepts
    from raw and normalized user queries.
    """

    def __init__(self, mesh_service: Optional[MeshDictionaryService] = None):
        if mesh_service is not None:
            self.mesh_service = mesh_service
        else:
            default_dict_path = "data/processed/mesh_dictionary.json"
            self.mesh_service = MeshDictionaryService(default_dict_path)

    def identify_concepts(
        self,
        clean_query: str,
        original_query: str = "",
        acronyms_expanded: Optional[Dict[str, str]] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        Maps clean_query and original_query to controlled MeSH descriptors and keywords.

        Args:
            clean_query: Normalized query string.
            original_query: Original user query string.
            acronyms_expanded: Dictionary of acronyms expanded during normalization.

        Returns:
            Tuple of:
            - mesh_terms: Sorted list of unique controlled MeSH descriptor names.
            - concepts: List of high-priority concept keyword phrases.
        """
        mesh_matched: Set[str] = set()
        acronyms_expanded = acronyms_expanded or {}
        combined_text = f"{original_query} {clean_query}".lower()

        # 1. First pass: MeshDictionaryService exact lookup on clean_query
        try:
            dict_concepts = self.mesh_service.extract_mesh_concepts(clean_query)
            mesh_matched.update(dict_concepts)
        except Exception:
            pass

        # 2. Second pass: Augmented alias matching
        # Sort keys descending by length to prefer multi-word phrases over single words
        for alias, descriptor in sorted(AUGMENTED_MESH_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = r"(?:\b|_)" + re.escape(alias) + r"(?:\b|_)"
            if re.search(pattern, combined_text, re.IGNORECASE):
                mesh_matched.add(descriptor)

        # 3. Third pass: Resolve acronym expansions through mesh service
        for expansion in acronyms_expanded.values():
            resolved = self.mesh_service.resolve_concept(expansion)
            if resolved:
                mesh_matched.add(resolved)

        # Subsumption pruning: prefer specific descriptors over generic ancestors
        if "Diabetes Mellitus, Type 2" in mesh_matched and "Diabetes Mellitus" in mesh_matched:
            mesh_matched.remove("Diabetes Mellitus")
        if "Child, Preschool" in mesh_matched and "Child" in mesh_matched:
            mesh_matched.remove("Child")

        # Sort MeSH terms for deterministic stability
        mesh_terms = sorted(list(mesh_matched))

        # 4. Extract concept keywords for hybrid retrieval
        concepts_set: Set[str] = set(mesh_terms)

        # Add expanded acronym values
        for val in acronyms_expanded.values():
            concepts_set.add(val)

        # Extract salient tokens from clean_query
        tokens = re.findall(r"[A-Za-z0-9\-]+", clean_query)
        for t in tokens:
            t_lower = t.lower()
            if len(t) >= 4 and t_lower not in CONCEPT_STOPWORDS and not t.isdigit():
                concepts_set.add(t)

        concepts = sorted(list(concepts_set), key=lambda c: (c not in mesh_terms, len(c)), reverse=True)

        return mesh_terms, concepts
