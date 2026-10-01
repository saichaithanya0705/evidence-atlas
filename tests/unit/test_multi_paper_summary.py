import json
from types import SimpleNamespace

import pytest

from backend.app.models.request_response import ClaimVerification, EvidenceRecord
from backend.app.workflow.synthesis import EvidenceSynthesizer
from backend.app.workflow.verification import SemanticClaimVerifier


def _settings():
    return SimpleNamespace(
        NVIDIA_MODEL_NAME="fixture-model",
        LLM_MAX_TOKENS=512,
        LLM_SYNTHESIS_MAX_TOKENS=300,
    )


def _record(pmid, span):
    return EvidenceRecord(pmid=pmid, title=f"Study {pmid}", key_findings=span, supporting_text_spans=[span])


def _records():
    first = "Drug A reduced kidney progression by 30% among adults with diabetes."
    second = "Hospitalization fell by 20% over 12 months among adults with diabetes."
    return [_record("101", first), _record("202", second)], first, second


class _Client:
    def __init__(self, content):
        self.content = content
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


class _SemanticStub:
    available = True

    def __init__(self, supported=True, error=None):
        self.supported = supported
        self.error = error
        self.calls = []

    def verify(self, synthesis, records):
        self.calls.append((synthesis, records))
        if self.error:
            raise self.error
        pmids = [record.pmid for record in records]
        return [ClaimVerification(
            claim_index=index,
            supported=self.supported,
            supporting_pmids=pmids if self.supported else [],
            rationale="fixture semantic verdict",
        ) for index, _claim in enumerate(synthesis.splitlines())]


def _summary_payload(text, pmids=("101", "202")):
    return json.dumps({
        "selections": [
            {"pmid": "101", "span_index": 0},
            {"pmid": "202", "span_index": 0},
        ],
        "summary": [{"text": text, "pmids": list(pmids)}],
    })


def _synthesize(payload, records, verifier):
    return EvidenceSynthesizer(
        client=_Client(payload),
        settings=_settings(),
        semantic_verifier=verifier,
    ).synthesize("Drug A kidney outcomes", records, [], False)


def test_combined_summary_across_two_papers_passes_and_audits_original_spans():
    records, first, second = _records()
    verifier = _SemanticStub()
    text = "Drug A reduced kidney progression by 30% and hospitalization fell by 20% over 12 months among adults with diabetes"

    result = _synthesize(_summary_payload(text), records, verifier)

    assert result.audit.valid
    assert result.audit.cited_pmids == ["101", "202"]
    assert set(next(iter(result.audit.claim_support_map.values()))) == {first, second}
    assert verifier.calls


def test_semantic_verifier_receives_source_specific_accepted_evidence_for_joint_claim():
    records, first, second = _records()
    provider = _Client(json.dumps({
        "verdicts": [{
            "claim_index": 0,
            "supported": True,
            "supporting_pmids": ["101", "202"],
            "rationale": "Both source passages jointly support the claim.",
        }],
    }))
    verifier = SemanticClaimVerifier(client=provider)
    text = "Drug A reduced kidney progression by 30% and hospitalization fell by 20% over 12 months among adults with diabetes [PMID: 101] [PMID: 202]."

    verdicts = verifier.verify(text, records)

    assert verdicts[0].supported
    body = json.loads(provider.calls[0]["messages"][1]["content"])
    accepted = {item["pmid"]: item["spans"] for item in body["accepted_evidence"]}
    assert accepted == {"101": [first], "202": [second]}


def test_joint_claim_missing_one_semantic_supporting_pmid_fails_closed():
    records, _first, _second = _records()
    provider = _Client(json.dumps({
        "verdicts": [{
            "claim_index": 0,
            "supported": True,
            "supporting_pmids": ["101"],
            "rationale": "Only one source was returned.",
        }],
    }))
    verifier = SemanticClaimVerifier(client=provider)
    text = "Drug A reduced kidney progression by 30% and hospitalization fell by 20% over 12 months among adults with diabetes [PMID: 101] [PMID: 202]."

    verdicts = verifier.verify(text, records)

    assert verdicts[0].supported is False
    assert verdicts[0].supporting_pmids == []


def test_invented_joint_numeric_outcome_falls_back_to_exact_selected_sources():
    records, first, second = _records()
    verifier = _SemanticStub()
    text = "Drug A reduced kidney progression by 40% and hospitalization fell by 20% over 12 months among adults with diabetes"

    result = _synthesize(_summary_payload(text), records, verifier)

    assert result.audit.valid
    assert first.rstrip(".") in result.text and second.rstrip(".") in result.text
    assert "40%" not in result.text


@pytest.mark.parametrize("verifier", [_SemanticStub(supported=False), _SemanticStub(error=TimeoutError("offline"))])
def test_rejected_or_unavailable_joint_summary_falls_back_to_exact_sources(verifier):
    records, first, second = _records()
    text = "Drug A reduced kidney progression by 30% and hospitalization fell by 20% over 12 months among adults with diabetes"

    result = _synthesize(_summary_payload(text), records, verifier)

    assert result.audit.valid
    assert first.rstrip(".") in result.text and second.rstrip(".") in result.text
    assert "Drug A reduced kidney progression by 30% and hospitalization fell by 20%" not in result.text


def test_causal_joint_claim_rejected_by_semantic_provider_is_not_released():
    records, first, second = _records()
    verifier = _SemanticStub(supported=False)
    text = "Drug A caused a 30% reduction in kidney progression and prevented hospitalization by 20% over 12 months among adults with diabetes"

    result = _synthesize(_summary_payload(text), records, verifier)

    assert first.rstrip(".") in result.text and second.rstrip(".") in result.text
    assert "caused a 30% reduction" not in result.text
    assert "prevented hospitalization" not in result.text
