"""SQLite connection and additive schema migrations for the local application."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect_db(path):
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_db(path) -> None:
    with connect_db(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        if db.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
            return
        db.executescript("""
            CREATE TABLE accounts (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','admin')),
                password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_by TEXT, created_at TEXT NOT NULL,
                FOREIGN KEY(created_by) REFERENCES accounts(id)
            );
            CREATE TABLE sessions (
                token_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                csrf_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            );
            CREATE INDEX idx_sessions_account ON sessions(account_id);
            CREATE TABLE query_runs (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, username TEXT NOT NULL,
                role TEXT NOT NULL, operation TEXT NOT NULL, query TEXT NOT NULL,
                requested_controls TEXT NOT NULL, applied_controls TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, duration_ms REAL, error TEXT,
                FOREIGN KEY(account_id) REFERENCES accounts(id)
            );
            CREATE INDEX idx_runs_started ON query_runs(started_at DESC);
            CREATE INDEX idx_runs_account ON query_runs(account_id, started_at DESC);
            CREATE INDEX idx_runs_status ON query_runs(status, started_at DESC);
            CREATE TABLE query_events (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                stage TEXT NOT NULL, timestamp TEXT NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(run_id,sequence),
                FOREIGN KEY(run_id) REFERENCES query_runs(id)
            );
            CREATE TABLE query_results (
                run_id TEXT PRIMARY KEY, response TEXT NOT NULL, trace TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES query_runs(id)
            );
            CREATE TABLE account_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT,
                action TEXT NOT NULL, subject_id TEXT, timestamp TEXT NOT NULL
            );
        """)
        db.execute("INSERT INTO schema_migrations VALUES (1, ?)", (utc_now(),))
