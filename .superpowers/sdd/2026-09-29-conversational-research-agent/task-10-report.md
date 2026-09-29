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
