import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.auth.security import hash_password
from backend.app.core.config import get_settings
from backend.app.storage.accounts import AccountStore
from backend.app.storage.conversations import ConversationStore
from backend.app.storage.database import connect_db, initialize_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "routes.sqlite3"
    monkeypatch.setenv("APP_DATABASE_PATH", str(path))
    get_settings.cache_clear()
    initialize_db(path)
    AccountStore(path).create("reader", "Reader", "user", hash_password("reader-password-123"), None, False)
    AccountStore(path).create("other", "Other", "user", hash_password("other-password-123"), None, False)
    AccountStore(path).create("administrator", "Administrator", "admin", hash_password("admin-password-123"), None, False)
    with TestClient(main.app, base_url="http://testserver") as value:
        yield value
    get_settings.cache_clear()


def _headers(client):
    response = client.post("/auth/login", json={"username": "reader", "password": "reader-password-123"}, headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}


def test_conversation_routes_are_registered_and_require_session(client):
    for method, path in (("post", "/conversations"), ("get", "/conversations"), ("get", "/conversations/missing"), ("post", "/conversations/missing/turns")):
        response = client.post(path, json={}) if method == "post" else client.get(path)
        assert response.status_code == 401


def test_conversation_reads_reject_expired_and_deactivated_sessions(client):
    _headers(client)
    path = get_settings().APP_DATABASE_PATH
    with connect_db(path) as db:
        db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    assert client.get("/conversations").status_code == 401

    _headers(client)
    account = AccountStore(path).by_username("reader")
    AccountStore(path).update(account["id"], account["id"], active=False)
    assert client.get("/conversations").status_code == 401


def test_create_list_detail_and_owned_turn_routes(client):
    headers = _headers(client)
    created = client.post("/conversations", json={}, headers=headers)
    assert created.status_code == 201
    conversation_id = created.json()["conversation_id"]
    assert client.get("/conversations?limit=10&offset=0", headers=headers).json()["total"] == 1
    assert client.get(f"/conversations/{conversation_id}", headers=headers).status_code == 200
    assert client.get("/conversations/not-owned", headers=headers).status_code == 404
    assert client.get("/conversations?limit=101", headers=headers).status_code == 422


def test_restored_conversation_detail_exposes_audit_request_id_only_to_admins(client):
    path = get_settings().APP_DATABASE_PATH
    store = ConversationStore(path)

    def completed_conversation(account):
        conversation = store.create(account["id"])
        turn = store.begin_turn(conversation["id"], account["id"], "test question")
        store.complete_turn(
            turn["id"], agent_action="RESEARCH", standalone_query="test question",
            complexity_hint="SIMPLE", final_route="SIMPLE", answer_status="SUPPORTED",
            assistant_message="Supported [PMID: 12345]", audit_run_id="trace-run-123",
            public_response={"request_id": "trace-run-123", "cited_pmids": ["12345"], "evidence_table": [], "retrieved_papers": [], "evidence_gaps": []},
        )
        return conversation["id"]

    reader_headers = _headers(client)
    reader = AccountStore(path).by_username("reader")
    reader_conversation = completed_conversation(reader)
    public_turn = client.get(f"/conversations/{reader_conversation}", headers=reader_headers).json()["turns"][0]
    assert "request_id" not in public_turn
    assert "request_id" not in public_turn["result"]

    login = client.post("/auth/login", json={"username": "administrator", "password": "admin-password-123"}, headers={"Origin": "http://testserver"})
    assert login.status_code == 200
    admin_headers = {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}
    administrator = AccountStore(path).by_username("administrator")
    admin_conversation = completed_conversation(administrator)
    admin_turn = client.get(f"/conversations/{admin_conversation}", headers=admin_headers).json()["turns"][0]
    assert admin_turn["request_id"] == "trace-run-123"
    assert "request_id" not in admin_turn["result"]


def test_turn_post_rejects_missing_csrf_and_advanced_user_controls(client):
    headers = _headers(client)
    conversation_id = client.post("/conversations", json={}, headers=headers).json()["conversation_id"]
    no_csrf = {"Origin": "http://testserver"}
    assert client.post("/conversations", json={}, headers=no_csrf).status_code == 403
    assert client.post(f"/conversations/{conversation_id}/turns", json={"message": "diabetes"}, headers=no_csrf).status_code == 403
    assert client.post(f"/conversations/{conversation_id}/turns", json={"message": "diabetes", "max_loops": 9}, headers=headers).status_code == 422
    assert client.post(
        f"/conversations/{conversation_id}/turns",
        json={"message": "diabetes", "year_min": 2020}, headers=headers,
    ).status_code == 403


def test_foreign_conversation_is_hidden_as_not_found(client):
    other_login = client.post("/auth/login", json={"username": "other", "password": "other-password-123"}, headers={"Origin": "http://testserver"})
    assert other_login.status_code == 200
    other_headers = {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}
    foreign_id = client.post("/conversations", json={}, headers=other_headers).json()["conversation_id"]
    reader_headers = _headers(client)

    assert client.get(f"/conversations/{foreign_id}", headers=reader_headers).status_code == 404
    assert client.post(f"/conversations/{foreign_id}/turns", json={"message": "diabetes"}, headers=reader_headers).status_code == 404


def test_turn_route_returns_the_completed_public_response(client):
    from backend.app.conversation.models import ConversationAgentDecision
    from backend.app.conversation.routes import get_conversation_service
    from backend.app.conversation.service import ConversationService
    from backend.app.models.request_response import AgentAction
    from backend.app.storage.audits import AuditStore

    headers = _headers(client)
    conversation_id = client.post("/conversations", json={}, headers=headers).json()["conversation_id"]
    path = get_settings().APP_DATABASE_PATH
    class FakeAgent:
        def plan_turn(self, message, history):
            return ConversationAgentDecision(
                action=AgentAction.CLARIFY, decision_summary="A specific outcome is needed.",
                message="Please name the outcome.",
            )

    class NoResearch:
        pass

    service = ConversationService(
        store=ConversationStore(path), audit=AuditStore(path), agent=FakeAgent(), research=NoResearch(),
    )
    client.app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        response = client.post(
            f"/conversations/{conversation_id}/turns", json={"message": "What about it?"}, headers=headers,
        )
    finally:
        client.app.dependency_overrides.pop(get_conversation_service, None)

    assert response.status_code == 200
    assert response.json()["action"] == "CLARIFY"
    assert response.json()["answer_status"] == "INSUFFICIENT"
    assert response.json()["assistant_message"] == "Please name the outcome."
    assert "request_id" not in response.json()
    restored = client.get(f"/conversations/{conversation_id}", headers=headers).json()["turns"][0]
    assert restored["result"]["cited_pmids"] == []
    assert "raw_prompt" not in restored["result"]


def test_admin_turn_post_includes_audit_request_id(client):
    from backend.app.conversation.models import ConversationAgentDecision
    from backend.app.conversation.routes import get_conversation_service
    from backend.app.conversation.service import ConversationService
    from backend.app.models.request_response import AgentAction
    from backend.app.storage.audits import AuditStore

    login = client.post("/auth/login", json={"username": "administrator", "password": "admin-password-123"}, headers={"Origin": "http://testserver"})
    assert login.status_code == 200
    headers = {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}
    conversation_id = client.post("/conversations", json={}, headers=headers).json()["conversation_id"]
    path = get_settings().APP_DATABASE_PATH

    class FakeAgent:
        def plan_turn(self, message, history):
            return ConversationAgentDecision(
                action=AgentAction.CLARIFY, decision_summary="A specific outcome is needed.",
                message="Please name the outcome.",
            )

    class NoResearch:
        pass

    service = ConversationService(store=ConversationStore(path), audit=AuditStore(path), agent=FakeAgent(), research=NoResearch())
    client.app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        response = client.post(f"/conversations/{conversation_id}/turns", json={"message": "What about it?"}, headers=headers)
    finally:
        client.app.dependency_overrides.pop(get_conversation_service, None)

    assert response.status_code == 200
    assert response.json()["request_id"]


def test_conversation_detail_openapi_documents_role_gated_admin_projection(client):
    operation = client.get("/openapi.json").json()["paths"]["/conversations/{conversation_id}"]["get"]
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert "anyOf" in response_schema
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    branch_names = {branch["$ref"].rsplit("/", 1)[-1] for branch in response_schema["anyOf"]}
    assert branch_names == {"ConversationDetailResponse", "AdminConversationDetailResponse"}
    assert "request_id" not in schemas["ConversationTurnRecord"]["properties"]
    assert "request_id" in schemas["AdminConversationTurnRecord"]["properties"]
    post_operation = client.get("/openapi.json").json()["paths"]["/conversations/{conversation_id}/turns"]["post"]
    post_schema = post_operation["responses"]["200"]["content"]["application/json"]["schema"]
    post_names = {branch["$ref"].rsplit("/", 1)[-1] for branch in post_schema["anyOf"]}
    assert post_names == {"ConversationTurnResponse", "AdminConversationTurnResponse"}
    assert "request_id" not in schemas["ConversationTurnResponse"]["properties"]
    assert "request_id" in schemas["AdminConversationTurnResponse"]["properties"]


def test_failed_turn_remains_failed_after_api_reload(client):
    from backend.app.conversation.routes import get_conversation_service
    from backend.app.conversation.service import ConversationService
    from backend.app.storage.audits import AuditStore

    headers = _headers(client)
    conversation_id = client.post("/conversations", json={}, headers=headers).json()["conversation_id"]
    path = get_settings().APP_DATABASE_PATH

    class BrokenAgent:
        def plan_turn(self, message, history):
            raise RuntimeError("private provider error")

    class NoResearch:
        pass

    service = ConversationService(
        store=ConversationStore(path), audit=AuditStore(path), agent=BrokenAgent(), research=NoResearch(),
    )
    client.app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        failed = client.post(
            f"/conversations/{conversation_id}/turns", json={"message": "A technical failure"}, headers=headers,
        )
    finally:
        client.app.dependency_overrides.pop(get_conversation_service, None)

    assert failed.status_code == 503
    reloaded = client.get(f"/conversations/{conversation_id}", headers=headers).json()["turns"][0]
    assert reloaded["action"] is None
    assert reloaded["answer_status"] == "FAILED"
    assert "private provider error" not in reloaded["assistant_message"]


def test_running_turn_is_reported_as_conflict_without_second_storage_record(client):
    from backend.app.conversation.routes import get_conversation_service
    from backend.app.storage.audits import AuditStore

    headers = _headers(client)
    conversation_id = client.post("/conversations", json={}, headers=headers).json()["conversation_id"]
    path = get_settings().APP_DATABASE_PATH
    account = AccountStore(path).by_username("reader")
    store = ConversationStore(path)
    store.begin_turn(conversation_id, account["id"], "already running", turn_id="running-turn")
    service = type("Injected", (), {"run_turn": lambda self, *args: store.begin_turn(conversation_id, account["id"], "second", turn_id="second-turn")})()
    client.app.dependency_overrides[get_conversation_service] = lambda: service
    try:
        response = client.post(f"/conversations/{conversation_id}/turns", json={"message": "second"}, headers=headers)
    finally:
        client.app.dependency_overrides.pop(get_conversation_service, None)

    assert response.status_code == 409
    detail = store.detail_for_account(conversation_id, account["id"])
    assert detail["total_turns"] == 1
    with connect_db(path) as db:
        assert db.execute("SELECT COUNT(*) FROM query_runs").fetchone()[0] == 0
