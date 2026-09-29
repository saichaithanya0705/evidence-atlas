"""Durable account-owned conversations and turn lifecycle storage."""

import json
import sqlite3
import uuid

from .database import connect_db, utc_now


class ConversationBusyError(RuntimeError):
    """Raised when a conversation already has a turn in progress."""


_TITLE_MAX = 80
_MESSAGE_MAX = 4000
_PAGE_MAX = 100


def _bounded_text(value, label, maximum, *, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.strip()
    if (not value and not allow_empty) or len(value) > maximum:
        raise ValueError(f"Invalid {label}")
    return value


def _page(limit, offset, default):
    try:
        limit = int(limit)
        offset = int(offset)
    except (TypeError, ValueError):
        raise ValueError("Invalid pagination") from None
    return min(_PAGE_MAX, max(1, limit if limit is not None else default)), max(0, offset)


class ConversationStore:
    def __init__(self, path):
        self.path = path

    def create(self, account_id: str, title: str = "New research") -> dict:
        title = _bounded_text(title, "title", _TITLE_MAX)
        conversation_id = str(uuid.uuid4())
        created = utc_now()
        with connect_db(self.path) as db:
            db.execute(
                "INSERT INTO conversations(id,account_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
                (conversation_id, account_id, title, created, created),
            )
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            return dict(row)

    def update_title(self, conversation_id: str, account_id: str, title: str) -> dict | None:
        title = _bounded_text(title, "title", _TITLE_MAX)
        with connect_db(self.path) as db:
            cursor = db.execute(
                "UPDATE conversations SET title=?,updated_at=? WHERE id=? AND account_id=?",
                (title, utc_now(), conversation_id, account_id),
            )
            if cursor.rowcount == 0:
                return None
            return dict(db.execute("SELECT * FROM conversations WHERE id=? AND account_id=?", (conversation_id, account_id)).fetchone())

    def list_for_account(self, account_id: str, *, limit: int = 50, offset: int = 0) -> dict:
        limit, offset = _page(limit, offset, 50)
        with connect_db(self.path) as db:
            total = db.execute("SELECT COUNT(*) FROM conversations WHERE account_id=?", (account_id,)).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM conversations WHERE account_id=? ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                (account_id, limit, offset),
            ).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def detail_for_account(self, conversation_id: str, account_id: str, *, limit: int = 100, offset: int = 0) -> dict | None:
        limit, offset = _page(limit, offset, 100)
        with connect_db(self.path) as db:
            conversation = db.execute(
                "SELECT * FROM conversations WHERE id=? AND account_id=?", (conversation_id, account_id),
            ).fetchone()
            if conversation is None:
                return None
            total = db.execute(
                "SELECT COUNT(*) FROM conversation_turns WHERE conversation_id=?", (conversation_id,),
            ).fetchone()[0]
            rows = db.execute(
                "SELECT * FROM conversation_turns WHERE conversation_id=? ORDER BY ordinal DESC LIMIT ? OFFSET ?",
                (conversation_id, limit, offset),
            ).fetchall()
        return {"conversation": dict(conversation), "turns": [dict(row) for row in rows], "total_turns": total}

    def begin_turn(self, conversation_id: str, account_id: str, user_message: str, *, turn_id: str | None = None) -> dict:
        user_message = _bounded_text(user_message, "user message", _MESSAGE_MAX)
        turn_id = turn_id or str(uuid.uuid4())
        created = utc_now()
        try:
            with connect_db(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                conversation = db.execute(
                    "SELECT id FROM conversations WHERE id=? AND account_id=?", (conversation_id, account_id),
                ).fetchone()
                if conversation is None:
                    raise ValueError("Conversation not found")
                ordinal = db.execute(
                    "SELECT COALESCE(MAX(ordinal),0)+1 FROM conversation_turns WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()[0]
                db.execute(
                    """INSERT INTO conversation_turns(
                        id,conversation_id,ordinal,user_message,status,created_at
                    ) VALUES (?,?,?,?,'running',?)""",
                    (turn_id, conversation_id, ordinal, user_message, created),
                )
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (created, conversation_id))
                return dict(db.execute("SELECT * FROM conversation_turns WHERE id=?", (turn_id,)).fetchone())
        except sqlite3.IntegrityError as exc:
            with connect_db(self.path) as db:
                running = db.execute(
                    "SELECT 1 FROM conversation_turns WHERE conversation_id=? AND status='running'",
                    (conversation_id,),
                ).fetchone()
            if running:
                raise ConversationBusyError("A turn is already running for this conversation") from exc
            raise

    def complete_turn(
        self, turn_id: str, *, agent_action: str, standalone_query: str | None,
        complexity_hint: str | None, final_route: str | None, answer_status: str,
        assistant_message: str, audit_run_id: str, public_response: dict,
    ) -> dict:
        assistant_message = _bounded_text(assistant_message, "assistant message", _MESSAGE_MAX, allow_empty=True)
        encoded = json.dumps(public_response, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str, allow_nan=False)
        completed = utc_now()
        with connect_db(self.path) as db:
            row = db.execute("SELECT conversation_id,status FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("Conversation turn is not running")
            db.execute(
                """UPDATE conversation_turns SET agent_action=?,standalone_query=?,complexity_hint=?,
                    final_route=?,answer_status=?,assistant_message=?,audit_run_id=?,
                    public_response_json=?,status='completed',completed_at=? WHERE id=?""",
                (agent_action, standalone_query, complexity_hint, final_route, answer_status,
                 assistant_message, audit_run_id, encoded, completed, turn_id),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (completed, row["conversation_id"]))
            return dict(db.execute("SELECT * FROM conversation_turns WHERE id=?", (turn_id,)).fetchone())

    def fail_turn(self, turn_id: str, *, assistant_message: str, audit_run_id: str | None = None) -> dict:
        assistant_message = _bounded_text(assistant_message, "assistant message", _MESSAGE_MAX, allow_empty=True)
        completed = utc_now()
        with connect_db(self.path) as db:
            row = db.execute("SELECT conversation_id,status FROM conversation_turns WHERE id=?", (turn_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("Conversation turn is not running")
            db.execute(
                "UPDATE conversation_turns SET status='failed',answer_status='FAILED',assistant_message=?,audit_run_id=?,completed_at=? WHERE id=?",
                (assistant_message, audit_run_id, completed, turn_id),
            )
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (completed, row["conversation_id"]))
            return dict(db.execute("SELECT * FROM conversation_turns WHERE id=?", (turn_id,)).fetchone())
