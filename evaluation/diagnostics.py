"""Bounded claim and retrieval failure categorization."""

from __future__ import annotations

from typing import Any, Mapping

FAILURE_CATEGORIES = (
    "retriever_miss", "context_noise", "missing_evidence", "extraction_miss",
    "unsupported_generation", "citation_mismatch", "incomplete_answer",
)


def diagnose_failures(sample: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return category and concise evidence only; never persist prompts or reasoning."""
    found: list[dict[str, str]] = []
    relevant = set(map(str, sample.get("relevant_pmids", ())))
    candidates = set(map(str, sample.get("candidate_pmids", ())))
    contexts = set(map(str, sample.get("context_pmids", ())))
    claims = sample.get("claims", ())
    if relevant and not candidates:
        found.append({"category": "retriever_miss", "reason": "no labeled relevant PMID was retrieved"})
    elif relevant and not (relevant & candidates):
        found.append({"category": "context_noise", "reason": "retrieved candidates do not match labeled evidence"})
    if relevant and "context_pmids" in sample and not (relevant & contexts):
        found.append({"category": "missing_evidence", "reason": "relevant candidates were not present in answer context"})
    if sample.get("extraction_miss"):
        found.append({"category": "extraction_miss", "reason": "source evidence was not extracted"})
    if any(isinstance(claim, Mapping) and not claim.get("supported", False) for claim in claims):
        found.append({"category": "unsupported_generation", "reason": "one or more material claims lack support"})
    if any(isinstance(claim, Mapping) and not claim.get("citation_valid", True) for claim in claims):
        found.append({"category": "citation_mismatch", "reason": "one or more citations do not resolve to the cited evidence"})
    required = set(map(str, sample.get("required_subquestions", ())))
    covered = set(map(str, sample.get("covered_subquestions", ())))
    if required - covered:
        found.append({"category": "incomplete_answer", "reason": "one or more required subquestions remain uncovered"})
    return found
