"""Source identity survives provider outages; novel claims still need verification."""

from types import SimpleNamespace

from backend.app.core.nim_client import llm_request_scope
from backend.app.models.request_response import EvidenceRecord
from backend.app.workflow.service import _validate_release_text
from backend.app.workflow.synthesis import EvidenceSynthesizer


class UnavailableVerifier:
    available = True

    def verify(self, *_args):
        raise TimeoutError("Provider budget exhausted")


def record(pmid="12345", span="Treatment reduced symptom recurrence from 18% to 12%."):
    return EvidenceRecord(pmid=pmid, title="Recurrence study", key_findings=span, supporting_text_spans=[span])


def test_exact_fallback_survives_exhausted_optional_provider():
    evidence = [record()]
    synth = EvidenceSynthesizer(settings=SimpleNamespace(LLM_MODE="mock"), semantic_verifier=UnavailableVerifier())
    with llm_request_scope(0):
        result = synth.synthesize("Treatment and symptom recurrence", evidence, [])
        released, audit = _validate_release_text(result.text, evidence, synth)
    assert result.audit.valid and released
    assert audit.cited_pmids == ["12345"]
    assert evidence[0].supporting_text_spans[0].rstrip(".") in result.text


def test_exact_selected_spans_do_not_require_second_provider_call():
    evidence = [record()]
    text = EvidenceSynthesizer.deterministic_text("recurrence", evidence, [], False)
    synth = EvidenceSynthesizer(client=lambda *_args: text, semantic_verifier=UnavailableVerifier())
    result = synth.synthesize("recurrence", evidence, [])
    assert result.audit.valid and result.audit.cited_pmids == ["12345"]


def test_paraphrase_remains_closed_when_semantic_verifier_fails():
    evidence = [record()]
    synth = EvidenceSynthesizer(semantic_verifier=UnavailableVerifier())
    text = "Treatment reduced symptom recurrence [PMID: 12345]."
    assert synth.validator.validate(text, evidence).valid
    released, _ = _validate_release_text(text, evidence, synth)
    assert not released


def test_exact_gate_requires_every_cited_source_to_match():
    evidence = [record(), record("67890", "Treatment was assessed for symptom recurrence.")]
    text = "Treatment reduced symptom recurrence from 18% to 12% [PMID: 12345] [PMID: 67890]."
    assert not EvidenceSynthesizer._is_exact_span_text(text, evidence)


def test_wrong_numbers_and_reversed_effect_cannot_take_exact_path():
    evidence = [record()]
    synth = EvidenceSynthesizer(semantic_verifier=UnavailableVerifier())
    for text in ["Treatment reduced symptom recurrence from 18% to 6% [PMID: 12345].", "Treatment increased symptom recurrence from 18% to 12% [PMID: 12345]."]:
        assert not EvidenceSynthesizer._is_exact_span_text(text, evidence)
        assert not _validate_release_text(text, evidence, synth)[0]


def test_fallback_can_cover_multiple_outcomes_from_one_stronger_paper():
    weak = record("1", "BACKGROUND: Survival outcomes are of interest.")
    findings = [
        "RESULTS: Median survival was 36 months.",
        "RESULTS: Mortality risk increased with age (hazard ratio 2.1).",
        "RESULTS: Renal survival was 24 months.",
    ]
    strong = record("2", findings[0]).model_copy(update={"supporting_text_spans": findings})
    selected = EvidenceSynthesizer._fallback_records("renal survival mortality outcomes", [weak, strong])
    strong_selection = next(item for item in selected if item.pmid == "2")
    assert set(strong_selection.supporting_text_spans) == set(findings)
    assert sum(len(item.supporting_text_spans) for item in selected) <= 4


def test_fallback_does_not_fill_answer_with_unrelated_numeric_spans():
    selected = EvidenceSynthesizer._fallback_records("renal survival", [record("1", "RESULTS: The assay used 5 mL of blood.")])
    assert selected == []


def test_explicit_condition_subtypes_do_not_substitute_for_requested_scope():
    requested = record("1", "Survival was 24 months in XY cardiomyopathy.")
    other = record("2", "Survival was 36 months in YZ cardiomyopathy.")
    comparison = record("3", "XY cardiomyopathy and YZ cardiomyopathy had different survival outcomes.")
    unspecified = record("4", "Survival was assessed in cardiomyopathy.")
    assert EvidenceSynthesizer._scope_records("XY cardiomyopathy survival", [requested, other, comparison, unspecified]) == [requested, comparison, unspecified]
