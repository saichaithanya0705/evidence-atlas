from types import SimpleNamespace

import pytest

from backend.app.evidence.extraction import EvidenceExtractor
from backend.app.models.request_response import EvidenceRecord, RetrievalCandidate
from backend.app.query.models import PICOModel, QueryPlan
from backend.app.workflow.repair import TargetedClaimRepairer
from backend.app.workflow.synthesis import ClaimToSpanValidator, EvidenceSynthesizer, _claims


def _record(span: str, *, year: int | None = None) -> EvidenceRecord:
    return EvidenceRecord(
        pmid="12345",
        title="Study title",
        year=year,
        study_design="Randomized Controlled Trial",
        population="adults with diabetes",
        intervention="drug A",
        comparator="placebo",
        outcome="kidney disease progression",
        key_findings=span,
        limitations="Short follow-up.",
        supporting_text_spans=[span],
    )


def _audit(claim: str, span: str, *, year: int | None = None):
    return ClaimToSpanValidator().validate(
        claim.rstrip(" .") + " [PMID: 12345].", [_record(span, year=year)]
    )


def test_claim_validator_rejects_opposite_direction_and_negation():
    opposite = _audit(
        "Drug A reduced kidney disease progression.",
        "Drug A increased kidney disease progression.",
    )
    negated = _audit(
        "Drug A reduced kidney disease progression.",
        "Drug A did not reduce kidney disease progression.",
    )

    assert not opposite.valid
    assert not negated.valid


def test_claim_validator_rejects_unsupported_numbers_but_accepts_record_year():
    wrong_count = _audit(
        "Drug A reduced kidney disease progression by 35%.",
        "Drug A reduced kidney disease progression by 25%.",
    )
    supported_year = _audit(
        "In 2021, drug A reduced kidney disease progression.",
        "Drug A reduced kidney disease progression.",
        year=2021,
    )

    assert not wrong_count.valid
    assert supported_year.valid


def test_deterministic_source_line_with_et_al_abbreviation_remains_grounded():
    span = (
        "Accordingly, the 0.44% reduction found by Kohan et al. in patients "
        "with chronic kidney disease might have been anticipated."
    )
    record = _record(span)
    text = EvidenceSynthesizer.deterministic_text("kidney outcomes", [record], [], False)

    audit = ClaimToSpanValidator().validate(text, [record])

    assert audit.valid
    assert not audit.unsupported_claims


def test_pico_extracts_full_expanded_sglt2_intervention_and_clean_population():
    from backend.app.query.extractor import PICOExtractor

    plan = PICOExtractor().extract(
        "What are the kidney outcomes of SGLT2 inhibitors in chronic kidney disease?",
        "What are the kidney outcomes of Sodium-Glucose Cotransporter-2 inhibitors in chronic kidney disease?",
    )

    assert plan.intervention == "Sodium-Glucose Cotransporter-2 inhibitors"
    assert plan.population == "chronic kidney disease"
    assert plan.outcome == "Kidney outcomes"


def test_extraction_propagates_year_and_synthesis_context_includes_comparison_fields():
    candidate = RetrievalCandidate(
        pmid="12345",
        title="Study title",
        year=2021,
        study_type="Randomized Controlled Trial",
        abstract=(
            "Among adults with diabetes receiving drug A, compared with placebo, "
            "kidney disease progression was reduced."
        ),
    )
    plan = QueryPlan(
        original_query="drug A kidney disease",
        clean_query="drug A kidney disease",
        canonical_query="drug A kidney disease",
        concepts=["drug A", "kidney disease"],
        pico=PICOModel(
            population="adults with diabetes",
            intervention="drug A",
            comparator="placebo",
            outcome="kidney disease progression",
        ),
    )
    extracted = EvidenceExtractor().extract(candidate, plan)
    seen = {}

    def model(_query, evidence, _gaps, _insufficient):
        seen["evidence"] = evidence
        span = evidence[0]["supporting_text_spans"][0].rstrip(" .")
        return f"{span} [PMID: 12345]."

    result = EvidenceSynthesizer(client=model).synthesize("drug A kidney disease", [extracted], [])
    context = seen["evidence"][0]

    assert extracted.year == 2021
    assert result.mode == "nvidia_nim"
    assert {
        "year": context["year"],
        "population": context["population"],
        "intervention": context["intervention"],
        "comparator": context["comparator"],
        "outcome": context["outcome"],
        "study_design": context["study_design"],
        "key_findings": context["key_findings"],
        "limitations": context["limitations"],
    } == {
        "year": 2021,
        "population": "adults with diabetes",
        "intervention": "drug A",
        "comparator": "placebo",
        "outcome": "kidney disease progression",
        "study_design": "Randomized Controlled Trial",
        "key_findings": (
            "Among adults with diabetes receiving drug A, compared with placebo, "
            "kidney disease progression was reduced."
        ),
        "limitations": None,
    }


def test_no_evidence_skips_model_call_and_returns_valid_abstention():
    def should_not_run(*_args):
        raise AssertionError("A model call without source evidence is wasteful")

    result = EvidenceSynthesizer(client=should_not_run).synthesize(
        "rare disease treatment", [], [], insufficient=True
    )

    assert result.mode == "deterministic_spans"
    assert result.audit.valid
    assert result.audit.cited_pmids == []
    assert result.timings_ms["generation"] == 0.0


def test_limited_metadata_is_not_a_claim_but_real_claims_remain_validated():
    span = "Drug A reduced kidney disease progression."
    record = _record(span)
    metadata = (
        "The full question was not established by the available evidence.\n"
        "Evidence gaps are listed separately in the response."
    )
    grounded = f"{span} [PMID: 12345]\n{metadata}"
    unsupported = f"Drug A cured every patient [PMID: 12345]\n{metadata}"
    caveat_with_claim = "The full question was not established by the available evidence. Drug A cured every patient [PMID: 12345]"
    gap_notice_with_claim = "Evidence gaps are listed separately in the response. Drug A cured every patient [PMID: 12345]"
    arbitrary_gap_prefix = "Evidence gaps: Drug A cured every patient [PMID: 12345]"

    assert _claims(grounded) == ["Drug A reduced kidney disease progression. [PMID: 12345]"]
    assert ClaimToSpanValidator().validate(grounded, [record]).valid
    assert not ClaimToSpanValidator().validate(unsupported, [record]).valid
    assert not ClaimToSpanValidator().validate(caveat_with_claim, [record]).valid
    assert not ClaimToSpanValidator().validate(gap_notice_with_claim, [record]).valid
    assert not ClaimToSpanValidator().validate(arbitrary_gap_prefix, [record]).valid


@pytest.mark.parametrize(
    "text",
    [
        "The full question was not established by the available evidence. Drug A cured every patient [PMID: 12345]",
        "Evidence gaps: Drug A cured every patient [PMID: 12345]",
    ],
)
def test_arbitrary_text_appended_to_metadata_prefix_remains_a_validated_claim(text):
    record = _record("Drug A reduced kidney disease progression.")

    assert _claims(text) == [text]
    assert not ClaimToSpanValidator().validate(text, [record]).valid


def test_nim_span_selection_is_validated_and_rendered_from_source():
    raw = '{"selections":[{"pmid":"12345","span_index":0}]}'
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
    settings = SimpleNamespace(NVIDIA_MODEL_NAME="fake", LLM_MAX_TOKENS=2048, LLM_SYNTHESIS_MAX_TOKENS=300)
    span = "Drug A reduced kidney disease progression among adults with diabetes."

    result = EvidenceSynthesizer(client=client, settings=settings).synthesize("kidney outcomes", [_record(span)], [])

    assert result.mode == "nvidia_nim"
    assert result.audit.valid
    assert result.audit.cited_pmids == ["12345"]
    assert span.rstrip(".") in result.text


def test_nim_rejects_unknown_span_and_falls_back_to_source():
    raw = '{"selections":[{"pmid":"12345","span_index":9}]}'
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: response)))
    settings = SimpleNamespace(NVIDIA_MODEL_NAME="fake", LLM_MAX_TOKENS=2048, LLM_SYNTHESIS_MAX_TOKENS=300)

    result = EvidenceSynthesizer(client=client, settings=settings).synthesize("kidney outcomes", [_record("Drug A reduced kidney disease progression.")], [])

    assert result.mode == "deterministic_spans"
    assert result.audit.valid
    assert "unknown PMID or source span" in result.fallback_reason


def test_targeted_repair_preserves_supported_claim_and_replaces_only_failed_claim():
    from backend.app.models.request_response import ClaimVerification

    first_span = "Drug A reduced kidney disease progression among adults with diabetes."
    second_span = "Drug B improved survival among adults with cancer."
    original = (
        "Evidence summary:\n"
        f"{first_span[:-1]} [PMID: 12345].\n"
        "Drug B improved survival in every patient [PMID: 54321].\n"
        "Evidence gaps are listed separately in the response."
    )
    records = [
        _record(first_span),
        _record(second_span).model_copy(update={"pmid": "54321"}),
    ]
    audit = ClaimToSpanValidator().validate(original, records)
    result = TargetedClaimRepairer().repair(
        original,
        records,
        audit,
        [
            ClaimVerification(
                claim_index=0, supported=True, supporting_pmids=["12345"], rationale="supported"
            ),
            ClaimVerification(
                claim_index=1, supported=False, supporting_pmids=[], rationale="overstated"
            ),
        ],
    )

    assert f"{first_span[:-1]} [PMID: 12345]." in result.text
    assert f"{second_span[:-1]} [PMID: 54321]." in result.text
    assert "in every patient" not in result.text
    assert result.text.startswith("Evidence summary:\n")
    assert result.text.endswith("Evidence gaps are listed separately in the response.")
    assert (result.preserved_claims, result.repaired_claims, result.pruned_claims) == (1, 1, 0)
    assert result.attempt_count == 1


def test_targeted_repair_never_introduces_a_new_pmid_and_prunes_without_exact_span():
    from backend.app.models.request_response import ClaimVerification
    from backend.app.workflow.synthesis import extract_cited_pmids

    original = "Drug A cured every patient [PMID: 12345]."
    records = [_record("Drug A reduced kidney disease progression.")]
    result = TargetedClaimRepairer().repair(
        original,
        records,
        ClaimToSpanValidator().validate(original, records),
        [ClaimVerification(
            claim_index=0, supported=False, supporting_pmids=["99999"], rationale="unsupported"
        )],
    )

    assert result.text == ""
    assert result.repaired_claims == 0
    assert result.pruned_claims == 1
    assert result.attempt_count == 1
    assert extract_cited_pmids(result.text) == []
