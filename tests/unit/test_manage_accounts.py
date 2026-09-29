"""Local account recovery must not disclose the new password or retain sessions."""

from types import SimpleNamespace
import sys

from backend.app.auth.security import hash_password, verify_password
from backend.app.storage.accounts import AccountStore
from backend.app.storage.database import initialize_db
from scripts import manage_accounts


def test_local_password_reset_revokes_sessions_and_requires_change(tmp_path, monkeypatch, capsys):
    path = tmp_path / "accounts.sqlite3"
    initialize_db(path)
    store = AccountStore(path)
    admin = store.create("admin", "Admin", "admin", hash_password("original-password-123"), None, False)
    store.create_session("session-hash", "csrf-hash", admin["id"], "2099-01-01T00:00:00+00:00")
    monkeypatch.setattr(manage_accounts, "get_settings", lambda: SimpleNamespace(APP_DATABASE_PATH=path))
    monkeypatch.setattr(manage_accounts, "getpass", lambda _: "new-admin-password-123")
    monkeypatch.setattr(sys, "argv", ["manage_accounts.py", "reset-password", "--username", "admin"])

    manage_accounts.main()

    updated = store.by_id(admin["id"])
    assert verify_password("new-admin-password-123", updated["password_hash"])
    assert updated["must_change_password"] == 1
    assert store.session("session-hash") is None
    assert "new-admin-password-123" not in capsys.readouterr().out
