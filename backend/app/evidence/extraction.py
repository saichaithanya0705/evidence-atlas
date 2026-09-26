"""Deterministic evidence extraction with exact abstract sentence spans."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from backend.app.models.request_response import EvidenceRecord, RetrievalCandidate
from backend.app.query.models import QueryPlan
from backend.app.retrieval.bm25 import tokenize_biomedical_text


_LIMITATION_MARKERS = (
    "limitation", "limited by", "small sample", "short follow-up", "not powered",
    "cannot establish", "did not assess", "further studies", "single-center",
)
_FINDING_MARKERS = ("results:", "conclusion:", "conclusions:", "in this study", "we found", "was associated", "reduced", "increased", "improved", "no significant")


def _sentence_spans(text: str) -> List[str]:
    """Split abstract text without rewriting the returned source substrings."""
    if not text:
        return []
    spans: List[str] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+(?=[A-Z0-9])", text):
        sentence = text[start:match.start()].strip()
        if sentence:
            spans.append(sentence)
        start = match.end()
    tail = text[start:].strip()
    if tail:
        spans.append(tail)
    return spans or [text.strip()]


def _terms(plan: QueryPlan) -> List[str]:
    values = [plan.original_query, plan.clean_query, plan.canonical_query]
    values.extend(getattr(plan, "concepts", []) or [])
    values.extend(getattr(plan, "mesh_terms", []) or [])
    weights = getattr(plan, "concept_weights", None)
    if weights is not None:
        values.extend(getattr(weights, "must_have", []) or [])
        values.extend(getattr(weights, "high_priority", []) or [])
    tokens = set()
    for value in values:
        tokens.update(tokenize_biomedical_text(str(value or "")))
    return sorted(tokens)


def _query_specificity_score(sentence: str, terms: Sequence[str]) -> float:
    tokens = set(tokenize_biomedical_text(sentence))
    if not tokens or not terms:
        return 0.0
    overlap = len(tokens.intersection(terms))
    # A small structural boost selects findings/conclusions only when they also
    # share at least one query concept; abstract section labels alone are not evidence.
    marker_boost = 0.15 if any(marker in sentence.casefold() for marker in _FINDING_MARKERS) else 0.0
    return overlap / max(1, min(len(terms), 8)) + marker_boost


def _field_if_verbatim(value: Optional[str], spans: Sequence[str]) -> Optional[str]:
    candidate = (value or "").strip()
    if not candidate:
        return None
    if any(candidate.casefold() in span.casefold() for span in spans):
        return candidate
    return None


def _controlled_source_alias(value: Optional[str], spans: Sequence[str]) -> Optional[str]:
    """Return a verbatim controlled-term alias only when it occurs in source."""
    desired = (value or "").casefold()
    patterns = []
    if "glucagon-like peptide-1" in desired:
        patterns.append(r"\bGLP-?1\s+(?:receptor\s+)?agonists?\b")
    if "sodium-glucose cotransporter-2" in desired:
        patterns.append(r"\bSGLT-?2\s+inhibitors?\b")
    for span in spans:
        for pattern in patterns:
            match = re.search(pattern, span, re.IGNORECASE)
            if match:
                return match.group(0)
    return None


class EvidenceExtractor:
    """Build EvidenceRecords without filling source-absent PICO details."""

    def __init__(self, max_spans_per_paper: int = 3) -> None:
        self.max_spans_per_paper = max(1, int(max_spans_per_paper))

    def extract(self, candidate: RetrievalCandidate, plan: QueryPlan) -> EvidenceRecord:
        abstract = candidate.abstract or ""
        sentences = _sentence_spans(abstract)
        terms = _terms(plan)
        scored = [(_query_specificity_score(sentence, terms), index, sentence) for index, sentence in enumerate(sentences)]
        relevant = [item for item in scored if item[0] > 0]
        if relevant:
            # Keep the highest-value spans while restoring source order so the
            # evidence table remains readable and offsets are easy to inspect.
            selected = sorted(sorted(relevant, key=lambda item: (-item[0], item[1]))[: self.max_spans_per_paper], key=lambda item: item[1])
            spans = [item[2] for item in selected]
        else:
            spans = []

        limitations = [span for span in spans if any(marker in span.casefold() for marker in _LIMITATION_MARKERS)]
        findings = [span for span in spans if span not in limitations]
        if not findings and spans:
            findings = list(spans)
        key_findings = " ".join(findings).strip() if findings else "No query-relevant finding could be extracted from the abstract."

        pico = getattr(plan, "pico", None)
        population = _field_if_verbatim(getattr(pico, "population", None), spans) if pico else None
        intervention = _field_if_verbatim(getattr(pico, "intervention", None), spans) if pico else None
        if intervention is None and pico:
            intervention = _controlled_source_alias(getattr(pico, "intervention", None), sentences)
        comparator = _field_if_verbatim(getattr(pico, "comparator", None), spans) if pico else None
        outcome = _field_if_verbatim(getattr(pico, "outcome", None), spans) if pico else None

        return EvidenceRecord(
            pmid=candidate.pmid,
            title=candidate.title,
            year=candidate.year,
            study_design=candidate.study_type or "Other",
            population=population,
            intervention=intervention,
            comparator=comparator,
            outcome=outcome,
            key_findings=key_findings,
            limitations=" ".join(limitations) if limitations else None,
            supporting_text_spans=spans,
        )

    def extract_all(self, candidates: Iterable[RetrievalCandidate], plan: QueryPlan) -> List[EvidenceRecord]:
        return [self.extract(candidate, plan) for candidate in candidates]


class EvidenceAnalyzer:
    """Create auditable cross-study groups and conservative agreement labels."""

    _POSITIVE = ("reduced", "improved", "increased", "lower", "benefit", "effective", "protective", "significant")
    _NEGATIVE = ("increased risk", "worsened", "higher", "harm", "ineffective", "no significant", "not associated", "failed")

    @staticmethod
    def _group_key(record: EvidenceRecord) -> str:
        return (record.intervention or record.outcome or record.study_design or "unspecified evidence").strip().casefold()

    @classmethod
    def _direction(cls, finding: str) -> Optional[str]:
        text = finding.casefold()
        negative = any(term in text for term in cls._NEGATIVE)
        positive = any(term in text for term in cls._POSITIVE) and not negative
        if positive == negative:
            return None
        return "positive" if positive else "negative"

    def analyze(self, records: Sequence[EvidenceRecord], query_plan: QueryPlan) -> dict:
        groups = {}
        for record in records:
            key = self._group_key(record)
            groups.setdefault(key, []).append(record.pmid)
        directions = [self._direction(record.key_findings) for record in records]
        observed = {value for value in directions if value is not None}
        if not records:
            consensus = "insufficient"
        elif len(observed) > 1:
            consensus = "conflicting"
        elif len(records) == 1 or not observed:
            consensus = "mixed" if len(records) > 1 else "insufficient"
        else:
            consensus = "consensus"

        gaps = []
        pico = getattr(query_plan, "pico", None)
        if len(records) < 2:
            gaps.append("The retrieved evidence contains fewer than two studies for cross-study comparison.")
        for label, value in (("population", getattr(pico, "population", None)), ("intervention", getattr(pico, "intervention", None)), ("comparator", getattr(pico, "comparator", None)), ("outcome", getattr(pico, "outcome", None))):
            if value and not any(getattr(record, label, None) for record in records):
                gaps.append(f"The abstracts do not explicitly report the requested {label}.")
        if any(not record.supporting_text_spans for record in records):
            gaps.append("One or more records lack a query-relevant supporting abstract span.")
        return {"groups": groups, "consensus_level": consensus, "evidence_gaps": gaps}
