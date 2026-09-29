import json
from threading import Barrier, Thread

import pytest

from backend.app.storage.accounts import AccountStore
from backend.app.storage.conversations import ConversationBusyError, ConversationStore
from backend.app.storage.database import connect_db, initialize_db


def _accounts(path):
    initialize_db(path)
    store = AccountStore(path)
    first = store.create("alice", "Alice", "user", "hash", None, False)
    second = store.create("bob", "Bob", "user", "hash", None, False)
    return first, second


def test_fresh_database_has_conversation_schema_and_v1_upgrade_preserves_data(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    initialize_db(path)
    account = AccountStore(path).create("alice", "Alice", "user", "hash", None, False)
    with connect_db(path) as db:
        assert [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
        columns = {row[1] for row in db.execute("PRAGMA table_info(query_runs)")}
        assert {"conversation_id", "turn_id"} <= columns

    old_path = tmp_path / "version-one.sqlite3"
    initialize_db(old_path)
    old_account = AccountStore(old_path).create("legacy", "Legacy", "user", "hash", None, False)
    with connect_db(old_path) as db:
        db.execute("INSERT INTO query_runs(id,account_id,username,role,operation,query,requested_controls,applied_controls,status,started_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "old-run", old_account["id"], "legacy", "user", "research", "old question", "{}", "{}", "completed", "2026-01-01T00:00:00+00:00",
        ))
        db.execute("DROP INDEX IF EXISTS idx_runs_conversation")
        db.execute("DROP INDEX IF EXISTS idx_runs_turn")
        db.execute("ALTER TABLE query_runs DROP COLUMN conversation_id")
        db.execute("ALTER TABLE query_runs DROP COLUMN turn_id")
        db.execute("DROP TABLE conversation_turns")
        db.execute("DROP TABLE conversations")
        db.execute("DELETE FROM schema_migrations WHERE version=2")
    initialize_db(old_path)
    with connect_db(old_path) as db:
        assert tuple(db.execute("SELECT username,query FROM query_runs WHERE id='old-run'").fetchone()) == ("legacy", "old question")
        assert [row[0] for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    assert ConversationStore(old_path).create(old_account["id"])["account_id"] == old_account["id"]


def test_owned_conversation_title_validation_pagination_and_turn_lifecycle(tmp_path):
    path = tmp_path / "conversations.sqlite3"
    alice, bob = _accounts(path)
    store = ConversationStore(path)
    first = store.create(alice["id"])
    second = store.create(alice["id"], "Follow up")
    assert first["title"] == "New research"
    assert store.detail_for_account(first["id"], bob["id"]) is None
    assert store.update_title(first["id"], bob["id"], "Stolen") is None
    assert store.update_title("missing", alice["id"], "Title") is None
    with pytest.raises(ValueError):
        store.create(alice["id"], "x" * 81)
    with pytest.raises(ValueError):
        store.update_title(first["id"], alice["id"], " ")

    # Equal timestamps still have a deterministic ID tie break; update activity
    # controls ordering and pagination is bounded to the requested account.
    with connect_db(path) as db:
        db.execute("UPDATE conversations SET updated_at='2026-01-01T00:00:00+00:00' WHERE account_id=?", (alice["id"],))
    store.update_title(first["id"], alice["id"], "Renamed")
    rows = store.list_for_account(alice["id"], limit=1, offset=0)
    assert rows["total"] == 2 and len(rows["items"]) == 1
    assert rows["items"][0]["id"] == first["id"]
    assert store.list_for_account(alice["id"], limit=1, offset=1)["items"][0]["id"] == second["id"]
    assert store.list_for_account(bob["id"])["items"] == []
    assert store.list_for_account(alice["id"], limit=5000)["total"] == 2

    one = store.begin_turn(first["id"], alice["id"], "What is the evidence?", turn_id="turn-1")
    assert one["ordinal"] == 1 and one["status"] == "running"
    with pytest.raises(ConversationBusyError):
        store.begin_turn(first["id"], alice["id"], "Concurrent question", turn_id="turn-blocked")
    with connect_db(path) as db:
        assert db.execute("SELECT COUNT(*) FROM conversation_turns WHERE conversation_id=?", (first["id"],)).fetchone()[0] == 1

    completed = store.complete_turn(
        "turn-1", agent_action="RESEARCH", standalone_query="Evidence question",
        complexity_hint="SIMPLE", final_route="SIMPLE", answer_status="SUPPORTED",
        assistant_message="A concise answer", audit_run_id="run-1", public_response={"z": 1, "a": 2},
    )
    assert completed["status"] == "completed"
    assert json.loads(completed["public_response_json"]) == {"a": 2, "z": 1}
    assert completed["completed_at"] is not None
    two = store.begin_turn(first["id"], alice["id"], "Another question", turn_id="turn-2")
    assert two["ordinal"] == 2
    failed = store.fail_turn("turn-2", assistant_message="Please retry")
    assert failed["status"] == "failed" and failed["audit_run_id"] is None
    three = store.begin_turn(first["id"], alice["id"], "Retry", turn_id="turn-3")
    assert three["ordinal"] == 3
    detail = store.detail_for_account(first["id"], alice["id"], limit=2, offset=1)
    assert detail["conversation"]["id"] == first["id"]
    assert [turn["id"] for turn in detail["turns"]] == ["turn-2", "turn-1"]
    assert detail["total_turns"] == 3


def test_partial_unique_index_allows_only_one_concurrent_running_turn(tmp_path):
    path = tmp_path / "concurrent.sqlite3"
    alice, _ = _accounts(path)
    store = ConversationStore(path)
    conversation = store.create(alice["id"])
    gate = Barrier(3)
    outcomes = []

    def begin(turn_id):
        gate.wait()
        try:
            store.begin_turn(conversation["id"], alice["id"], turn_id, turn_id=turn_id)
            outcomes.append("started")
        except ConversationBusyError:
            outcomes.append("busy")

    threads = [Thread(target=begin, args=(turn_id,)) for turn_id in ("first", "second")]
    for thread in threads:
        thread.start()
    gate.wait()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()
    assert outcomes.count("started") == 1
    assert outcomes.count("busy") == 1
    with connect_db(path) as db:
        assert db.execute("SELECT COUNT(*) FROM conversation_turns WHERE conversation_id=?", (conversation["id"],)).fetchone()[0] == 1
        indexes = {row[1] for row in db.execute("PRAGMA index_list(conversation_turns)")}
        assert "idx_conversation_turns_one_running" in indexes
