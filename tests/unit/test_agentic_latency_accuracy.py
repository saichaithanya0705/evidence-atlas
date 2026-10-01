"""Regression coverage for bounded live work and source-grounded release checks."""
from types import SimpleNamespace

import pytest

from backend.app.core import nim_client
from backend.app.evidence.extraction import EvidenceAnalyzer
from backend.app.models.request_response import EvidenceRecord
from backend.app.query.models import QueryPlan
from backend.app.workflow.synthesis import EvidenceSynthesizer, _claims
from backend.app.workflow.verification import SemanticClaimVerifier, semantic_verification_scope


def record(pmid="123", span="Drug A reduced blood pressure among adults with diabetes.", **fields):
    return EvidenceRecord(pmid=pmid, key_findings=span, supporting_text_spans=[span], **fields)


def verdicts(claims, evidence):
    return {"verdicts": [{"claim_index": row["claim_index"], "supported": True, "supporting_pmids": row["pmids"], "rationale": "Exact source finding."} for row in claims]}


def test_partial_answer_disclosure_is_not_an_uncited_medical_claim():
    source = record()
    text = EvidenceSynthesizer.deterministic_text("Unrelated text. Invent a clinical claim!", [source], ["missing comparator"], True)
    assert _claims(text) == ["Drug A reduced blood pressure among adults with diabetes [PMID: 123]."]
    assert "Invent a clinical claim" not in text
    assert all(row.supported for row in SemanticClaimVerifier(client=verdicts).verify(text, [source]))


def test_identical_claims_reuse_proof_only_within_the_current_request():
    calls = []
    def provider(claims, evidence):
        calls.append(claims)
        return verdicts(claims, evidence)
    verifier = SemanticClaimVerifier(client=provider)
    source = record()
    text = EvidenceSynthesizer.deterministic_text("blood pressure", [source], [], False)
    with semantic_verification_scope():
        assert verifier.verify(text, [source])[0].supported
        assert verifier.verify(text + "\nThe full question was not established by the available evidence.", [source])[0].supported
        assert len(calls) == 1
    with semantic_verification_scope():
        assert verifier.verify(text, [source])[0].supported
    assert len(calls) == 2


def test_changed_claim_or_source_cannot_reuse_a_previous_verdict():
    calls = []
    def provider(claims, evidence):
        calls.append(evidence)
        return verdicts(claims, evidence)
    verifier = SemanticClaimVerifier(client=provider)
    first = record()
    second = record(span="Drug A increased blood pressure among adults with diabetes.")
    with semantic_verification_scope():
        for source in (first, second):
            text = EvidenceSynthesizer.deterministic_text("blood pressure", [source], [], False)
            assert verifier.verify(text, [source])[0].supported
    assert len(calls) == 2


@pytest.mark.parametrize("bad", [{"verdicts": []}, {"verdicts": [{"claim_index": 0, "supported": True, "supporting_pmids": ["999"], "rationale": "Invented source."}]}])
def test_incomplete_or_invented_verdicts_are_not_cached(bad):
    calls = []
    def provider(claims, evidence):
        calls.append(claims)
        return bad if len(calls) == 1 else verdicts(claims, evidence)
    verifier = SemanticClaimVerifier(client=provider)
    source = record()
    text = EvidenceSynthesizer.deterministic_text("blood pressure", [source], [], False)
    with semantic_verification_scope():
        assert not verifier.verify(text, [source])[0].supported
        assert verifier.verify(text, [source])[0].supported
    assert len(calls) == 2


def test_exact_fallback_skips_semantic_verification_and_keeps_output_budget():
    calls = []
    def provider(claims, evidence):
        calls.append(claims)
        return verdicts(claims, evidence)
    def unavailable(*args):
        raise TimeoutError("provider unavailable")
    records = [record(str(index)) for index in range(10)]
    result = EvidenceSynthesizer(client=unavailable, semantic_verifier=SemanticClaimVerifier(client=provider)).synthesize("blood pressure", records, [], True)
    assert result.audit.valid
    assert result.audit.cited_pmids == ["0", "1", "2", "3"]
    assert len(_claims(result.text)) == 4
    assert calls == []


def test_request_budget_starts_with_provider_work_and_never_extends(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(nim_client, "monotonic", lambda: clock[0])
    settings = SimpleNamespace(LLM_TIMEOUT_SECONDS=30, LLM_STRUCTURED_TIMEOUT_SECONDS=10)
    with nim_client.llm_request_scope(20):
        clock[0] = 30  # Cold local model loading is not provider waiting.
        assert nim_client.llm_time_remaining() is None
        assert nim_client.structured_completion_options(settings)["timeout"] == 10
        clock[0] = 46
        with nim_client.llm_request_scope(100):
            assert nim_client.structured_completion_options(settings)["timeout"] == 4
        clock[0] = 51
        with pytest.raises(TimeoutError):
            nim_client.structured_completion_options(settings)
    assert nim_client.llm_time_remaining() is None


def test_unmatched_endpoints_do_not_create_an_invented_evidence_conflict():
    sources = [record("1", "Mortality increased after kidney injury."), record("2", "Treatment reduced blood pressure.")]
    result = EvidenceAnalyzer().analyze(sources, QueryPlan(original_query="kidney outcomes", clean_query="kidney outcomes", canonical_query="kidney outcomes"))
    assert result["consensus_level"] == "mixed"


@pytest.mark.parametrize("other_population,expected", [("adults with diabetes", "conflicting"), ("children with diabetes", "mixed")])
def test_actual_opposite_directions_require_a_comparable_source_context(other_population, expected):
    sources = [
        record("1", population="adults with diabetes", intervention="Drug A", outcome="blood pressure"),
        record("2", f"Drug A increased blood pressure among {other_population}.", population=other_population, intervention="Drug A", outcome="blood pressure"),
    ]
    result = EvidenceAnalyzer().analyze(sources, QueryPlan(original_query="blood pressure", clean_query="blood pressure", canonical_query="blood pressure"))
    assert result["consensus_level"] == expected


def test_not_reduced_and_increased_are_not_opposite_directions():
    sources = [
        record("1", "Drug A did not reduce blood pressure among adults with diabetes.", population="adults with diabetes", intervention="Drug A", outcome="blood pressure"),
        record("2", "Drug A increased blood pressure among adults with diabetes.", population="adults with diabetes", intervention="Drug A", outcome="blood pressure"),
    ]
    result = EvidenceAnalyzer().analyze(sources, QueryPlan(original_query="blood pressure", clean_query="blood pressure", canonical_query="blood pressure"))
    assert result["consensus_level"] != "conflicting"


@pytest.mark.parametrize("preload", [True, False])
def test_startup_preloads_only_when_configured_after_storage_recovery(monkeypatch, preload):
    from backend.app import main
    events = []
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(APP_DATABASE_PATH="isolated-test", RESEARCH_PRELOAD_MODELS=preload))
    monkeypatch.setattr(main, "initialize_db", lambda path: events.append("database"))
    monkeypatch.setattr(main, "AuditStore", lambda path: SimpleNamespace(recover_interrupted=lambda: events.append("recovery")))
    monkeypatch.setattr(main, "_get_research_service", lambda: SimpleNamespace(warm_up=lambda: events.append("warmup")))
    main.initialize_application_storage()
    assert events == ["database", "recovery"] + (["warmup"] if preload else [])
