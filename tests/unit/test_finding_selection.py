from backend.app.evidence.extraction import EvidenceExtractor, score_finding_sentence
from backend.app.models.request_response import RetrievalCandidate
from backend.app.query.models import PICOModel, QueryPlan


def _plan(query: str, *, concepts=None, outcome=None) -> QueryPlan:
    return QueryPlan(
        original_query=query,
        clean_query=query,
        canonical_query=query,
        concepts=list(concepts or []),
        pico=PICOModel(outcome=outcome),
    )


def _candidate(abstract: str) -> RetrievalCandidate:
    return RetrievalCandidate(pmid="synthetic", title="Synthetic study", abstract=abstract)


def test_results_with_query_relevance_beat_unrelated_results_and_keep_exact_spans():
    abstract = (
        "RESULTS: The cohort had a median renal survival of 24 months (95% CI 18-31). "
        "RESULTS: Serum sodium was 139 mmol/L at baseline. "
        "CONCLUSION: Dialysis at presentation and high proteinuria predicted shorter renal survival."
    )

    record = EvidenceExtractor(max_spans_per_paper=2).extract(
        _candidate(abstract),
        _plan("renal survival predictors", concepts=["renal survival", "predictors"], outcome="renal survival"),
    )

    assert record.supporting_text_spans == [
        "RESULTS: The cohort had a median renal survival of 24 months (95% CI 18-31).",
        "CONCLUSION: Dialysis at presentation and high proteinuria predicted shorter renal survival.",
    ]
    assert record.key_findings == " ".join(record.supporting_text_spans)
    assert "139 mmol/L" not in record.key_findings


def test_high_overlap_aim_does_not_crowd_out_result_sentence():
    abstract = (
        "OBJECTIVE: We aimed to characterize renal survival predictors and outcomes in amyloid disease. "
        "RESULTS: Median renal survival was 24 months, and dialysis occurred in 42% of participants."
    )

    record = EvidenceExtractor(max_spans_per_paper=1).extract(
        _candidate(abstract),
        _plan("renal survival predictors outcomes", concepts=["renal survival", "predictors", "outcomes"]),
    )

    assert record.supporting_text_spans == [
        "RESULTS: Median renal survival was 24 months, and dialysis occurred in 42% of participants."
    ]


def test_unseen_predictor_query_prefers_clinical_result_and_caps_selection():
    abstract = (
        "BACKGROUND: Cardiac involvement is common in the disease. "
        "RESULTS: Older age and elevated troponin were independent prognostic factors for cardiac mortality (hazard ratio 2.1). "
        "RESULTS: The laboratory assay used 5 mL of blood. "
        "CONCLUSIONS: These prognostic factors may help identify patients at risk."
    )

    record = EvidenceExtractor(max_spans_per_paper=2).extract(
        _candidate(abstract),
        _plan("cardiac mortality prognostic factors", concepts=["cardiac mortality", "prognostic factors"]),
    )

    assert len(record.supporting_text_spans) == 2
    assert record.supporting_text_spans[0].startswith("RESULTS: Older age")
    assert record.supporting_text_spans[1].startswith("CONCLUSIONS: These prognostic factors")
    assert "5 mL" not in record.key_findings


def test_score_is_zero_for_unrelated_numeric_sentence_and_positive_for_finding():
    terms = ["renal", "survival", "predictors"]
    assert score_finding_sentence("RESULTS: The assay used 5 mL of blood.", terms) == 0.0
    assert score_finding_sentence("RESULTS: Renal survival was 24 months.", terms) > 0
