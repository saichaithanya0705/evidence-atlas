"""Conservative action boundary, independent of model availability or output.

Lexical scope is a floor, not a relevance or evidence verdict. Unrecognized
topics require a biomedical clarification; matching terms never grant evidence,
citations, secrets, or a supported status. The planner still resolves intent.
"""

import re

from backend.app.query.mesh_mapper import AUGMENTED_MESH_ALIASES
from backend.app.query.normalizer import CURATED_ACRONYMS

_MEDICAL_CONTEXT = re.compile(
    r"\b(?:biomedical|medical|clinical|health|diseases?|disorders?|syndromes?|"
    r"diagnosis|symptoms?|therap(?:y|ies)|treatments?|medications?|drugs?|"
    r"monitoring|interactions?|population|mortality|prognosis|pharmac\w*|"
    r"vaccin\w*|adverse|side\s+effects?|cardiovascular|renal|kidney|"
    r"cancer|diabet\w*|hyperkalemia|proteinur\w*|glomerul\w*|nephr\w*|"
    r"LDL|statins?|aspirin|metformin)\b", re.I,
)
_KNOWN_TOPIC = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in AUGMENTED_MESH_ALIASES) + r")\b", re.I,
)
_CLINICAL_ACRONYM = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in (*CURATED_ACRONYMS, "AKI", "GFR", "RAAS")) + r")\b",
)
_FORBIDDEN_REQUEST = re.compile(
    r"\b(?:reveal|show|print|expose|dump|display)\b[^.\n]{0,100}"
    r"\b(?:api[_ -]?keys?|passwords?|credentials?|secrets?|system\s+prompt|hidden\s+reasoning)\b|"
    r"\b(?:invent|fabricate|fake|make\s+up)\b[^.\n]{0,100}"
    r"\b(?:trials?|stud(?:y|ies)|citations?|pmids?|evidence)\b|"
    r"\b(?:mark|label|return)\b[^.\n]{0,60}\bsupported\b[^.\n]{0,60}\bwithout\s+(?:evidence|citations?)\b",
    re.I,
)


def prohibited_request(message: str) -> bool:
    return bool(_FORBIDDEN_REQUEST.search(message))


def has_biomedical_context(message: str) -> bool:
    return bool(_MEDICAL_CONTEXT.search(message) or _KNOWN_TOPIC.search(message) or _CLINICAL_ACRONYM.search(message))
