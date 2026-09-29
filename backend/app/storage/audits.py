"""Durable, account-attributed query history and trace snapshots."""

from datetime import datetime
import json
import math

from .database import connect_db, utc_now


def _json(value):
    return json.dumps(value or {}, ensure_ascii=False, default=str, separators=(",", ":"))


class AuditStore:
    def __init__(self, path):
        self.path = path

    def start(self, run_id, account, operation, query, requested, applied):
        if len(query) > 4000:
            raise ValueError("Research question exceeds 4000 characters")
        with connect_db(self.path) as db:
            db.execute("INSERT INTO query_runs VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)", (
                run_id, account["id"], account["username"], account["role"], operation, query,
                _json(requested), _json(applied), "running", utc_now(),
            ))

    def event(self, run_id, stage, payload):
        encoded = _json(payload)
        if len(encoded) > 100000:
            raise ValueError("Audit event exceeds size limit")
        with connect_db(self.path) as db:
            sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM query_events WHERE run_id=?", (run_id,)).fetchone()[0]
            db.execute("INSERT INTO query_events VALUES (?,?,?,?,?)", (run_id, sequence, stage, utc_now(), encoded))

    def applied(self, run_id, controls):
        with connect_db(self.path) as db:
            db.execute("UPDATE query_runs SET applied_controls=? WHERE id=?", (_json(controls), run_id))

    def finish(self, run_id, status, response=None, trace=None, error=None):
        with connect_db(self.path) as db:
            row = db.execute("SELECT started_at,status FROM query_runs WHERE id=?", (run_id,)).fetchone()
            if row is None or row["status"] != "running":
                raise ValueError("Audit run is not open")
            end = utc_now()
            duration = (datetime.fromisoformat(end) - datetime.fromisoformat(row["started_at"])).total_seconds() * 1000
            db.execute("UPDATE query_runs SET status=?,finished_at=?,duration_ms=?,error=? WHERE id=?", (status, end, round(duration, 2), error, run_id))
            db.execute("INSERT INTO query_results VALUES (?,?,?)", (run_id, _json(response), _json(trace)))

    def recover_interrupted(self):
        with connect_db(self.path) as db:
            rows = db.execute("SELECT id,started_at FROM query_runs WHERE status='running'").fetchall()
            for row in rows:
                end = utc_now()
                duration = (datetime.fromisoformat(end) - datetime.fromisoformat(row["started_at"])).total_seconds() * 1000
                db.execute("UPDATE query_runs SET status='interrupted',finished_at=?,duration_ms=?,error='Service stopped before completion' WHERE id=?", (end, round(duration, 2), row["id"]))
            return len(rows)

    def detail(self, run_id):
        with connect_db(self.path) as db:
            row = db.execute("SELECT * FROM query_runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["requested_controls"] = json.loads(result["requested_controls"])
            result["applied_controls"] = json.loads(result["applied_controls"])
            stored = db.execute("SELECT * FROM query_results WHERE run_id=?", (run_id,)).fetchone()
            result["response"] = json.loads(stored["response"]) if stored else None
            result["trace"] = json.loads(stored["trace"]) if stored else None
            events = db.execute("SELECT stage,timestamp,payload FROM query_events WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
            result["events"] = [{"stage": e["stage"], "timestamp": e["timestamp"], "payload": json.loads(e["payload"])} for e in events]
            return result

    def list_runs(self, *, limit=50, offset=0, account=None, status=None, query=None, from_date=None, to_date=None):
        clauses, params = [], []
        if account:
            clauses.append("username=?")
            params.append(account.strip().casefold())
        if status:
            clauses.append("status=?")
            params.append(status)
        if query:
            clauses.append("query LIKE ? ESCAPE '\\'")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        if from_date:
            clauses.append("started_at>=?")
            params.append(from_date)
        if to_date:
            clauses.append("started_at<?")
            params.append(to_date)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with connect_db(self.path) as db:
            total = db.execute("SELECT COUNT(*) FROM query_runs" + where, params).fetchone()[0]
            rows = db.execute("SELECT id,username,role,operation,query,status,started_at,finished_at,duration_ms,error FROM query_runs" + where + " ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?", [*params, min(100, max(1, limit)), max(0, offset)]).fetchall()
        return {"items": [dict(row) for row in rows], "total": total}

    def aggregate(self, from_date=None):
        with connect_db(self.path) as db:
            where = " WHERE started_at>=?" if from_date else ""
            rows = db.execute("SELECT operation,status,duration_ms FROM query_runs" + where, (from_date,) if from_date else ()).fetchall()
        durations = sorted(row["duration_ms"] for row in rows if row["duration_ms"] is not None)
        return {
            "total_queries": len(rows),
            "by_operation": {key: sum(row["operation"] == key for row in rows) for key in sorted({row["operation"] for row in rows})},
            "by_status": {key: sum(row["status"] == key for row in rows) for key in sorted({row["status"] for row in rows})},
            "average_duration_ms": round(sum(durations) / len(durations), 2) if durations else None,
            "p95_duration_ms": durations[math.ceil(.95 * len(durations)) - 1] if durations else None,
        }
