from backend.app.storage.audits import _safe_trace
from backend.app.evidence.extraction import score_finding_sentence
from pipelines.preprocess import infer_study_type


def test_admin_trace_retains_bounded_execution_contract_not_provider_content():
    trace = _safe_trace({
        "request_id": "run-1", "original_query": "vaccine effectiveness",
        "query_plan": {"canonical_query": "mRNA vaccine effectiveness", "route": "MODERATE",
                       "subqueries": ["mRNA vaccines"], "router_reasoning": "SECRET", "pico": {"population": "SECRET"}},
        "retrieval_iterations": [{"iteration": 0, "query": "mRNA vaccines",
            "candidate_pmids": ["123", "bad"], "accumulated_pmids": ["123"],
            "retrieval": {"channels": {"bm25": {"returned": 5, "accepted": 2, "error": "SECRET"}, "bm25_query_2": {"returned": 3, "accepted": 1}}},
            "grade": {"grade": "PARTIAL", "rationale": "SECRET"}}],
        "final_evidence_pmids": ["123"], "stop_reason": "evidence_sufficient",
        "synthesis_metadata": {"mode": "deterministic_spans", "fallback_reason": "SECRET provider exception"},
        "citation_audit": {"valid": True}, "provider_output": "SECRET",
    })
    assert trace["query_plan"]["canonical_query"] == "mRNA vaccine effectiveness"
    assert trace["retrieval_iterations"][0]["candidate_pmids"] == ["123"]
    assert trace["retrieval_iterations"][0]["grade"]["grade"] == "PARTIAL"
    assert trace["synthesis_metadata"]["mode"] == "deterministic_spans"
    assert trace["retrieval_iterations"][0]["retrieval"]["channels"]["bm25_query_2"]["accepted"] == 1
    assert "SECRET" not in str(trace)


def test_effectiveness_result_beats_vaccine_background():
    terms = ["recent", "research", "effectiveness", "mrna", "vaccines", "respiratory", "infections"]
    result = "RECENT FINDINGS: The COVID-19 mRNA vaccines demonstrated effectiveness in preventing severe COVID-19 and death."
    background = "Since 2019, research has focused on mRNA vaccines for infectious disease prevention and respiratory infections."
    assert score_finding_sentence(result, terms) > score_finding_sentence(background, terms)


def test_clinical_question_is_not_a_reported_finding():
    assert score_finding_sentence("CLINICAL QUESTION: What are the benefits of medications for diabetes and cardiovascular complications?", ["diabetes", "cardiovascular", "complications"]) == 0


def test_publication_type_review_overrides_trials_mentioned_in_abstract():
    assert infer_study_type(["Review", "Journal Article"], "Respiratory vaccines", "Phase 3 clinical trials showed efficacy.") == "Review"


def test_guideline_is_not_relabelled_as_systematic_review():
    assert infer_study_type(["Practice Guideline", "Journal Article"], "Clinical practice guideline", "Recommendations informed by a systematic review.") == "Other"
