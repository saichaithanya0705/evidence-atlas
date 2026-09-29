import pytest
from contextlib import contextmanager
from threading import Event, Thread, current_thread

import backend.app.storage.accounts as accounts_module

from backend.app.storage.database import initialize_db
from backend.app.storage.accounts import AccountStore
from backend.app.storage.audits import AuditStore


def test_database_reopens_accounts_and_audits(tmp_path):
    path = tmp_path / "app.sqlite3"
    initialize_db(path)
    initialize_db(path)
    accounts = AccountStore(path)
    admin = accounts.create("  Admin  ", "Administrator", "admin", "hashed-password", None, False)
    assert accounts.by_username("admin")["id"] == admin["id"]
    with pytest.raises(ValueError):
        accounts.create("ADMIN", "Another", "user", "hash", admin["id"], True)

    audits = AuditStore(path)
    audits.start("run-1", admin, "research", "kidney outcomes", {"year_min": 2020}, {})
    audits.event("run-1", "retrieve", {"pmids": ["123"]})
    audits.finish("run-1", "completed", {"request_id": "run-1", "synthesis": "Example"}, {"stages": ["retrieve"]})
    reopened = AuditStore(path)
    detail = reopened.detail("run-1")
    assert detail["username"] == "admin"
    assert detail["trace"]["stages"] == ["retrieve"]
    assert detail["events"][0]["stage"] == "retrieve"
    assert reopened.list_runs(limit=5000)["items"][0]["id"] == "run-1"


def test_recover_interrupted_run(tmp_path):
    path = tmp_path / "app.sqlite3"
    initialize_db(path)
    account = AccountStore(path).create("user", "User", "user", "hash", None, False)
    audits = AuditStore(path)
    audits.start("interrupted", account, "research", "question", {}, {})
    audits.event("interrupted", "query_analysis", {"route": "SIMPLE"})
    assert audits.recover_interrupted() == 1
    row = AuditStore(path).detail("interrupted")
    assert row["status"] == "interrupted"
    assert row["events"][0]["payload"]["route"] == "SIMPLE"


def test_concurrent_admin_deactivation_keeps_one_active(tmp_path, monkeypatch):
    path = tmp_path / "admins.sqlite3"
    initialize_db(path)
    store = AccountStore(path)
    first = store.create("first", "First", "admin", "hash", None, False)
    second = store.create("second", "Second", "admin", "hash", None, False)
    first_checked = Event()
    second_checked = Event()
    original_connect = accounts_module.connect_db

    @contextmanager
    def coordinated_connection(db_path):
        with original_connect(db_path) as db:
            class Proxy:
                def execute(self, sql, parameters=()):
                    result = db.execute(sql, parameters)
                    if "SELECT COUNT(*) FROM accounts WHERE role='admin'" in sql:
                        if current_thread().name == "first-update":
                            first_checked.set()
                            second_checked.wait(.5)
                        else:
                            second_checked.set()
                    return result
            yield Proxy()

    monkeypatch.setattr(accounts_module, "connect_db", coordinated_connection)
    outcomes = []

    def disable(account, actor):
        try:
            store.update(account["id"], actor["id"], active=False)
            outcomes.append("disabled")
        except ValueError:
            outcomes.append("blocked")

    one = Thread(name="first-update", target=disable, args=(first, second))
    two = Thread(name="second-update", target=disable, args=(second, first))
    one.start()
    assert first_checked.wait(2)
    two.start()
    one.join(3)
    two.join(3)
    assert not one.is_alive() and not two.is_alive()
    assert outcomes.count("disabled") == 1
    assert sum(item["active"] for item in store.list_accounts()["items"] if item["role"] == "admin") == 1
