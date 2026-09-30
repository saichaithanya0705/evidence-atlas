"""Bounded claim-local repair using only already accepted evidence spans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backend.app.models.request_response import ClaimVerification, EvidenceRecord
from backend.app.workflow.synthesis import (
    CitationAudit,
    ClaimToSpanValidator,
    _PMID_PATTERN,
    _claims,
    extract_cited_pmids,
)


@dataclass(frozen=True)
class ClaimRepairResult:
    text: str
    preserved_claims: int
    repaired_claims: int
    pruned_claims: int
    attempt_count: int

    def metadata(self) -> dict[str, int]:
        return {
            "preserved_claims": self.preserved_claims,
            "repaired_claims": self.repaired_claims,
            "pruned_claims": self.pruned_claims,
            "attempt_count": self.attempt_count,
        }


def _render_span(span: str, pmid: str) -> str:
    clean = " ".join(span.split()).strip()
    body = clean.rstrip(".!? ")
    ending = clean[len(body):] or "."
    return f"{body} [PMID: {pmid}]{ending}"


class TargetedClaimRepairer:
    """Preserve supported claims and replace failures from their cited sources."""

    def __init__(self, validator: ClaimToSpanValidator | None = None) -> None:
        self.validator = validator or ClaimToSpanValidator()

    def _replacement(
        self,
        claim: str,
        records: Sequence[EvidenceRecord],
        audit: CitationAudit,
    ) -> str | None:
        accepted_spans = set(audit.claim_support_map.get(claim, []))
        if not accepted_spans:
            return None
        by_pmid = {record.pmid: record for record in records}
        for pmid in extract_cited_pmids(claim):
            record = by_pmid.get(pmid)
            if record is None:
                continue
            for span in record.supporting_text_spans:
                if span in accepted_spans:
                    return _render_span(span, pmid)
        return None

    @staticmethod
    def _rebuild(text: str, actions: dict[int, str | None]) -> str:
        output: list[str] = []
        claim_index = 0
        for raw_line in (text or "").splitlines():
            line_claims = _claims(raw_line)
            if not line_claims:
                if raw_line.strip():
                    output.append(raw_line)
                continue
            if len(line_claims) == 1 and actions.get(claim_index) == line_claims[0]:
                output.append(raw_line)
                claim_index += 1
                continue
            for _claim in line_claims:
                replacement = actions.get(claim_index)
                if replacement:
                    output.append(replacement)
                claim_index += 1
        return "\n".join(output).strip()

    def repair(
        self,
        text: str,
        records: Sequence[EvidenceRecord],
        audit: CitationAudit,
        verdicts: Sequence[ClaimVerification],
    ) -> ClaimRepairResult:
        claims = _claims(text)
        verdict_by_index = {item.claim_index: item for item in verdicts}
        actions: dict[int, str | None] = {}
        preserved = repaired = pruned = 0
        needs_repair = False

        for index, claim in enumerate(claims):
            verdict = verdict_by_index.get(index)
            if verdict is not None and verdict.supported:
                actions[index] = claim
                preserved += 1
                continue
            needs_repair = True
            replacement = self._replacement(claim, records, audit)
            actions[index] = replacement
            if replacement is None:
                pruned += 1
            else:
                repaired += 1

        repaired_text = self._rebuild(text, actions)
        original_pmids = set(extract_cited_pmids(text))
        if any(pmid not in original_pmids for pmid in extract_cited_pmids(repaired_text)):
            repaired_text = ""
            pruned = len(claims)
            preserved = repaired = 0
        return ClaimRepairResult(
            text=repaired_text,
            preserved_claims=preserved,
            repaired_claims=repaired,
            pruned_claims=pruned,
            attempt_count=1 if needs_repair else 0,
        )

    @classmethod
    def prune_unsupported(
        cls,
        text: str,
        verdicts: Sequence[ClaimVerification],
    ) -> tuple[str, int]:
        claims = _claims(text)
        verdict_by_index = {item.claim_index: item for item in verdicts}
        actions = {
            index: claim if verdict_by_index.get(index) is not None
            and verdict_by_index[index].supported else None
            for index, claim in enumerate(claims)
        }
        pruned = sum(value is None for value in actions.values())
        return cls._rebuild(text, actions), pruned
