"""Durable, account-attributed query history and trace snapshots."""

from datetime import datetime
import json
import math

from .database import connect_db, utc_now


_EVENT_FIELDS = {
    "agent_decision": {"action", "complexity_hint", "accepted", "iteration", "route_floor"},
    "query_enhanced": {"iteration", "rewrite_applied"},
    "route_arbitrated": {"iteration", "route", "route_floor"},
    "query_analysis": {"status", "duration_ms", "route", "rule_route", "agent_complexity_hint"},
    "retrieval_attempt": {"iteration", "route"},
    "retrieve": {"status", "duration_ms", "candidate_count", "iteration"},
    "judge": {"status", "duration_ms", "grade", "missing_count", "conflict_count", "stop_reason", "iteration"},
    "evidence_judged": {"iteration", "grade", "missing_count", "conflict_count"},
    "correct": {"status", "duration_ms", "iteration"},
    "correction_stopped": {"reason", "iteration"},
    "claim_verified": {"claim_count", "supported_count"},
    "semantic_verification": {"supported_count", "unsupported_count"},
    "answer_released": {"status", "claim_count", "gap_count"},
    "evidence": {"status", "duration_ms", "evidence_count", "iteration"},
    "synthesize": {"status", "duration_ms"},
    "validate": {"status", "duration_ms"},
    "done": {"status", "duration_ms", "stop_reason"},
}
_RESPONSE_FIELDS = {"request_id", "query", "synthesis", "cited_pmids", "evidence_gaps", "evidence_table", "retrieved_papers", "citations_valid", "citation_precision", "consensus_level", "route", "answer_status"}
_EVIDENCE_FIELDS = {"pmid", "title", "year", "study_design", "population", "intervention", "comparator", "outcome", "key_findings", "limitations", "supporting_text_spans"}
_PAPER_FIELDS = {"pmid", "title", "abstract", "journal", "year", "authors", "mesh_terms", "study_type"}
_TRACE_FIELDS = {"valid", "citations_valid", "precision", "citation_precision", "cited_pmids", "invalid_pmids"}
_TIMING_FIELDS = {"total", "total_ms", "duration_ms", "query_analysis", "retrieval", "judge", "evidence", "synthesis", "validation"}
_ROUTES = {"SIMPLE", "MODERATE", "COMPLEX"}
_ACTIONS = {"RESEARCH", "ANSWER_FROM_EVIDENCE", "CLARIFY", "ABSTAIN"}
_ANSWER_STATUSES = {"SUPPORTED", "LIMITED", "INSUFFICIENT", "FAILED"}
_CONSENSUS_LEVELS = {"consensus", "mixed", "conflicting", "insufficient"}
_STOP_REASONS = {
    "retrieval_failed", "evidence_sufficient", "unresolved_conflict",
    "correction_budget_exhausted", "correction_disabled",
    "correction_rejected_below_route_floor", "correction_stalled",
    "citation_validation_failed_fail_closed", "completed",
}
_GRADES = {"SUFFICIENT", "INSUFFICIENT"}


def _json(value):
    return json.dumps(value or {}, ensure_ascii=False, default=str, separators=(",", ":"))


def _safe_gaps(values):
    if not isinstance(values, list):
        return []
    return [" ".join(item.split())[:240] for item in values[:10] if isinstance(item, str) and item.strip()]


def _safe_mapping(value, allowed):
    if not isinstance(value, dict):
        return {}
    return {
        key: item[:4000] if isinstance(item, str) else item
        for key in allowed if (item := value.get(key)) is not None
        and (type(item) in {str, int, float, bool})
        and (not isinstance(item, float) or math.isfinite(item))
    }


def _safe_string_list(value, *, limit=20, item_limit=200):
    if not isinstance(value, list):
        return []
    return [item[:item_limit] for item in value[:limit] if isinstance(item, str) and item.strip()]


def _safe_pmids(value):
    return [item for item in _safe_string_list(value, limit=100, item_limit=20) if item.isdigit()]


def _safe_controls(value):
    source = value if isinstance(value, dict) else {}
    result = {}
    for key in ("year_min", "year_max"):
        item = source.get(key)
        if type(item) is int and 1800 <= item <= 3000:
            result[key] = item
    loops = source.get("max_loops")
    if type(loops) is int and 0 <= loops <= 100:
        result["max_loops"] = loops
    study_types = source.get("study_types")
    if isinstance(study_types, list):
        result["study_types"] = _safe_string_list(study_types, limit=20, item_limit=80)
    return result


def _safe_evidence(value):
    result = _safe_mapping(value, _EVIDENCE_FIELDS)
    spans = value.get("supporting_text_spans")
    if isinstance(spans, list):
        result["supporting_text_spans"] = _safe_string_list(spans, limit=20, item_limit=1000)
    return result


def _safe_paper(value):
    result = _safe_mapping(value, _PAPER_FIELDS)
    for key in ("authors", "mesh_terms"):
        if isinstance(value.get(key), list):
            result[key] = _safe_string_list(value[key], limit=30, item_limit=160)
    return result


def _safe_citation_audit(value):
    result = _safe_mapping(value, _TRACE_FIELDS)
    for key in ("valid", "citations_valid"):
        if key in result and type(result[key]) is not bool:
            result.pop(key)
    for key in ("precision", "citation_precision"):
        if key in result and (type(result[key]) not in {int, float} or not 0 <= result[key] <= 1):
            result.pop(key)
    for key in ("cited_pmids", "invalid_pmids"):
        if key in value:
            result[key] = _safe_pmids(value[key])
    return result


def _safe_response(value):
    if not isinstance(value, dict):
        return None
    response = _safe_mapping(value, _RESPONSE_FIELDS)
    response["cited_pmids"] = _safe_pmids(value.get("cited_pmids"))
    response["evidence_gaps"] = _safe_gaps(value.get("evidence_gaps"))
    response["evidence_table"] = [
        _safe_evidence(item) for item in value.get("evidence_table", [])[:20]
        if isinstance(item, dict)
    ] if isinstance(value.get("evidence_table"), list) else []
    response["retrieved_papers"] = [
        _safe_paper(item) for item in value.get("retrieved_papers", [])[:20]
        if isinstance(item, dict)
    ] if isinstance(value.get("retrieved_papers"), list) else []
    if response.get("answer_status") not in _ANSWER_STATUSES:
        response.pop("answer_status", None)
    if response.get("route") not in _ROUTES:
        response.pop("route", None)
    if response.get("consensus_level") not in _CONSENSUS_LEVELS:
        response.pop("consensus_level", None)
    if type(response.get("citations_valid")) is not bool:
        response.pop("citations_valid", None)
    precision = response.get("citation_precision")
    if type(precision) not in {int, float} or not math.isfinite(precision) or not 0 <= precision <= 1:
        response.pop("citation_precision", None)
    return response


def _safe_trace(value):
    if not isinstance(value, dict):
        return None
    result = {}
    citation_audit = value.get("citation_audit")
    if isinstance(citation_audit, dict):
        result["citation_audit"] = _safe_citation_audit(citation_audit)
    timings = value.get("timings_ms")
    if isinstance(timings, dict):
        result["timings_ms"] = {
            key: item for key, item in timings.items()
            if key in _TIMING_FIELDS and isinstance(item, (int, float)) and math.isfinite(item)
        }
    return result


def _safe_event(event):
    stage = event.get("stage")
    allowed = _EVENT_FIELDS.get(stage)
    if allowed is None:
        return None
    source = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    payload = {}
    enum_fields = {
        "action": _ACTIONS, "complexity_hint": _ROUTES, "route": _ROUTES,
        "route_floor": _ROUTES, "rule_route": _ROUTES,
        "agent_complexity_hint": _ROUTES, "grade": _GRADES,
        "status": {"started", "completed", "failed"} | _ANSWER_STATUSES,
        "stop_reason": _STOP_REASONS, "reason": _STOP_REASONS,
    }
    boolean_fields = {"accepted", "rewrite_applied"}
    integer_fields = {"iteration", "candidate_count", "missing_count", "conflict_count", "claim_count", "supported_count", "unsupported_count", "gap_count", "evidence_count"}
    for key in allowed:
        item = source.get(key)
        if key in enum_fields and isinstance(item, str) and item in enum_fields[key]:
            payload[key] = item
        elif key in boolean_fields and type(item) is bool:
            payload[key] = item
        elif key == "duration_ms" and type(item) in {int, float} and math.isfinite(item) and item >= 0:
            payload[key] = item
        elif key in integer_fields and type(item) is int and 0 <= item <= 100000:
            payload[key] = item
    # semantic verdict objects can include rationale and claim text; expose only counts.
    if stage == "semantic_verification":
        verdicts = source.get("verdicts", [])
        if isinstance(verdicts, list):
            payload = {
                "supported_count": sum(bool(item.get("supported")) for item in verdicts if isinstance(item, dict)),
                "unsupported_count": sum(not bool(item.get("supported")) for item in verdicts if isinstance(item, dict)),
            }
    return {"stage": stage, "timestamp": event.get("timestamp"), "payload": payload}


def _admin_projection(row, events, response, trace):
    safe_events = [item for event in events if (item := _safe_event(event)) is not None]
    response = _safe_response(response)
    trace = _safe_trace(trace)
    by_stage = {}
    for event in safe_events:
        payload = event["payload"]
        by_stage[event["stage"]] = payload
    analysis = by_stage.get("query_analysis", {})
    agent_event = next((event["payload"] for event in safe_events if event["stage"] == "agent_decision" and "action" in event["payload"]), {})
    route_events = [event["payload"] for event in safe_events if event["stage"] == "route_arbitrated"]
    released = by_stage.get("answer_released", {})
    correction_count = min(100, sum(event["stage"] == "correct" and event["payload"].get("status") == "completed" for event in safe_events))
    durations = {
        event["stage"]: event["payload"]["duration_ms"]
        for event in safe_events if isinstance(event["payload"].get("duration_ms"), (int, float))
    }
    projected = {
        key: row.get(key) for key in (
            "id", "username", "role", "operation", "query", "status", "started_at",
            "finished_at", "duration_ms", "conversation_id", "turn_id",
        )
    }
    projected.update({
        "error": "The operation failed." if row.get("status") in {"failed", "interrupted"} else None,
        "requested_controls": _safe_controls(row.get("requested_controls")),
        "applied_controls": _safe_controls(row.get("applied_controls")),
        "agent_action": agent_event.get("action"),
        "agent_complexity_hint": agent_event.get("complexity_hint") or analysis.get("agent_complexity_hint"),
        "rule_route": analysis.get("rule_route"),
        "final_route": (route_events[-1].get("route") if route_events else None) or analysis.get("route") or (response or {}).get("route"),
        "answer_status": (response or {}).get("answer_status") or released.get("status"),
        "correction_count": correction_count,
        "evidence_gaps": _safe_gaps((response or {}).get("evidence_gaps")),
        "stage_durations_ms": durations,
        "response": response,
        "trace": trace,
        "events": safe_events,
    })
    return projected


class AuditStore:
    def __init__(self, path):
        self.path = path

    def start(self, run_id, account, operation, query, requested, applied, *, conversation_id=None, turn_id=None):
        if len(query) > 4000:
            raise ValueError("Research question exceeds 4000 characters")
        with connect_db(self.path) as db:
            db.execute("""INSERT INTO query_runs(
                id, account_id, username, role, operation, query,
                requested_controls, applied_controls, status, started_at,
                finished_at, duration_ms, error, conversation_id, turn_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,?,?)""", (
                run_id, account["id"], account["username"], account["role"], operation, query,
                _json(requested), _json(applied), "running", utc_now(), conversation_id, turn_id,
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

    def admin_detail(self, run_id):
        raw = self.detail(run_id)
        if raw is None:
            return None
        return _admin_projection(raw, raw["events"], raw.get("response"), raw.get("trace"))

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
            rows = db.execute("SELECT id FROM query_runs" + where + " ORDER BY started_at DESC,id DESC LIMIT ? OFFSET ?", [*params, min(100, max(1, limit)), max(0, offset)]).fetchall()
        return {"items": [self.admin_detail(row["id"]) for row in rows], "total": total}

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
