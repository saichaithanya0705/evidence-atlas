import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.core.config import get_settings
from backend.app.storage.accounts import AccountStore
from backend.app.storage.audits import AuditStore
from backend.app.storage.database import initialize_db
from backend.app.auth.security import hash_password
from backend.app.models.request_response import ResearchResponse, RetrievalCandidate


@pytest.fixture
def audit_client(tmp_path, monkeypatch):
    path = tmp_path / "audit.sqlite3"
    monkeypatch.setenv("APP_DATABASE_PATH", str(path))
    get_settings.cache_clear()
    initialize_db(path)
    accounts = AccountStore(path)
    accounts.create("administrator", "Administrator", "admin", hash_password("admin-password-123"), None, False)
    accounts.create("alice", "Alice", "user", hash_password("alice-password-123"), None, False)

    class FakeService:
        def research(self, query, filters, max_loops, request_id, event_sink=None):
            if event_sink:
                event_sink("query_analysis", {"route": "SIMPLE"})
                event_sink("retrieve", {"pmids": ["12345"]})
            if "fail" in query:
                raise RuntimeError("provider secret must not appear")
            return ResearchResponse(
                request_id=request_id, query=query, canonical_query=query, route="SIMPLE",
                synthesis="Example synthesis [PMID: 12345].", evidence_table=[], cited_pmids=["12345"],
                citations_valid=True, citation_precision=1.0, consensus_level="consensus",
                evidence_gaps=[], audit_trace_url=f"/trace/{request_id}",
                retrieved_papers=[RetrievalCandidate(pmid="12345", title="Example", abstract="Abstract")],
            )

        def get_trace(self, request_id):
            return {"request_id": request_id, "stages": [{"stage": "retrieve"}], "timings_ms": {"total": 1}}

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeService())
    with TestClient(main.app, base_url="http://testserver", raise_server_exceptions=False) as client:
        yield client, path
    get_settings.cache_clear()


def login(client, name, password):
    assert client.post("/auth/login", json={"username": name, "password": password}, headers={"Origin": "http://testserver"}).status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}


def test_user_controls_rejected_and_trace_restricted(audit_client):
    client, path = audit_client
    headers = login(client, "alice", "alice-password-123")
    rejected = client.post("/research", json={"query": "kidney", "year_min": 2020}, headers=headers)
    assert rejected.status_code == 403
    allowed = client.post("/research", json={"query": "kidney"}, headers=headers)
    assert allowed.status_code == 200
    body = allowed.json()
    assert "route" not in body
    assert "evidence_table" in body and body["evidence_table"] == []
    assert client.get("/admin/audits").status_code == 403
    assert client.get(f"/trace/{body['request_id']}").status_code == 403
    runs = AuditStore(path).list_runs()["items"]
    assert len(runs) == 2
    assert {run["status"] for run in runs} == {"rejected", "completed"}


def test_admin_can_read_persisted_trace_after_failure(audit_client):
    client, path = audit_client
    headers = login(client, "administrator", "admin-password-123")
    assert client.post("/research", json={"query": "fail safely", "max_loops": 2}, headers=headers).status_code == 503
    listing = client.get("/admin/audits").json()
    assert listing["total"] == 1
    run_id = listing["items"][0]["id"]
    assert listing["items"][0]["status"] == "failed"
    detail = client.get(f"/admin/audits/{run_id}").json()
    assert len(detail["events"]) >= 2
    assert "secret" not in detail["error"]
    assert AuditStore(path).detail(run_id)["events"][0]["stage"] == "query_analysis"


def test_oversized_authenticated_query_is_rejected_and_audited(audit_client):
    client, path = audit_client
    headers = login(client, "alice", "alice-password-123")
    response = client.post("/research", json={"query": "x" * 20001}, headers=headers)
    assert response.status_code == 413
    runs = AuditStore(path).list_runs()
    assert runs["total"] == 1
    detail = AuditStore(path).detail(runs["items"][0]["id"])
    assert detail["status"] == "rejected"
    assert detail["username"] == "alice"
    assert len(detail["query"]) <= 4000


def test_unknown_request_fields_do_not_store_secret_values(audit_client):
    client, path = audit_client
    headers = login(client, "alice", "alice-password-123")
    response = client.post("/research", json={"query": "kidney", "password": "private-password-should-not-persist", "api_key": "private-api-key-should-not-persist"}, headers=headers)
    assert response.status_code == 403
    runs = AuditStore(path).list_runs()
    detail = AuditStore(path).detail(runs["items"][0]["id"])
    assert "private-password-should-not-persist" not in str(detail)
    assert "private-api-key-should-not-persist" not in str(detail)
