from backend.app.evidence.extraction import EvidenceExtractor
from backend.app.models.request_response import EvidenceRecord, RetrievalCandidate
from backend.app.query.models import PICOModel, QueryPlan
from backend.app.workflow.synthesis import ClaimToSpanValidator, EvidenceSynthesizer


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
