"""Deterministic citation-to-evidence integrity checks.

This checks identifier membership and exact quoted-span membership only. It does
not determine whether an abstract semantically supports a generated claim.
"""

from __future__ import annotations

import re
from typing import Any


def _pmid(value: Any) -> str | None:
    match = re.fullmatch(r"\s*(?:PMID\s*:\s*)?(\d+)\s*", str(value or ""), re.IGNORECASE)
    return match.group(1) if match else None


def evaluate_answer_citations(answer: dict[str, Any]) -> dict[str, Any]:
    """Check citation IDs and source spans in saved research response objects.

    Accepts the API response fields ``cited_pmids``, ``retrieved_papers`` and
    ``evidence_table``. A small ``claims``/``evidence`` form is also accepted
    for hand-authored adjudication fixtures. Missing evidence fails closed.
    """
    evidence_by_pmid: dict[str, str] = {}
    evidence_items = answer.get("retrieved_papers") or answer.get("evidence") or []
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        pmid = _pmid(item.get("pmid"))
        abstract = item.get("abstract")
        if pmid and isinstance(abstract, str):
            evidence_by_pmid[pmid] = abstract

    total = 0
    valid_pmids = 0
    total_quotes = 0
    valid_quotes = 0
    invalid: list[dict[str, str]] = []
    claims = answer.get("claims") or []
    if claims:
        for claim_index, claim in enumerate(claims):
            if not isinstance(claim, dict):
                continue
            for citation in claim.get("citations", []) or []:
                total += 1
                if not isinstance(citation, dict):
                    invalid.append({"claim_index": str(claim_index), "reason": "citation_malformed"})
                    continue
                pmid = _pmid(citation.get("pmid"))
                abstract = evidence_by_pmid.get(pmid or "")
                if abstract is not None:
                    valid_pmids += 1
                quote = citation.get("quote")
                if isinstance(quote, str) and quote.strip():
                    total_quotes += 1
                    quote_valid = abstract is not None and quote in abstract
                    if quote_valid:
                        valid_quotes += 1
                else:
                    quote_valid = False

                if abstract is None:
                    invalid.append({"claim_index": str(claim_index), "pmid": pmid or "", "reason": "pmid_not_in_retrieved_evidence"})
                elif isinstance(quote, str) and quote.strip() and not quote_valid:
                    invalid.append({"claim_index": str(claim_index), "pmid": pmid or "", "reason": "quote_not_in_cited_abstract"})
    else:
        cited_pmids = answer.get("cited_pmids") or re.findall(r"\[PMID\s*:\s*(\d+)\]", str(answer.get("synthesis", "")), re.IGNORECASE)
        for cited in cited_pmids:
            total += 1
            pmid = _pmid(cited)
            if pmid and pmid in evidence_by_pmid:
                valid_pmids += 1
            else:
                invalid.append({"pmid": pmid or "", "reason": "pmid_not_in_retrieved_evidence"})

        for record_index, record in enumerate(answer.get("evidence_table", []) or []):
            if not isinstance(record, dict):
                continue
            pmid = _pmid(record.get("pmid"))
            abstract = evidence_by_pmid.get(pmid or "")
            for span in record.get("supporting_text_spans", []) or []:
                total_quotes += 1
                quote_valid = isinstance(span, str) and bool(span.strip()) and abstract is not None and span in abstract
                if quote_valid:
                    valid_quotes += 1
                else:
                    invalid.append({
                        "record_index": str(record_index),
                        "pmid": pmid or "",
                        "reason": "quote_not_in_cited_abstract" if abstract is not None else "pmid_not_in_retrieved_evidence",
                    })

    return {
        "citation_count": total,
        "valid_pmid_count": valid_pmids,
        "pmid_precision": valid_pmids / total if total else None,
        "quoted_span_count": total_quotes,
        "valid_quoted_span_count": valid_quotes,
        "quoted_span_precision": valid_quotes / total_quotes if total_quotes else None,
        "invalid_citations": invalid,
    }
