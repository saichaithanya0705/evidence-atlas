"""
backend/app/query/filter_extractor.py
Search Filter Extraction Module (FEAT-R3-05).
Parses explicit temporal constraints (e.g. "after 2022" -> year_min=2023, "before 2020" -> year_max=2019)
and study type mentions into structured metadata filters with year bounds validation [1900, 2099].
"""
import re
from typing import List, Optional, Tuple
from backend.app.query.models import SearchFilters


# Controlled study type mappings: (regex pattern, standardized study design)
STUDY_TYPE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Systematic Reviews & Meta-Analyses (checked first to handle compound phrases)
    (
        re.compile(r"\b(?:systematic\s+reviews?|meta-analys(?:is|es)|network\s+meta-analys(?:is|es))\b", re.IGNORECASE),
        "Systematic Review"
    ),
    # Randomized Controlled Trials
    (
        re.compile(
            r"\b(?:rcts?|randomi[zs]ed\s+controlled\s+trials?|randomi[zs]ed\s+trials?|"
            r"clinical\s+trials?|phase\s+3(?:\s+trials?)?|phase\s+iii(?:\s+trials?)?)\b",
            re.IGNORECASE
        ),
        "Randomized Controlled Trial"
    ),
    # Observational Cohort Studies
    (
        re.compile(
            r"\b(?:cohort\s+stud(?:y|ies)|observational\s+stud(?:y|ies)|"
            r"prospective\s+cohort(?:s)?|retrospective\s+cohort(?:s)?|population-based\s+cohort(?:s)?)\b",
            re.IGNORECASE
        ),
        "Observational Cohort Study"
    ),
    # Phase 2 Clinical Trials
    (
        re.compile(r"\b(?:phase\s+2(?:\s+trials?)?|phase\s+ii(?:\s+trials?)?)\b", re.IGNORECASE),
        "Phase 2 Clinical Trial"
    ),
    # Preclinical Studies
    (
        re.compile(r"\b(?:preclinical(?:\s+stud(?:y|ies))?|in\s+vivo|animal\s+models?|xenografts?)\b", re.IGNORECASE),
        "Preclinical Study"
    ),
    # In Vitro Studies
    (
        re.compile(r"\b(?:in\s+vitro(?:\s+stud(?:y|ies))?|cell\s+lines?|organoids?)\b", re.IGNORECASE),
        "In Vitro Study"
    ),
    # Translational Studies
    (
        re.compile(r"\b(?:translational(?:\s+stud(?:y|ies))?)\b", re.IGNORECASE),
        "Translational Study"
    ),
]

MIN_VALID_YEAR = 1900
MAX_VALID_YEAR = 2099


def _is_valid_year(year: Optional[int]) -> bool:
    """Validates that a publication year lies strictly within [1900, 2099]."""
    return year is not None and MIN_VALID_YEAR <= year <= MAX_VALID_YEAR


class SearchFilterExtractor:
    """
    Extracts publication year boundaries and study type constraints from query text.
    Implements offset arithmetic:
    - "after YYYY" / "since YYYY" -> year_min = YYYY + 1
    - "before YYYY" / "prior to YYYY" -> year_max = YYYY - 1
    - "YYYY-YYYY" / "between Y1 and Y2" -> year_min = min(Y1, Y2), year_max = max(Y1, Y2)
    - "last N years" / "past N years" -> year_min = reference_year - N
    """

    def __init__(self, reference_year: int = 2026):
        self.reference_year = reference_year

    def extract_filters(self, query: str) -> SearchFilters:
        """
        Parses temporal expressions and study designs from query text.

        Args:
            query: Natural language query string.

        Returns:
            SearchFilters object with year_min, year_max, and study_type_filters.
        """
        year_min: Optional[int] = None
        year_max: Optional[int] = None
        study_types: List[str] = []

        q = query.strip()

        # ---------------------------------------------------------------------
        # 1. Temporal Parsing
        # ---------------------------------------------------------------------

        # Pattern A: "after YYYY" / "since YYYY" / "published after YYYY"
        # Invariant: year_min = YYYY + 1
        after_match = re.search(r"\b(?:after|since|published\s+after)\s+(\d{4})\b", q, re.IGNORECASE)
        if after_match:
            cand = int(after_match.group(1)) + 1
            if _is_valid_year(cand):
                year_min = cand

        # Pattern B: "before YYYY" / "prior to YYYY" / "until YYYY" / "published before YYYY"
        # Invariant: year_max = YYYY - 1
        before_match = re.search(r"\b(?:before|prior\s+to|until|published\s+before)\s+(\d{4})\b", q, re.IGNORECASE)
        if before_match:
            cand = int(before_match.group(1)) - 1
            if _is_valid_year(cand):
                year_max = cand

        # Pattern C: "between YYYY and YYYY" / "from YYYY to YYYY"
        between_match = re.search(r"\b(?:between|from)\s+(\d{4})\s+(?:and|to|-)\s+(\d{4})\b", q, re.IGNORECASE)
        if between_match:
            y1 = int(between_match.group(1))
            y2 = int(between_match.group(2))
            min_y = min(y1, y2)
            max_y = max(y1, y2)
            if _is_valid_year(min_y):
                year_min = min_y
            if _is_valid_year(max_y):
                year_max = max_y

        # Pattern D: "YYYY-YYYY" hyphenated range (only if not already parsed)
        if year_min is None and year_max is None:
            range_match = re.search(r"\b(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2})\b", q)
            if range_match:
                y1 = int(range_match.group(1))
                y2 = int(range_match.group(2))
                min_y = min(y1, y2)
                max_y = max(y1, y2)
                if _is_valid_year(min_y):
                    year_min = min_y
                if _is_valid_year(max_y):
                    year_max = max_y

        # Pattern E: "last N years" / "past N years" / "in the last N years"
        if year_min is None:
            n_years_match = re.search(r"\b(?:in\s+the\s+)?(?:last|past)\s+(\d+)\s+years?\b", q, re.IGNORECASE)
            if n_years_match:
                n = int(n_years_match.group(1))
                cand = self.reference_year - n
                if _is_valid_year(cand):
                    year_min = cand

        # Pattern F: "recent" / "recently published" / "latest"
        if year_min is None:
            recent_match = re.search(r"\b(?:recently\s+published|recent\s+trials?|latest\s+evidence|recent)\b", q, re.IGNORECASE)
            if recent_match:
                cand = self.reference_year - 3
                if _is_valid_year(cand):
                    year_min = cand

        # ---------------------------------------------------------------------
        # 2. Study Design Parsing
        # ---------------------------------------------------------------------
        for pattern, design in STUDY_TYPE_PATTERNS:
            if pattern.search(q):
                if design not in study_types:
                    study_types.append(design)

        return SearchFilters(
            year_min=year_min,
            year_max=year_max,
            study_type_filters=study_types
        )
