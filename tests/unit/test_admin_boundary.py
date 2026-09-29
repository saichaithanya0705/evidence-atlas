"""Regression checks for identity-based diagnostic access."""

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.auth.security import hash_password
from backend.app.core.config import get_settings
from backend.app.models.request_response import EvidenceRecord, ResearchResponse, RetrievalCandidate
from backend.app.storage.accounts import AccountStore
from backend.app.storage.database import initialize_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "boundary.sqlite3"
    monkeypatch.setenv("APP_DATABASE_PATH", str(path))
    get_settings.cache_clear()
    initialize_db(path)
    store = AccountStore(path)
    store.create("admin", "Administrator", "admin", hash_password("admin-password-123"), None, False)
    store.create("reader", "Reader", "user", hash_password("reader-password-123"), None, False)
    with TestClient(main.app, base_url="http://testserver") as value:
        yield value
    get_settings.cache_clear()


def sign_in(client, username, password):
    result = client.post("/auth/login", json={"username": username, "password": password}, headers={"Origin": "http://testserver"})
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}


@pytest.mark.parametrize("method,path", [("post", "/analyze-query"), ("get", "/trace/unknown"), ("get", "/metrics"), ("get", "/admin/audits")])
def test_shared_key_cannot_bypass_sign_in(client, method, path):
    response = getattr(client, method)(path, headers={"X-Admin-Key": "legacy-key"})
    assert response.status_code == 401


def test_ordinary_account_cannot_read_diagnostics(client):
    headers = sign_in(client, "reader", "reader-password-123")
    assert client.post("/analyze-query", json={"query": "diabetes"}, headers=headers).status_code == 403
    assert client.get("/trace/unknown").status_code == 403
    assert client.get("/metrics").status_code == 403
    assert client.get("/admin/audits").status_code == 403


def test_public_health_is_coarse(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "service", "version"}


def test_reader_search_contains_no_query_analysis(client, monkeypatch):
    from types import SimpleNamespace

    class FakeSearchService:
        def search(self, *args):
            return SimpleNamespace(canonical_query="diabetes", route="SIMPLE"), [], {"secret": "admin-only"}

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeSearchService())
    headers = sign_in(client, "reader", "reader-password-123")
    response = client.post("/search", json={"query": "diabetes"}, headers=headers)
    assert response.status_code == 200
    assert set(response.json()) == {"query", "total_results", "candidates"}


def test_reader_research_excludes_diagnostics(client, monkeypatch):
    candidate = RetrievalCandidate(pmid="12345", title="Example study", abstract="An abstract.", channel_scores={"dense": .9}, channel_ranks={"dense": 1}, rrf_score=.5, reranker_score=.8)

    class FakeResearchService:
        def research(self, query, filters, max_loops, request_id, event_sink=None):
            return ResearchResponse(request_id=request_id, query=query, canonical_query="diabetes mellitus", route="SIMPLE", synthesis="A grounded result [PMID: 12345].", evidence_table=[EvidenceRecord(pmid="12345", title="Example study", key_findings="Grounded finding", supporting_text_spans=["Exact abstract span"])], cited_pmids=["12345"], citations_valid=True, citation_precision=1.0, consensus_level="consensus", evidence_gaps=["  Missing   safety evidence  "], audit_trace_url=f"/trace/{request_id}", retrieved_papers=[candidate])

        def get_trace(self, request_id):
            return {"request_id": request_id, "stages": []}

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeResearchService())
    headers = sign_in(client, "reader", "reader-password-123")
    response = client.post("/research", json={"query": "diabetes"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    for field in ("audit_trace_url", "canonical_query", "route", "citation_precision", "consensus_level"):
        assert field not in body
    assert body["evidence_gaps"] == ["Missing safety evidence"]
    assert body["evidence_table"][0]["supporting_text_spans"] == ["Exact abstract span"]
    assert "channel_scores" not in body["retrieved_papers"][0]


def test_reader_cannot_read_linked_admin_trace_or_internal_metadata(client, monkeypatch, tmp_path):
    from backend.app.storage.audits import AuditStore

    path = tmp_path / "boundary.sqlite3"
    account = AccountStore(path).by_username("reader")
    audits = AuditStore(path)
    audits.start("private-trace", account, "conversation_turn", "question", {}, {},
                 conversation_id="conversation-private", turn_id="turn-private")
    audits.event("private-trace", "agent_decision", {"action": "RESEARCH"})
    audits.finish("private-trace", "completed", {"answer_status": "SUPPORTED"})
    headers = sign_in(client, "reader", "reader-password-123")

    assert client.get("/admin/audits", headers=headers).status_code == 403
    assert client.get("/admin/audits/private-trace", headers=headers).status_code == 403
