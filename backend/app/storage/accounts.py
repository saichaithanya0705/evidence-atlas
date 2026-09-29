"""Account and session repository; callers handle password hashing."""

from datetime import datetime, timezone
import uuid

from .database import connect_db, utc_now


def public_account(row):
    if row is None:
        return None
    return {key: row[key] for key in ("id", "username", "display_name", "role", "active", "must_change_password", "created_at")}


class AccountStore:
    def __init__(self, path):
        self.path = path

    def create(self, username, display_name, role, password_hash, created_by=None, must_change_password=True):
        normalized = username.strip().casefold()
        if not normalized or len(normalized) > 64 or role not in {"user", "admin"} or not password_hash:
            raise ValueError("Invalid account details")
        account_id = str(uuid.uuid4())
        with connect_db(self.path) as db:
            if db.execute("SELECT 1 FROM accounts WHERE username=?", (normalized,)).fetchone():
                raise ValueError("Username already exists")
            db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,1,?,?,?)", (
                account_id, normalized, display_name.strip()[:120] or normalized, role,
                password_hash, int(must_change_password), created_by, utc_now(),
            ))
            db.execute("INSERT INTO account_events(actor_id,action,subject_id,timestamp) VALUES (?,?,?,?)", (
                created_by, "create", account_id, utc_now(),
            ))
        return self.by_id(account_id)

    def by_username(self, username):
        with connect_db(self.path) as db:
            row = db.execute("SELECT * FROM accounts WHERE username=?", (username.strip().casefold(),)).fetchone()
            return dict(row) if row else None

    def by_id(self, account_id):
        with connect_db(self.path) as db:
            row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            return dict(row) if row else None

    def list_accounts(self, limit=100, offset=0):
        with connect_db(self.path) as db:
            rows = db.execute("SELECT * FROM accounts ORDER BY created_at DESC LIMIT ? OFFSET ?", (min(100, max(1, limit)), max(0, offset))).fetchall()
            total = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
        return {"items": [public_account(row) for row in rows], "total": total}

    def update(self, account_id, actor_id, *, active=None, role=None, password_hash=None, must_change_password=None):
        with connect_db(self.path) as db:
            # Serialize the last-admin check with the update. A deferred
            # transaction would let two administrators both observe count=2.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if row is None:
                raise ValueError("Account not found")
            new_active = row["active"] if active is None else int(bool(active))
            new_role = row["role"] if role is None else role
            if new_role not in {"user", "admin"}:
                raise ValueError("Invalid role")
            if row["role"] == "admin" and row["active"] and (new_role != "admin" or not new_active):
                count = db.execute("SELECT COUNT(*) FROM accounts WHERE role='admin' AND active=1").fetchone()[0]
                if count <= 1:
                    raise ValueError("Cannot remove the last active administrator")
            db.execute("UPDATE accounts SET role=?, active=?, password_hash=?, must_change_password=? WHERE id=?", (
                new_role, new_active, password_hash or row["password_hash"],
                row["must_change_password"] if must_change_password is None else int(bool(must_change_password)), account_id,
            ))
            if not new_active or password_hash or new_role != row["role"]:
                db.execute("DELETE FROM sessions WHERE account_id=?", (account_id,))
            db.execute("INSERT INTO account_events(actor_id,action,subject_id,timestamp) VALUES (?,?,?,?)", (
                actor_id, "update", account_id, utc_now(),
            ))
        return self.by_id(account_id)

    def create_session(self, token_hash, csrf_hash, account_id, expires_at):
        with connect_db(self.path) as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (token_hash, account_id, csrf_hash, utc_now(), expires_at))

    def session(self, token_hash):
        with connect_db(self.path) as db:
            row = db.execute("SELECT s.*, a.username, a.display_name, a.role, a.active, a.must_change_password, a.created_at FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.token_hash=?", (token_hash,)).fetchone()
            if not row or not row["active"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                return None
            result = dict(row)
            result["id"] = result["account_id"]
            return result

    def revoke_session(self, token_hash):
        with connect_db(self.path) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
