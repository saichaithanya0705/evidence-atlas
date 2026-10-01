import json
from types import SimpleNamespace

import pytest
import re

from backend.app.models.request_response import ClaimVerification, EvidenceRecord
from backend.app.workflow.synthesis import EvidenceSynthesizer, _claims
import backend.app.workflow.synthesis as synthesis_module
from backend.app.core import nim_client
from backend.app.core.config import Settings


def _record(pmid: str, span: str) -> EvidenceRecord:
    return EvidenceRecord(pmid=pmid, title=f"Study {pmid}", key_findings=span, supporting_text_spans=[span])


def _records(include_unselected=False):
    records = [
        _record("101", "Median renal survival was 24 months."),
        _record("202", "Dialysis occurred in 42% of participants."),
        _record("303", "Older age predicted shorter survival (hazard ratio 2.1)."),
    ]
    if include_unselected:
        records.append(_record("404", "The unrelated assay result was negative."))
    return records


def _report():
    return {
        "findings": [
            {"text": "Median renal survival was 24 months.", "pmids": ["101"]},
            {"text": "Dialysis occurred in 42% of participants.", "pmids": ["202"]},
            {"text": "Older age predicted shorter survival (hazard ratio 2.1).", "pmids": ["303"]},
        ],
        "connections": [{"text": "Median renal survival was 24 months and dialysis occurred in 42% of participants.", "pmids": ["101", "202"]}],
        "summary": [{"text": "Older age predicted shorter survival (hazard ratio 2.1).", "pmids": ["303"]}],
    }


class _Verifier:
    available = True

    def __init__(self, supported=True, incomplete=False):
        self.supported = supported
        self.incomplete = incomplete
        self.calls = []

    def verify(self, text, records):
        self.calls.append((text, records))
        if self.incomplete:
            return []
        by_pmid = {record.pmid for record in records}
        verdicts = []
        for i, claim in enumerate(_claims(text)):
            cited = [pmid for pmid in re.findall(r"\[PMID:\s*([^\]]+)\]", claim) if pmid in by_pmid]
            verdicts.append(ClaimVerification(
                claim_index=i,
                supported=self.supported,
                supporting_pmids=cited if self.supported else [],
                rationale="fixture",
            ))
        return verdicts


class _ChatClient:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.payloads:
            raise AssertionError("unexpected provider call")
        payload = self.payloads.pop(0)
        if isinstance(payload, BaseException):
            raise payload
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def _selection_payload(report, *, pmids=("101", "202", "303")):
    return {
        "selections": [{"pmid": pmid, "span_index": 0} for pmid in pmids],
        "report": report,
    }


def _settings():
    return SimpleNamespace(
        NVIDIA_MODEL_NAME="fixture-model",
        LLM_MAX_TOKENS=2048,
        LLM_SYNTHESIS_MAX_TOKENS=2048,
        LLM_SYNTHESIS_TIMEOUT_SECONDS=30,
        LLM_TIMEOUT_SECONDS=30,
        LLM_STRUCTURED_TIMEOUT_SECONDS=10,
    )


def _synth(verifier=None):
    return EvidenceSynthesizer(semantic_verifier=verifier or _Verifier())


def test_valid_report_has_exact_schema_and_all_three_sections_across_papers():
    result = _synth()._validated_report(_report(), _records())

    assert isinstance(result, str)
    assert result.count("Findings and sources:") == 1
    assert result.count("How the studies relate:") == 1
    assert result.count("Final summary:") == 1
    assert all(f"[PMID: {pmid}]" in result for pmid in ("101", "202", "303"))


@pytest.mark.parametrize("mutate", [
    lambda report: report.update({"extra": []}),
    lambda report: report["findings"].append({"text": "x" * 1001, "pmids": ["101"]}),
    lambda report: report["findings"].append({"text": "Unknown source", "pmids": ["999"]}),
    lambda report: report["summary"].__setitem__(0, {"text": "Invented [PMID: 101]", "pmids": ["101"]}),
    lambda report: report["connections"].__setitem__(0, {"text": "Line one\nline two", "pmids": ["101", "202"]}),
])
def test_malformed_oversize_unknown_or_embedded_citation_report_is_rejected(mutate):
    report = _report()
    mutate(report)
    assert _synth()._validated_report(report, _records()) is None


def test_report_over_500_words_rejected_before_semantic_verification():
    report = _report()
    # Five items x 105 words exceeds the aggregate 500-word cap while each
    # individual paragraph stays below the 1000-character cap.
    filler = " clinical evidence reported" * 35
    for section in ("findings", "connections", "summary"):
        report[section][0]["text"] += filler
    verifier = _Verifier()
    assert _synth(verifier)._validated_report(report, _records()) is None
    assert verifier.calls == []


@pytest.mark.parametrize("mutate", [
    lambda report: report.update({"findings": []}),
    lambda report: report.update({"findings": report["findings"] + [{"text": "extra", "pmids": ["101"]}, {"text": "extra2", "pmids": ["101"]}]}),
    lambda report: report.update({"connections": "not a list"}),
    lambda report: report.update({"summary": [{"text": "x", "pmids": ["101"]}] * 3}),
])
def test_report_sections_require_expected_nonempty_cardinalities_and_types(mutate):
    report = _report()
    mutate(report)
    assert _synth()._validated_report(report, _records()) is None


def test_unselected_pmid_is_rejected_even_when_text_matches_a_selected_span():
    client = _ChatClient(_selection_payload(_report(), pmids=("101", "202", "303")))
    report = _report()
    report["summary"] = [{"text": "Median renal survival was 24 months.", "pmids": ["404"]}]
    client.payloads[0] = _selection_payload(report)
    result = EvidenceSynthesizer(client=client, settings=_settings(), semantic_verifier=_Verifier()).synthesize(
        "renal survival", _records(include_unselected=True), []
    )
    assert "[PMID: 404]" not in result.text
    assert "Median renal survival was 24 months" in result.text


def test_invented_numeric_claim_fails_citation_gate_before_semantic_verifier():
    records = _records()
    report = _report()
    report["summary"] = [{"text": "Median renal survival was 99 months.", "pmids": ["101"]}]
    verifier = _Verifier()
    assert _synth(verifier)._validated_report(report, records) is None
    assert verifier.calls == []


def test_lexically_plausible_causal_claim_is_rejected_by_semantic_verifier():
    records = _records()
    report = _report()
    report["summary"] = [{"text": "Older age caused shorter survival (hazard ratio 2.1).", "pmids": ["303"]}]
    verifier = _Verifier(supported=False)
    assert _synth(verifier)._validated_report(report, records) is None
    assert verifier.calls


def test_incomplete_semantic_verdict_fails_closed():
    assert _synth(_Verifier(incomplete=True))._validated_report(_report(), _records()) is None


def test_claim_extraction_ignores_fixed_report_headings():
    text = _synth()._validated_report(_report(), _records())
    assert text.splitlines()[0] == "Findings and sources:"
    assert all("Findings and sources:" not in claim for claim in synthesis_module._claims(text))


def test_invalid_initial_report_is_revised_once_and_released_when_valid():
    invalid = _report()
    invalid["summary"] = [{"text": "Median renal survival was 99 months.", "pmids": ["101"]}]
    client = _ChatClient(_selection_payload(invalid), {"report": _report()})
    result = EvidenceSynthesizer(client=client, settings=_settings(), semantic_verifier=_Verifier()).synthesize(
        "renal survival", _records(), []
    )
    assert result.mode == "nvidia_nim"
    assert "Findings and sources:" in result.text
    assert len(client.calls) == 2


@pytest.mark.parametrize("second", [
    {"report": {"findings": [], "connections": [], "summary": []}},
    TimeoutError("revision timeout"),
])
def test_invalid_revision_falls_back_to_exact_selected_spans_and_never_retries_twice(second):
    invalid = _report()
    invalid["summary"] = [{"text": "Median renal survival was 99 months.", "pmids": ["101"]}]
    client = _ChatClient(_selection_payload(invalid), second)
    result = EvidenceSynthesizer(client=client, settings=_settings(), semantic_verifier=_Verifier()).synthesize(
        "renal survival", _records(), []
    )
    assert "Median renal survival was 24 months" in result.text
    assert "99 months" not in result.text
    assert len(client.calls) == 2


def test_retry_is_skipped_when_remaining_budget_is_below_fifteen_seconds(monkeypatch):
    invalid = _report()
    invalid["summary"] = [{"text": "Median renal survival was 99 months.", "pmids": ["101"]}]
    client = _ChatClient(_selection_payload(invalid), {"report": _report()})
    monkeypatch.setattr(synthesis_module, "llm_time_remaining", lambda: 10.0)
    result = EvidenceSynthesizer(client=client, settings=_settings(), semantic_verifier=_Verifier()).synthesize(
        "renal survival", _records(), []
    )
    assert "Median renal survival was 24 months" in result.text
    assert len(client.calls) == 1


def test_synthesis_defaults_are_bounded():
    assert Settings.model_fields["LLM_SYNTHESIS_MAX_TOKENS"].default == 2048
    assert Settings.model_fields["LLM_SYNTHESIS_TIMEOUT_SECONDS"].default == 30.0
    assert Settings.model_fields["LLM_RESEARCH_BUDGET_SECONDS"].default == 60.0


def test_chat_generation_sends_expanded_token_and_timeout_bounds():
    client = _ChatClient(_selection_payload(_report()))
    EvidenceSynthesizer(client=client, settings=_settings(), semantic_verifier=_Verifier()).synthesize(
        "renal survival", _records(), []
    )
    assert client.calls[0]["max_tokens"] == 2048
    assert client.calls[0]["timeout"] == 30


def test_structured_call_override_respects_global_budget_and_small_default(monkeypatch):
    settings = SimpleNamespace(LLM_TIMEOUT_SECONDS=30, LLM_STRUCTURED_TIMEOUT_SECONDS=10)
    assert nim_client.structured_completion_options(settings, timeout_seconds=30)["timeout"] == 30
    assert nim_client.structured_completion_options(settings)["timeout"] == 10

    clock = iter([100.0, 100.0])
    monkeypatch.setattr(nim_client, "monotonic", lambda: next(clock))
    with nim_client.llm_request_scope(20):
        assert nim_client.structured_completion_options(settings, timeout_seconds=30)["timeout"] == 20


def test_structured_call_timeout_is_capped_by_remaining_request_budget(monkeypatch):
    settings = SimpleNamespace(LLM_TIMEOUT_SECONDS=30, LLM_STRUCTURED_TIMEOUT_SECONDS=10)
    clock = iter([100.0, 116.0])
    monkeypatch.setattr(nim_client, "monotonic", lambda: next(clock))
    with nim_client.llm_request_scope(20):
        assert nim_client.structured_completion_options(settings, timeout_seconds=30)["timeout"] == 4


def test_nim_report_outage_or_malformed_report_returns_exact_span_fallback():
    records = _records()
    for client in (lambda *_args: (_ for _ in ()).throw(TimeoutError("offline")), lambda *_args: (_ for _ in ()).throw(ValueError("not json"))):
        synth = EvidenceSynthesizer(client=client, semantic_verifier=_Verifier())
        result = synth.synthesize("renal survival", records, [])
        assert any(span.rstrip(".") in result.text for record in records for span in record.supporting_text_spans)
        assert result.text != ""
