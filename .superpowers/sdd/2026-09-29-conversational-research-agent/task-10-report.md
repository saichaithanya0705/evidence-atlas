# Task 10: Administrator conversation audit traces

## RED

- Added backend projection and boundary assertions for conversation and turn IDs, agent and route summaries, answer status, bounded corrections/gaps/timings, stable event order, forbidden prompt/provider/reasoning fields, and ordinary-user denial.
- The first focused API run failed because the audit list omitted `conversation_id` (expected missing projection).
- The follow-up `/trace` assertion failed because the legacy alias returned stored `query_plan.pico` and router reasoning.
- The mocked admin UI failed because linked IDs and the turn-to-audit link were absent; the phase headings and evidence-gap summary were not rendered.

## GREEN

- `python -m pytest tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py -q`: 15 passed.
- `python -m pytest tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py tests/unit/test_research_pipeline.py::test_failed_synthesis_has_accurate_durable_stage_events -q`: 16 passed.
- From `frontend`, `npm run test:ui-accounts`: all 8 user/admin viewport scenarios passed.
- From `frontend`, `npm run build`: passed. The existing Node 20.18 / Vite minimum-version warning remains.

## Self-review

- Admin list/detail and the admin-only `/trace` alias use explicit allowlisted projections. Stored event order remains stable; nested query plans, raw provider output, prompts, reasoning, and unsanitized errors are not returned. Conversation turns persist only the released response plus allowlisted decision metadata, and ordinary conversation endpoints remain on their existing public projection.
- The UI exposes fixed phase labels, bounded evidence gaps, route/status/correction/duration summaries, and links each admin turn to its existing audit detail. It does not rerun research or offer unindexed conversation/route/status filters.
- Existing audit runs without conversation IDs remain readable with null linked fields.
- Full suite: 946 passed, 1 skipped, 5 failed. Four failures are unrelated Qdrant local-storage tests colliding on the shared storage lock. The fifth exposed an existing workflow-event compatibility expectation; the internal event shape was restored while its admin projection remains allowlisted. The corresponding regression test passes in the focused rerun.
- `git diff --check`: clean.

## Fix Round 1 — nested allowlist values

- Fix commit: `54e9ab9` (`fix: sanitize nested audit projection values`).

### RED

- Added nested injection fixtures under `correction_stopped.reason`, `requested_controls.year_min` / `study_types`, and citation audit `cited_pmids`.
- Command: `.venv\Scripts\python.exe -m pytest tests/unit/test_query_audits.py::test_admin_audit_projects_linked_trace_summaries_and_allowlisted_events -q`
- Result: failed as expected; the response preserved the nested prompt/provider values in the allowed control fields.

### GREEN

- Command: `.venv\Scripts\python.exe -m pytest tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py tests/unit/test_research_pipeline.py::test_failed_synthesis_has_accurate_durable_stage_events -q`
- Result: `16 passed, 4 warnings in 6.30s`.

### Self-review

- Generic projection helpers now accept scalar values only. Controls, event fields, citation summaries, PMIDs, evidence spans, paper lists, and timings each use their expected types and bounds; event enums and correction reasons are validated. Nested dictionaries/lists are either field-specifically sanitized or omitted.
- Legitimate normalized evidence gaps, citation booleans/PMIDs, and finite numeric stage timings continue to project in the passing tests. The workflow event compatibility test also remains green.
- `git diff --check`: clean before commit.

## Fix Round 2 — field-specific evidence scalar types

- Fix commit: `e114a9b` (`fix: validate audit evidence scalar types`).

### RED

- Added valid and malformed evidence/paper records. The malformed records use a string year, boolean text fields, numeric journal, and numeric PMID; valid records verify integer years and string fields remain available.
- Command: `.venv\Scripts\python.exe -m pytest tests/unit/test_query_audits.py::test_admin_audit_projects_linked_trace_summaries_and_allowlisted_events -q`
- Result: failed as expected because a string `year`, boolean `title`, and boolean `population` were returned in the admin projection.

### GREEN

- Command: `.venv\Scripts\python.exe -m pytest tests/unit/test_query_audits.py tests/unit/test_admin_boundary.py tests/unit/test_research_pipeline.py::test_failed_synthesis_has_accurate_durable_stage_events -q`
- Result: `16 passed, 4 warnings in 6.18s`.

### Self-review

- Evidence and paper projections now define expected scalar types per field: PMID is digit-only text, year is an integer bounded to 0–3000, descriptive fields are bounded strings, and author/mesh/span collections are bounded string lists. Invalid fields are omitted while valid data remains.
- The nested injection sanitizers from Fix Round 1 remain intact. `git diff --check` passed before commit.
