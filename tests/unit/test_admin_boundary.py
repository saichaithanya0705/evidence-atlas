"""Regression checks for identity-based diagnostic access."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.auth.security import hash_password
from backend.app.core.config import get_settings
from backend.app.models.request_response import EvidenceRecord, ResearchResponse, RetrievalCandidate
from backend.app.storage.accounts import AccountStore
from backend.app.storage.database import initialize_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "boundary.sqlite3"
    monkeypatch.setenv("APP_DATABASE_PATH", str(path))
    monkeypatch.setenv("EVALUATION_REPORTS_DIR", str(tmp_path / "evaluation-reports"))
    get_settings.cache_clear()
    initialize_db(path)
    store = AccountStore(path)
    store.create("admin", "Administrator", "admin", hash_password("admin-password-123"), None, False)
    store.create("reader", "Reader", "user", hash_password("reader-password-123"), None, False)
    with TestClient(main.app, base_url="http://testserver") as value:
        yield value
    get_settings.cache_clear()


def sign_in(client, username, password):
    result = client.post("/auth/login", json={"username": username, "password": password}, headers={"Origin": "http://testserver"})
    assert result.status_code == 200
    return {"Origin": "http://testserver", "X-CSRF-Token": client.cookies.get("evidence_csrf")}


@pytest.mark.parametrize("method,path", [("post", "/analyze-query"), ("get", "/trace/unknown"), ("get", "/metrics"), ("get", "/admin/audits")])
def test_shared_key_cannot_bypass_sign_in(client, method, path):
    response = getattr(client, method)(path, headers={"X-Admin-Key": "legacy-key"})
    assert response.status_code == 401


def test_ordinary_account_cannot_read_diagnostics(client):
    headers = sign_in(client, "reader", "reader-password-123")
    assert client.post("/analyze-query", json={"query": "diabetes"}, headers=headers).status_code == 403
    assert client.get("/trace/unknown").status_code == 403
    assert client.get("/metrics").status_code == 403
    assert client.get("/admin/audits").status_code == 403


def test_public_health_is_coarse(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert set(response.json()) == {"status", "service", "version"}


def test_reader_search_contains_no_query_analysis(client, monkeypatch):
    from types import SimpleNamespace

    class FakeSearchService:
        def search(self, *args):
            return SimpleNamespace(canonical_query="diabetes", route="SIMPLE"), [], {"secret": "admin-only"}

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeSearchService())
    headers = sign_in(client, "reader", "reader-password-123")
    response = client.post("/search", json={"query": "diabetes"}, headers=headers)
    assert response.status_code == 200
    assert set(response.json()) == {"query", "total_results", "candidates"}


def test_reader_research_excludes_diagnostics(client, monkeypatch):
    candidate = RetrievalCandidate(pmid="12345", title="Example study", abstract="An abstract.", channel_scores={"dense": .9}, channel_ranks={"dense": 1}, rrf_score=.5, reranker_score=.8)

    class FakeResearchService:
        def research(self, query, filters, max_loops, request_id, event_sink=None):
            return ResearchResponse(request_id=request_id, query=query, canonical_query="diabetes mellitus", route="SIMPLE", synthesis="A grounded result [PMID: 12345].", evidence_table=[EvidenceRecord(pmid="12345", title="Example study", key_findings="Grounded finding", supporting_text_spans=["Exact abstract span"])], cited_pmids=["12345"], citations_valid=True, citation_precision=1.0, consensus_level="consensus", evidence_gaps=["  Missing   safety evidence  "], audit_trace_url=f"/trace/{request_id}", retrieved_papers=[candidate])

        def get_trace(self, request_id):
            return {"request_id": request_id, "stages": []}

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeResearchService())
    headers = sign_in(client, "reader", "reader-password-123")
    response = client.post("/research", json={"query": "diabetes"}, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    for field in ("audit_trace_url", "canonical_query", "route", "citation_precision", "consensus_level"):
        assert field not in body
    assert body["evidence_gaps"] == ["Missing safety evidence"]
    assert body["evidence_table"][0]["supporting_text_spans"] == ["Exact abstract span"]
    assert "channel_scores" not in body["retrieved_papers"][0]


def test_admin_analyze_query_uses_stable_response_envelope(client, monkeypatch):
    from backend.app.models.request_response import PICOModel, QueryPlan
    from backend.app.auth import routes as auth_routes

    class FakeQueryService:
        def build_query_plan(self, query):
            return QueryPlan(
                original_query=query, clean_query=query, canonical_query="diabetes outcomes",
                mesh_terms=["Diabetes Mellitus"], pico=PICOModel(population="Adults"),
                route="MODERATE", router_confidence=0.84, router_reasoning="multi concept",
            ), None

    monkeypatch.setattr(main, "_query_service", FakeQueryService())
    auth_routes._attempts.clear()
    headers = sign_in(client, "admin", "admin-password-123")
    response = client.post("/analyze-query", json={"query": "diabetes outcomes"}, headers=headers)

    assert response.status_code == 200
    assert set(response.json()) == {"query_plan"}
    assert response.json()["query_plan"]["canonical_query"] == "diabetes outcomes"
    schema = client.get("/openapi.json").json()["paths"]["/analyze-query"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/AnalyzeQueryResponse"}


def test_public_research_adds_only_safe_interpretation(client, monkeypatch):
    from backend.app.models.request_response import PICOModel, QueryPlan

    candidate = RetrievalCandidate(pmid="12345", title="Trial", abstract="Abstract", channel_scores={"dense": 0.8})
    plan = QueryPlan(
        original_query="diabetes", clean_query="diabetes", canonical_query="diabetes mellitus",
        mesh_terms=["Diabetes Mellitus"], pico=PICOModel(population="Adults"), route="MODERATE",
        router_confidence=0.94, router_reasoning="private explanation", subqueries=["adverse events"],
    )
    class FakeResearchService:
        def research(self, query, filters, max_loops, request_id, event_sink=None):
            return ResearchResponse(
                request_id=request_id, query=query, canonical_query=plan.canonical_query, route=plan.route,
                synthesis="Grounded result [PMID: 12345].", evidence_table=[], cited_pmids=["12345"],
                citations_valid=True, citation_precision=1.0, consensus_level="consensus", evidence_gaps=[],
                audit_trace_url=f"/trace/{request_id}", retrieved_papers=[candidate],
                query_plan=plan, research_plan={"subquestions": [{"id": "sq-1", "question": "Assess outcomes", "dependencies": [], "concepts": ["outcomes"]}]},
                coverage_statuses={"sq-1": "COVERED"},
            )

        def get_trace(self, request_id):
            return {"request_id": request_id, "stages": []}

    monkeypatch.setattr(main, "_get_research_service", lambda: FakeResearchService())
    headers = sign_in(client, "reader", "reader-password-123")
    response = client.post("/research", json={"query": "diabetes"}, headers=headers)

    assert response.status_code == 200
    interpretation = response.json()["interpretation"]
    assert interpretation == {
        "canonical_question": "diabetes mellitus",
        "pico": {"population": "Adults", "intervention": None, "comparator": None, "outcome": None},
        "mesh_concepts": ["Diabetes Mellitus"],
        "route": "MODERATE",
        "subquestions": [{"id": "sq-1", "question": "Assess outcomes"}],
        "coverage_statuses": [{"subquestion_id": "sq-1", "status": "COVERED"}],
    }
    encoded = str(interpretation).lower()
    assert not any(secret in encoded for secret in ("router_confidence", "router_reasoning", "scores", "trace", "retrieval_iteration"))


def test_reader_cannot_read_linked_admin_trace_or_internal_metadata(client, monkeypatch, tmp_path):
    from backend.app.storage.audits import AuditStore

    path = tmp_path / "boundary.sqlite3"
    account = AccountStore(path).by_username("reader")
    audits = AuditStore(path)
    audits.start("private-trace", account, "conversation_turn", "question", {}, {},
                 conversation_id="conversation-private", turn_id="turn-private")
    audits.event("private-trace", "agent_decision", {"action": "RESEARCH"})
    audits.finish("private-trace", "completed", {"answer_status": "SUPPORTED"})
    headers = sign_in(client, "reader", "reader-password-123")

    assert client.get("/admin/audits", headers=headers).status_code == 403
    assert client.get("/admin/audits/private-trace", headers=headers).status_code == 403


def _published_evaluation(root, run_id="eval-2026-09-30"):
    from evaluation.benchmark import stable_checksum
    from evaluation.reporting import render_markdown

    run_dir = root / run_id
    (run_dir / "queries").mkdir(parents=True)
    report = {
        "run_id": run_id,
        "benchmark_checksum": "a" * 64,
        "corpus_checksum": "b" * 64,
        "configuration_checksum": "c" * 64,
        "variants": ["dense_only", "hybrid", "reranked", "agentic"],
        "query_count": 1,
        "metrics": {
            "dense_only.recall@10": {"status": "completed", "value": 0.75, "reason": None},
            "hybrid.ragas.faithfulness": {"status": "not_run", "value": None, "reason": "provider unavailable"},
            "agentic.ragas.context_precision": {"status": "failed", "value": None, "reason": "provider failed"},
        },
        "latency": {"dense_only": {"count": 1, "median": 12.0}},
        "failure_categories": {"retrieval_miss": 1},
        "robustness": {"dense_only": {"status": "completed", "value": {"scenarios": {"noisy_query": {"mean_metric_deltas": {"recall@10": -0.1, "query_context_coverage": -0.2, "context_precision": -0.1, "candidate_filter_compliance": -0.3}}}}, "reason": None, "queries": {}}},
        "limitations": ["optional metric fixture"],
        "prompts": "must not be returned",
        "model_output": "must not be returned",
        "api_key": "must not be returned",
        "hidden_trace": {"secret": True},
    }
    query = {"query_id": "q1", "variants": {"dense_only": {"diagnostics": [{"category": "retriever_miss", "evidence": "hidden"}], "metrics": {"query_context_coverage": 0.6, "context_precision": 0.7, "candidate_filter_compliance": 0.8}, "robustness": {"status": "completed", "scenarios": {"noisy_query": {"metric_deltas": {"recall@10": -0.1, "query_context_coverage": -0.2, "context_precision": -0.1, "candidate_filter_compliance": -0.3}}}, "raw_output": "hidden"}}}}
    report_bytes = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    query_bytes = (json.dumps(query, sort_keys=True, indent=2) + "\n").encode()
    markdown_bytes = render_markdown(report).encode()
    checksums = {
        "report.json": hashlib.sha256(report_bytes).hexdigest(),
        "report.md": hashlib.sha256(markdown_bytes).hexdigest(),
        "queries": {"q1.json": hashlib.sha256(query_bytes).hexdigest()},
    }
    (run_dir / "report.json").write_bytes(report_bytes)
    (run_dir / "report.md").write_bytes(markdown_bytes)
    (run_dir / "queries" / "q1.json").write_bytes(query_bytes)
    (run_dir / "checksums.json").write_text(json.dumps(checksums), encoding="utf-8")
    manifest = {"latest_run_id": run_id, "runs": [{"run_id": run_id, "report_checksum": checksums["report.json"], "checksums_checksum": stable_checksum(checksums)}]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


def test_evaluations_require_admin_and_list_only_promoted_reports(client, tmp_path):
    from backend.app.core.config import get_settings

    root = tmp_path / "evaluation-reports"
    run_dir = _published_evaluation(root)
    (root / "partial-run").mkdir()
    original_files = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert client.get("/admin/evaluations").status_code == 401
    reader = sign_in(client, "reader", "reader-password-123")
    assert client.get("/admin/evaluations", headers=reader).status_code == 403
    assert client.get("/admin/evaluations/eval-2026-09-30", headers=reader).status_code == 403
    admin = sign_in(client, "admin", "admin-password-123")
    response = client.get("/admin/evaluations", headers=admin)
    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["items"]] == ["eval-2026-09-30"]
    detail = client.get("/admin/evaluations/eval-2026-09-30", headers=admin)
    assert detail.status_code == 200
    body = detail.json()
    assert body["report_checksum"] == hashlib.sha256((run_dir / "report.json").read_bytes()).hexdigest()
    assert body["benchmark_checksum"] == "a" * 64
    assert "prompts" not in body and "model_output" not in body and "api_key" not in body and "hidden_trace" not in body
    assert body["queries"][0]["variants"]["dense_only"]["diagnostics"] == [{"category": "retriever_miss"}]
    assert body["robustness"]["dense_only"]["value"]["scenarios"]["noisy_query"] == {
        "query_context_coverage": -0.2, "context_precision": -0.1, "candidate_filter_compliance": -0.3,
    }
    assert body["queries"][0]["variants"]["dense_only"]["metrics"] == {
        "query_context_coverage": 0.6, "context_precision": 0.7, "candidate_filter_compliance": 0.8,
    }
    assert body["queries"][0]["variants"]["dense_only"]["robustness"]["scenarios"]["noisy_query"] == {
        "query_context_coverage": -0.2, "context_precision": -0.1, "candidate_filter_compliance": -0.3,
    }
    assert "evidence" not in str(body) and "raw_output" not in str(body)
    assert get_settings().EVALUATION_REPORTS_DIR == str(root)
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()} == original_files


@pytest.mark.parametrize("run_id", ["../secret", "..", "a/b", "a\\b", ".hidden", "C:\\secret"])
def test_evaluation_detail_rejects_unsafe_run_ids(client, run_id):
    admin = sign_in(client, "admin", "admin-password-123")
    response = client.get("/admin/evaluations/" + run_id, headers=admin)
    assert response.status_code in {400, 404}
    assert "C:\\" not in response.text


def test_evaluation_detail_fails_closed_on_checksum_mismatch_and_missing_report(client, tmp_path):
    root = tmp_path / "evaluation-reports"
    run_dir = _published_evaluation(root)
    admin = sign_in(client, "admin", "admin-password-123")
    before = (run_dir / "report.json").read_bytes()
    (run_dir / "report.json").write_text('{"run_id":"eval-2026-09-30","secret":"must-not-leak"}', encoding="utf-8")
    corrupt = client.get("/admin/evaluations/eval-2026-09-30", headers=admin)
    assert corrupt.status_code in {500, 503}
    assert "secret" not in corrupt.text and str(tmp_path) not in corrupt.text
    (run_dir / "report.json").write_bytes(before)
    (run_dir / "report.json").write_bytes(b"{malformed report json")
    malformed = client.get("/admin/evaluations/eval-2026-09-30", headers=admin)
    assert malformed.status_code == 503
    assert str(tmp_path) not in malformed.text and "malformed report json" not in malformed.text
    (run_dir / "report.json").write_bytes(before)
    missing = client.get("/admin/evaluations/missing-run", headers=admin)
    assert missing.status_code == 404


def test_evaluation_report_directory_symlink_cannot_escape_root(client, tmp_path):
    root = tmp_path / "evaluation-reports"
    root.mkdir()
    outside = tmp_path / "outside"
    _published_evaluation(outside)
    try:
        (root / "linked-run").symlink_to(outside / "eval-2026-09-30", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    from evaluation.benchmark import stable_checksum
    external_manifest = json.loads((outside / "manifest.json").read_text(encoding="utf-8"))
    external_entry = external_manifest["runs"][0]
    checksums = json.loads((outside / "eval-2026-09-30" / "checksums.json").read_text(encoding="utf-8"))
    (root / "manifest.json").write_text(json.dumps({"latest_run_id": "linked-run", "runs": [{"run_id": "linked-run", "report_checksum": external_entry["report_checksum"], "checksums_checksum": stable_checksum(checksums)}]}), encoding="utf-8")
    admin = sign_in(client, "admin", "admin-password-123")
    response = client.get("/admin/evaluations/linked-run", headers=admin)
    assert response.status_code in {404, 500, 503}
    assert str(outside) not in response.text
