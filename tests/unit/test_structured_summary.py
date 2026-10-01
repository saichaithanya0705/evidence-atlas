from types import SimpleNamespace

import pytest

from backend.app.models.request_response import ClaimVerification, EvidenceRecord
from backend.app.workflow.synthesis import EvidenceSynthesizer


def _record(pmid="101", span="Drug A reduced progression by 30% among adults with diabetes."):
    return EvidenceRecord(
        pmid=pmid,
        title="Drug A kidney outcomes",
        supporting_text_spans=[span],
        key_findings=span,
    )


def _settings():
    return SimpleNamespace(
        NVIDIA_MODEL_NAME="fixture-model",
        LLM_MAX_TOKENS=512,
        LLM_SYNTHESIS_MAX_TOKENS=300,
    )


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create),
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.payload))],
        )


class _Verifier:
    available = True

    def __init__(self, supported=True, error=None):
        self.supported = supported
        self.error = error
        self.calls = []

    def verify(self, synthesis, records):
        self.calls.append((synthesis, records))
        if self.error:
            raise self.error
        return [ClaimVerification(
            claim_index=index,
            supported=self.supported,
            supporting_pmids=[records[0].pmid] if self.supported else [],
            rationale="fixture verdict",
        ) for index, _claim in enumerate(synthesis.splitlines())]


def _synthesize(payload, records, verifier):
    return EvidenceSynthesizer(
        client=_Client(payload),
        settings=_settings(),
        semantic_verifier=verifier,
    ).synthesize("Drug A progression", records, [], False)


def test_structured_summary_is_released_after_semantic_verification():
    records = [_record()]
    verifier = _Verifier()
    payload = (
        '{"selections":[{"pmid":"101","span_index":0}],'
        '"summary":[{"text":"Among adults with diabetes, Drug A reduced progression by 30%",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert result.audit.cited_pmids == ["101"]
    assert "Drug A reduced progression by 30%" in result.text
    assert verifier.calls, "nonexact structured prose must pass semantic verification"


def test_structured_summary_merges_multiple_selected_spans_from_one_paper():
    first = "Drug A reduced progression by 30% among adults with diabetes."
    second = "The treatment was well tolerated over 12 months."
    records = [EvidenceRecord(
        pmid="101",
        title="Drug A kidney outcomes",
        supporting_text_spans=[first, second],
        key_findings=first,
    )]

    class MergedSpanVerifier(_Verifier):
        def verify(self, synthesis, selected):
            assert [*selected[0].supporting_text_spans] == [first, second]
            return super().verify(synthesis, selected)

    verifier = MergedSpanVerifier()
    payload = (
        '{"selections":[{"pmid":"101","span_index":0},{"pmid":"101","span_index":1}],'
        '"summary":[{"text":"Drug A reduced progression by 30% among adults with diabetes",'
        '"pmids":["101"]},{"text":"The treatment was well tolerated over 12 months",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert result.audit.cited_pmids == ["101"]
    assert len(verifier.calls) == 1
    assert len(verifier.calls[0][1][0].supporting_text_spans) == 2


def _combined_summary_fixture():
    first = "Drug A reduced progression by 30% among adults."
    second = "Hospitalization fell by 20% over 12 months."
    records = [EvidenceRecord(
        pmid="101",
        title="Drug A outcomes",
        supporting_text_spans=[first, second],
        key_findings=first,
    )]
    selections = '{"pmid":"101","span_index":0},{"pmid":"101","span_index":1}'
    return records, first, second, selections


def test_combined_same_paper_numeric_outcomes_keep_original_audit_spans():
    records, first, second, selections = _combined_summary_fixture()

    class CombinedVerifier(_Verifier):
        def verify(self, synthesis, selected):
            assert selected[0].supporting_text_spans == [first, second]
            return super().verify(synthesis, selected)

    verifier = CombinedVerifier()
    payload = (
        '{"selections":[' + selections + '],'
        '"summary":[{"text":"Drug A reduced progression by 30% and hospitalization fell by 20% over 12 months",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    claim_spans = next(iter(result.audit.claim_support_map.values()))
    assert result.audit.valid
    assert set(claim_spans) == {first, second}
    assert verifier.calls


def test_combined_same_paper_invented_number_falls_back_to_exact_spans():
    records, first, second, selections = _combined_summary_fixture()
    verifier = _Verifier()
    payload = (
        '{"selections":[' + selections + '],'
        '"summary":[{"text":"Drug A reduced progression by 30% and hospitalization fell by 50% over 12 months",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert first.rstrip(".") in result.text and second.rstrip(".") in result.text
    assert "50%" not in result.text


@pytest.mark.parametrize("verifier", [_Verifier(supported=False), _Verifier(error=TimeoutError("offline"))])
def test_combined_same_paper_summary_rejection_or_unavailability_falls_back(verifier):
    records, first, second, selections = _combined_summary_fixture()
    payload = (
        '{"selections":[' + selections + '],'
        '"summary":[{"text":"Drug A reduced progression by 30% and hospitalization fell by 20% over 12 months",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert first.rstrip(".") in result.text and second.rstrip(".") in result.text
    assert "Drug A reduced progression by 30% and hospitalization fell by 20%" not in result.text


@pytest.mark.parametrize("summary", [
    "null",
    "[{\"text\":\"one\",\"pmids\":[\"101\"]},{\"text\":\"two\",\"pmids\":[\"101\"]},{\"text\":\"three\",\"pmids\":[\"101\"]}]",
    "[{\"text\":123,\"pmids\":[\"101\"]}]",
    "[{\"text\":\"Drug A reduced progression by 30%\",\"pmids\":[]}]",
    "[{\"text\":\"Drug A reduced progression [PMID: 101]\",\"pmids\":[\"101\"]}]",
    "[{\"text\":\"Drug A reduced progression by 30%\",\"pmids\":[\"202\"]}]",
    "[{\"text\":\"Drug A reduced progression by 30%\",\"pmids\":[\"999\"]}]",
], ids=["non-list", "too-many-items", "non-string-text", "empty-citations", "embedded-citation", "unselected-known-pmid", "invented-pmid"])
def test_malformed_or_invented_summary_citation_falls_back_to_selected_source(summary):
    records = [_record()]
    verifier = _Verifier()
    if "202" in summary:
        records.append(_record("202", "Drug B improved hospitalization outcomes among adults."))
    payload = '{"selections":[{"pmid":"101","span_index":0}],"summary":' + summary + '}'

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert "Drug A reduced progression by 30% among adults with diabetes" in result.text
    assert "PMID: 101" in result.text
    assert "PMID: 202" not in result.text
    assert "PMID: 999" not in result.text


def test_structured_summary_without_semantic_verifier_falls_back_to_selected_source():
    records = [_record()]
    verifier = _Verifier()
    verifier.available = False
    payload = (
        '{"selections":[{"pmid":"101","span_index":0}],'
        '"summary":[{"text":"Among adults with diabetes, Drug A reduced progression by 30%",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert "Drug A reduced progression by 30% among adults with diabetes" in result.text
    assert verifier.calls == []


@pytest.mark.parametrize("verifier", [_Verifier(supported=False), _Verifier(error=TimeoutError("offline"))])
def test_rejected_or_unavailable_summary_falls_back_to_selected_source(verifier):
    records = [_record()]
    payload = (
        '{"selections":[{"pmid":"101","span_index":0}],'
        '"summary":[{"text":"Among adults with diabetes, Drug A reduced progression by 30%",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert "Drug A reduced progression by 30% among adults with diabetes" in result.text
    assert "Among adults with diabetes, Drug A reduced progression by 30%" not in result.text


def test_changed_numeric_claim_falls_back_to_source_span():
    records = [_record()]
    verifier = _Verifier()
    payload = (
        '{"selections":[{"pmid":"101","span_index":0}],'
        '"summary":[{"text":"Among adults with diabetes, Drug A reduced progression by 40%",'
        '"pmids":["101"]}]}'
    )

    result = _synthesize(payload, records, verifier)

    assert result.audit.valid
    assert "30% among adults with diabetes" in result.text
    assert "40%" not in result.text


def test_selections_only_response_remains_backward_compatible():
    records = [_record()]
    verifier = _Verifier()
    result = _synthesize(
        '{"selections":[{"pmid":"101","span_index":0}]}',
        records,
        verifier,
    )

    assert result.audit.valid
    assert "Drug A reduced progression by 30% among adults with diabetes" in result.text
    assert verifier.calls == []
