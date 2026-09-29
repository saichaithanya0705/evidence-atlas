import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import app
from backend.app.storage.database import initialize_db
from backend.app.storage.accounts import AccountStore
from backend.app.auth.security import hash_password


@pytest.fixture
def account_client(tmp_path, monkeypatch):
    path = tmp_path / "accounts.sqlite3"
    monkeypatch.setenv("APP_DATABASE_PATH", str(path))
    get_settings.cache_clear()
    initialize_db(path)
    admin = AccountStore(path).create("admin", "Administrator", "admin", hash_password("correct-horse-battery"), None, False)
    with TestClient(app, base_url="http://testserver") as client:
        yield client, path, admin
    get_settings.cache_clear()


def _login(client, name="admin", password="correct-horse-battery"):
    return client.post("/auth/login", json={"username": name, "password": password}, headers={"Origin": "http://testserver"})


def _csrf(client):
    return {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf", "")}


def test_login_session_and_retired_key(account_client):
    client, path, admin = account_client
    assert client.get("/auth/me", headers={"X-Admin-Key": "test-admin-key"}).status_code == 401
    assert _login(client, password="wrong-password").status_code == 401
    response = _login(client)
    assert response.status_code == 200
    assert response.json()["account"]["role"] == "admin"
    assert "password_hash" not in response.text
    assert client.cookies.get("evidence_session")
    assert client.get("/auth/me").json()["account"]["username"] == "admin"
    assert client.post("/auth/logout", headers=_csrf(client)).status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_admin_creates_user_and_enforces_password_change(account_client):
    client, path, admin = account_client
    _login(client)
    response = client.post("/admin/accounts", json={"username": "newuser", "display_name": "New User", "role": "user", "temporary_password": "temporary-secret-12"}, headers=_csrf(client))
    assert response.status_code == 201
    assert response.json()["must_change_password"] == 1
    client.post("/auth/logout", headers=_csrf(client))
    assert _login(client, "newuser", "temporary-secret-12").status_code == 200
    assert client.post("/research", json={"query": "kidney disease"}, headers=_csrf(client)).status_code == 403
    changed = client.post("/auth/password", json={"current_password": "temporary-secret-12", "new_password": "new-strong-password-12"}, headers=_csrf(client))
    assert changed.status_code == 200
    assert client.get("/auth/me").status_code == 401
    assert _login(client, "newuser", "new-strong-password-12").status_code == 200
    assert client.get("/admin/accounts").status_code == 403


def test_csrf_and_last_admin(account_client):
    client, path, admin = account_client
    _login(client)
    assert client.post("/admin/accounts", json={"username": "x", "display_name": "x", "role": "user", "temporary_password": "long-password-1234"}).status_code == 403
    assert client.patch(f"/admin/accounts/{admin['id']}", json={"active": False}, headers=_csrf(client)).status_code == 400


def test_five_failed_logins_are_throttled(account_client):
    client, _, _ = account_client
    for _ in range(5):
        assert _login(client, password="incorrect-password").status_code == 401
    assert _login(client, password="incorrect-password").status_code == 429
