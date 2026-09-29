import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.core.config import get_settings
from backend.app.storage.accounts import AccountStore
from backend.app.storage.audits import AuditStore
from backend.app.storage.database import connect_db, initialize_db
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


def test_audit_run_links_conversation_and_turn_without_breaking_legacy_callers(tmp_path):
    path = tmp_path / "audit-links.sqlite3"
    initialize_db(path)
    account = AccountStore(path).create("alice", "Alice", "user", "hash", None, False)
    audits = AuditStore(path)
    audits.start("linked-run", account, "research", "question", {}, {}, conversation_id="conversation-1", turn_id="turn-1")
    audits.start("legacy-run", account, "research", "old question", {}, {})

    assert audits.detail("linked-run")["conversation_id"] == "conversation-1"
    assert audits.detail("linked-run")["turn_id"] == "turn-1"
    assert audits.detail("legacy-run")["conversation_id"] is None
    assert audits.detail("legacy-run")["turn_id"] is None


def test_admin_audit_projects_linked_trace_summaries_and_allowlisted_events(audit_client):
    client, path = audit_client
    headers = login(client, "administrator", "admin-password-123")
    account = AccountStore(path).by_username("alice")
    audits = AuditStore(path)
    audits.start("linked-trace", account, "conversation_turn", "safe question", {}, {},
                 conversation_id="conversation-1", turn_id="turn-1")
    audits.event("linked-trace", "agent_decision", {
        "action": "RESEARCH", "complexity_hint": "MODERATE",
        "decision_summary": "must not be exposed", "prompt": "hidden prompt",
    })
    audits.event("linked-trace", "query_analysis", {
        "route": "MODERATE", "rule_route": "SIMPLE", "agent_complexity_hint": "MODERATE",
        "router_reasoning": "hidden reasoning", "canonical_query": "safe normalized question",
    })
    audits.event("linked-trace", "correct", {"status": "completed", "duration_ms": 12.5, "query": "private correction"})
    audits.event("linked-trace", "claim_verified", {"claim_count": 2, "supported_count": 2, "raw_output": "secret"})
    audits.event("linked-trace", "answer_released", {"status": "SUPPORTED", "gap_count": 1})
    audits.event("linked-trace", "correction_stopped", {"reason": {"prompt": "nested event secret"}, "iteration": 1})
    audits.finish("linked-trace", "completed", {
        "answer_status": "SUPPORTED", "evidence_gaps": ["  missing   pediatric evidence  "],
        "provider_output": "private provider text", "prompt": "hidden system prompt",
        "evidence_table": [
            {"pmid": "12345", "title": True, "year": "2024", "population": False,
             "key_findings": "Valid finding", "supporting_text_spans": ["Valid source span"]},
            {"pmid": "23456", "title": "Valid title", "year": 2020, "population": "Adults",
             "key_findings": "Valid finding", "supporting_text_spans": ["Valid source span"]},
        ],
        "retrieved_papers": [
            {"pmid": 12345, "title": False, "year": "2024", "abstract": "Valid abstract",
             "journal": 7, "authors": ["Valid Author", {"prompt": "nested author secret"}], "study_type": "Review"},
            {"pmid": "23456", "title": "Valid title", "year": 2020, "abstract": "Valid abstract",
             "journal": "Valid Journal", "authors": ["Valid Author"], "study_type": "Review"},
        ],
    }, {
        "query_plan": {"pico": {"population": "sensitive"}, "router_reasoning": "hidden"},
        "citation_audit": {"valid": True, "cited_pmids": ["12345", {"provider_output": "nested citation secret"}]},
    })
    with connect_db(path) as db:
        db.execute("UPDATE query_runs SET requested_controls=?,applied_controls=? WHERE id=?", (
            '{"year_min":{"prompt":"nested control secret"},"study_types":["Review",{"provider_output":"nested control secret"}]}',
            '{"max_loops":{"prompt":"nested control secret"}}', "linked-trace",
        ))
    audits.start("legacy-audit", account, "research", "old question", {}, {})
    audits.finish("legacy-audit", "completed", {"synthesis": "legacy result"})

    listing = client.get("/admin/audits", headers=headers).json()
    item = next(row for row in listing["items"] if row["id"] == "linked-trace")
    assert (item["conversation_id"], item["turn_id"], item["agent_action"]) == ("conversation-1", "turn-1", "RESEARCH")
    assert item["agent_complexity_hint"] == "MODERATE"
    assert (item["rule_route"], item["final_route"], item["answer_status"]) == ("SIMPLE", "MODERATE", "SUPPORTED")
    assert item["correction_count"] == 1

    detail = client.get("/admin/audits/linked-trace", headers=headers).json()
    assert detail["evidence_gaps"] == ["missing pediatric evidence"]
    assert detail["stage_durations_ms"] == {"correct": 12.5}
    assert detail["requested_controls"] == {"study_types": ["Review"]}
    assert detail["applied_controls"] == {}
    assert detail["trace"]["citation_audit"]["cited_pmids"] == ["12345"]
    assert detail["response"]["evidence_table"] == [
        {"pmid": "12345", "key_findings": "Valid finding", "supporting_text_spans": ["Valid source span"]},
        {"pmid": "23456", "title": "Valid title", "year": 2020, "population": "Adults",
         "key_findings": "Valid finding", "supporting_text_spans": ["Valid source span"]},
    ]
    assert detail["response"]["retrieved_papers"] == [
        {"abstract": "Valid abstract", "authors": ["Valid Author"], "study_type": "Review"},
        {"pmid": "23456", "title": "Valid title", "year": 2020, "abstract": "Valid abstract",
         "journal": "Valid Journal", "authors": ["Valid Author"], "study_type": "Review"},
    ]
    assert "reason" not in next(event["payload"] for event in detail["events"] if event["stage"] == "correction_stopped")
    assert [event["stage"] for event in detail["events"]] == [
        "agent_decision", "query_analysis", "correct", "claim_verified", "answer_released", "correction_stopped",
    ]
    assert "pico" not in str(detail)
    for unsafe in ("prompt", "provider_output", "raw_output", "router_reasoning", "decision_summary", "nested event secret", "nested citation secret", "nested control secret", "nested author secret"):
        assert unsafe not in str(detail)
    legacy_trace = client.get("/trace/linked-trace", headers=headers).json()
    assert "pico" not in str(legacy_trace)
    assert "router_reasoning" not in str(legacy_trace)

    legacy = audits.list_runs()["items"]
    assert any(row["id"] != "linked-trace" and row["conversation_id"] is None for row in legacy)
