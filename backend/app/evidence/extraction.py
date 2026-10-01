"""Deterministic evidence extraction with exact abstract sentence spans."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from backend.app.models.request_response import (
    EvidenceRecord,
    RetrievalCandidate,
    RetrievalProvenance,
)
from backend.app.query.models import QueryPlan
from backend.app.retrieval.bm25 import tokenize_biomedical_text


_LIMITATION_MARKERS = (
    "limitation", "limited by", "small sample", "short follow-up", "not powered",
    "cannot establish", "did not assess", "further studies", "single-center",
)
_FINDING_MARKERS = ("results:", "conclusion:", "conclusions:", "in this study", "we found", "was associated", "reduced", "increased", "improved", "no significant")
_RESULT_SECTION_MARKERS = ("results:", "result:", "conclusion:", "conclusions:", "recent findings:")
_LOW_VALUE_SECTION_MARKERS = ("background:", "objective:", "objectives:", "aim:", "aims:", "methods:", "method:")
_OUTCOME_MARKERS = (
    "survival", "mortality", "hazard", "predictor", "predictors", "risk", "odds ratio",
    "confidence interval", "associated", "endpoint", "outcome", "remission", "response",
    "progression", "recurrence", "prevalence", "incidence", "sensitivity", "specificity",
)
_AIM_MARKERS = ("aimed to", "aim of", "objective was", "we sought", "we investigated", "was designed to")


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


def score_finding_sentence(sentence: str, terms: Sequence[str]) -> float:
    """Score a source sentence for conservative, query-grounded extraction.

    The score is deliberately extractive: it only orders existing sentences and
    never supplies a claim absent from the source. Query overlap remains a hard
    gate in the caller; structural and clinical signals decide which overlapping
    sentence is most useful.
    """
    tokens = set(tokenize_biomedical_text(sentence))
    if not tokens or not terms:
        return 0.0
    term_set = set(terms)
    overlap = len(tokens.intersection(term_set))
    if not overlap:
        return 0.0

    folded = sentence.casefold()
    # Questions and stated objectives are not observations, even at high overlap.
    if folded.rstrip().endswith("?") or folded.startswith("clinical question:"):
        return 0.0
    # Reward query coverage, but cap the denominator so long expanded queries do
    # not make every sentence look equally weak.
    score = (overlap / max(1, min(len(term_set), 8))) + (0.12 * min(overlap, 5))
    if any(marker in folded for marker in _RESULT_SECTION_MARKERS):
        score += 1.35
    elif any(marker in folded for marker in _FINDING_MARKERS):
        score += 0.25
    if any(marker in folded for marker in _LOW_VALUE_SECTION_MARKERS):
        score -= 0.45
    if any(marker in folded for marker in _AIM_MARKERS):
        score -= 0.25

    outcome_hits = sum(marker in folded for marker in _OUTCOME_MARKERS)
    if re.search(r"\b(?:demonstrat\w*|show\w*|found|reduc\w*|improv\w*)\b.{0,100}\b(?:effectiveness|efficacy|protection|protective|severe|death|mortality)\b", folded):
        score += 1.0
    score += min(0.6, 0.2 * outcome_hits)
    # Numbers matter when they describe an outcome or association. A bare year
    # or sample size in an unrelated sentence receives no special treatment.
    if re.search(r"\d", sentence) and outcome_hits:
        score += 0.3
    return max(0.0, score)


def _query_specificity_score(sentence: str, terms: Sequence[str]) -> float:
    """Backward-compatible scorer name used by existing callers and tests."""
    return score_finding_sentence(sentence, terms)


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
    if re.fullmatch(r"(?:messenger ribonucleic acid|messenger rna|mrna) vaccines?", desired):
        patterns.append(r"\b(?:mRNA|messenger RNA|messenger ribonucleic acid)\s+vaccines?\b")
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
        scored = []
        section = None
        for index, sentence in enumerate(sentences):
            label = re.match(r"^(BACKGROUND|OBJECTIVES?|AIMS?|METHODS?|RESULTS?|CONCLUSIONS?|SUMMARY):", sentence, re.IGNORECASE)
            if label:
                section = label.group(1).casefold()
            score = score_finding_sentence(sentence, terms)
            if score > 0:
                # Structured abstract headings apply to following sentences too.
                # A result need not repeat the disease name to outrank its aim.
                if section in {"result", "results"}:
                    score += 0.5
                elif section in {"background", "method", "methods", "aim", "aims", "objective", "objectives"}:
                    score = max(0.0, score - 0.2)
            scored.append((score, index, sentence))
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
            retrieval_provenance=RetrievalProvenance(
                channel_ranks=dict(candidate.channel_ranks),
                channel_scores=dict(candidate.channel_scores),
                graph_path=list(candidate.graph_path) if candidate.graph_path else None,
                rrf_score=candidate.rrf_score,
                filter_satisfied=candidate.filter_satisfied,
                retrieval_iteration=candidate.retrieval_iteration,
            ),
            reranker_score=candidate.reranker_score,
            reranker_mode=candidate.reranker_mode,
            subquestion_ids=list(candidate.subquestion_ids),
        )

    def extract_all(self, candidates: Iterable[RetrievalCandidate], plan: QueryPlan) -> List[EvidenceRecord]:
        return [self.extract(candidate, plan) for candidate in candidates]


class EvidenceAnalyzer:
    """Create auditable cross-study groups and conservative agreement labels."""

    @staticmethod
    def _group_key(record: EvidenceRecord) -> str:
        return (record.intervention or record.outcome or record.study_design or "unspecified evidence").strip().casefold()

    @classmethod
    def _direction(cls, finding: str) -> Optional[str]:
        # Magnitude is observable; benefit/harm is not inferable from a word
        # such as "higher" or "significant" without a comparable endpoint.
        from backend.app.workflow.synthesis import ClaimToSpanValidator

        directions = {value for dimension, value in ClaimToSpanValidator._directions(finding) if dimension == "magnitude"}
        return next(iter(directions)) if len(directions) == 1 else None

    def analyze(self, records: Sequence[EvidenceRecord], query_plan: QueryPlan) -> dict:
        groups = {}
        for record in records:
            key = self._group_key(record)
            groups.setdefault(key, []).append(record.pmid)
        comparable = {}
        for record in records:
            # Exact source-grounded fields establish comparability. Missing
            # context is uncertainty, not proof of cross-study contradiction.
            if not all((record.population, record.intervention, record.outcome)):
                continue
            key = tuple(str(value or "").strip().casefold() for value in (record.population, record.intervention, record.comparator, record.outcome))
            outcome_spans = [span for span in record.supporting_text_spans if record.outcome.casefold() in span.casefold()]
            direction = self._direction(" ".join(outcome_spans))
            if direction:
                comparable.setdefault(key, []).append(direction)
        opposite_pairs = ({"increase", "decrease"}, {"increase", "negated-increase"}, {"decrease", "negated-decrease"})
        contradiction = any(pair.issubset(directions) for directions in comparable.values() for pair in opposite_pairs)
        agreement = bool(comparable) and sum(map(len, comparable.values())) == len(records) and all(len(directions) >= 2 and len(set(directions)) == 1 for directions in comparable.values())
        if not records:
            consensus = "insufficient"
        elif contradiction:
            consensus = "conflicting"
        elif agreement:
            consensus = "consensus"
        else:
            consensus = "mixed" if len(records) > 1 else "insufficient"

        gaps = []
        pico = getattr(query_plan, "pico", None)
        if len(records) < 2:
            gaps.append("The retrieved evidence contains fewer than two studies for cross-study comparison.")
        for label, value in (("population", getattr(pico, "population", None)), ("intervention", getattr(pico, "intervention", None)), ("comparator", getattr(pico, "comparator", None)), ("outcome", getattr(pico, "outcome", None))):
            if value and not any(getattr(record, label, None) for record in records):
                gaps.append(f"Could not confirm the requested {label} in the selected passages.")
        if any(not record.supporting_text_spans for record in records):
            gaps.append("One or more records lack a query-relevant supporting abstract span.")
        return {"groups": groups, "consensus_level": consensus, "evidence_gaps": gaps}
