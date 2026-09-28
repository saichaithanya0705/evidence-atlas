"""Regression tests for the administrator-only diagnostics boundary."""

from backend.app import main
from backend.app.models.request_response import ResearchResponse, RetrievalCandidate


def _ordinary_headers():
    # The shared test client has an admin default header for legacy contract
    # tests; an empty value explicitly exercises the ordinary-user path.
    return {"X-Admin-Key": ""}


def test_query_analysis_requires_admin_key(real_app_client):
    response = real_app_client.post(
        "/analyze-query",
        json={"query": "metformin and cardiovascular risk"},
        headers=_ordinary_headers(),
    )
    assert response.status_code == 403


def test_admin_verification_rejects_wrong_key(real_app_client):
    response = real_app_client.post(
        "/admin/verify",
        headers={"X-Admin-Key": "definitely-not-the-configured-key"},
    )
    assert response.status_code == 403


def test_trace_requires_admin_key(real_app_client):
    response = real_app_client.get("/trace/unknown", headers=_ordinary_headers())
    assert response.status_code == 403


def test_metrics_require_admin_key(real_app_client):
    response = real_app_client.get("/metrics", headers=_ordinary_headers())
    assert response.status_code == 403


def test_public_health_is_coarse(real_app_client):
    response = real_app_client.get("/health", headers=_ordinary_headers())
    assert response.status_code == 200
    assert set(response.json()) == {"status", "service", "version"}


def test_public_search_contains_no_query_analysis(real_app_client):
    response = real_app_client.post(
        "/search",
        json={"query": "diabetes", "top_k": 0},
        headers=_ordinary_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"query", "total_results", "candidates"}


def test_public_research_excludes_trace_and_evidence_spans(real_app_client, monkeypatch):
    candidate = RetrievalCandidate(
        pmid="12345",
        title="Example study",
        abstract="An abstract.",
        channel_scores={"dense": 0.9},
        channel_ranks={"dense": 1},
        rrf_score=0.5,
        reranker_score=0.8,
    )
    payload = ResearchResponse(
        request_id="req_boundary",
        query="diabetes",
        canonical_query="diabetes mellitus",
        route="SIMPLE",
        synthesis="A grounded result [PMID: 12345].",
        evidence_table=[],
        cited_pmids=["12345"],
        citations_valid=True,
        citation_precision=1.0,
        consensus_level="consensus",
        evidence_gaps=[],
        audit_trace_url="/trace/req_boundary",
        retrieved_papers=[candidate],
    )

    class FakeResearchService:
        def research(self, *args, **kwargs):
            return payload

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeResearchService())
    response = real_app_client.post(
        "/research",
        json={"query": "diabetes"},
        headers=_ordinary_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert "request_id" not in body
    assert "audit_trace_url" not in body
    assert "canonical_query" not in body
    assert "route" not in body
    assert "citation_precision" not in body
    assert "consensus_level" not in body
    assert "evidence_gaps" not in body
    assert body["evidence_table"] == []
    assert "channel_scores" not in body["retrieved_papers"][0]
    assert "filter_satisfied" not in body["retrieved_papers"][0]
