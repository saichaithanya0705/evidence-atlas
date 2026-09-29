# Accounts, Admin Workspaces, and Persistent Audits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver named user/admin accounts, separate responsive workspaces, admin-only advanced controls, and SQLite-backed query audits and traces on the completed corpus.

**Architecture:** FastAPI owns session authentication, authorization, and a small SQLite repository. Each query gets a durable run ID and trace snapshot. React owns page routing and role-specific screens; existing research components are reused. Startup runs against existing indexes and checks a supported Node/npm installation before attempting frontend launch.

**Tech Stack:** Python 3.11, FastAPI, sqlite3, argon2-cffi, React 18, Vite, Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-accounts-admin-audits-design.md`

## Global Constraints

- Admin-created accounts only. First admin is created through a hidden-prompt local CLI.
- SQLite is `data/app/evidence_atlas.sqlite3` by default and never stores vector data.
- Sessions are opaque, HttpOnly, SameSite=Lax, 12-hour cookies; state changes use CSRF and Origin checks.
- Users get question-only research. Year, study type, and retrieval budget are admin-only at API and UI.
- Store success and partial failure traces across restarts. Never claim an unrecorded success.
- Keep the 29,994-record corpus and all index artifacts. No routine rebuild on app startup.
- Frontend runtime remains Node 20.19+ or 22.12+.

## Review Focus

- A signed-out request or retired shared key cannot query or view an audit; verify in Task 2 tests.
- A user who crafts advanced-control JSON is rejected and logged; verify in Task 3 tests.
- A process interruption leaves a recoverable partial audit; verify in Task 3 tests.
- One user cannot infer another user's query through a public API response; verify in Task 4 tests.
- Admin sign-out during an in-flight query cannot revive the admin UI; verify in Task 5 browser tests.

---

### Task 1: SQLite Repository and Account Schema

**Files:** Create `backend/app/storage/database.py`, `backend/app/storage/accounts.py`, `backend/app/storage/audits.py`; modify `.gitignore`, `backend/app/core/config.py`, `requirements.txt`; test `tests/unit/test_app_storage.py`.

**Interfaces:** `connect_db(path)`, `initialize_db(path)`, `AccountStore(path)` with create/get/update/password methods, `AuditStore(path)` with create/event/finish/list/detail/aggregate/recover methods.

- [ ] Write tests for migration idempotence, unique normalized usernames, session/account foreign keys, bounded audit listing, and persistence after reopening the database.
- [ ] Run `pytest tests/unit/test_app_storage.py -q` and see the missing-interface failure.
- [ ] Implement the schema and repository with versioned migrations, parameterized SQL, WAL, busy timeout, and local database Git exclusions.
- [ ] Run the storage tests to green and check the schema against the spec.
- [ ] Commit Task 1 files only.

### Task 2: Authentication and Account Management

**Files:** Create `backend/app/auth/security.py`, `backend/app/auth/routes.py`, `scripts/manage_accounts.py`; modify `backend/app/main.py`; test `tests/unit/test_account_auth.py`.

**Interfaces:** `get_current_account(request)`, `require_admin(request)`, `require_csrf(request)`, `/auth/login|logout|me|password`, `/admin/accounts`, and `manage_accounts.py bootstrap-admin`.

- [ ] Write API tests for bootstrap, login, logout, expiry, password change/reset, deactivation, last-admin protection, CSRF/Origin failures, rate limits, and shared-key rejection.
- [ ] Run the focused tests to verify failure.
- [ ] Implement Argon2id password hashes, hashed session tokens, cookies, account APIs, account events, and hidden-prompt bootstrap.
- [ ] Run focused tests and verify no secret appears in API responses or audit records.
- [ ] Commit Task 2 files only.

### Task 3: Query Authorization and Durable Trace Lifecycle

**Files:** Modify `backend/app/main.py`, `backend/app/workflow/service.py`, `backend/app/models/request_response.py`; extend `backend/app/storage/audits.py`; test `tests/unit/test_query_audits.py` and update superseded `tests/unit/test_admin_boundary.py`.

**Interfaces:** `/research`, `/search`, `/analyze-query` create one run per accepted authenticated request, admin controls checked on server, workflow receives run ID and event sink, `/trace/{id}` reads SQLite.

- [ ] Write tests for user-only question acceptance, forged advanced controls, success/failure/empty/partial traces, interrupted-run recovery, storage failure, account attribution, and restart retrieval.
- [ ] Run focused tests to verify failure.
- [ ] Integrate the audit repository at API boundary and workflow transitions; commit before success responses and sanitize errors.
- [ ] Run focused tests and ensure stored history survives service recreation.
- [ ] Commit Task 3 files only.

### Task 4: Admin Audit, Observability, and Account APIs

**Files:** Create `backend/app/admin/routes.py`; modify `backend/app/main.py`; test `tests/unit/test_admin_views.py`.

**Interfaces:** `/admin/audits`, `/admin/audits/{id}`, `/admin/observability`, `/admin/accounts`; public `/health` remains coarse.

- [ ] Write tests for pagination/filter combinations, trace detail, account access boundaries, persisted aggregates, and no public leakage.
- [ ] Run tests to verify failure.
- [ ] Implement read routes and account-management actions with bounded response sizes.
- [ ] Run tests and reconcile any old endpoint assumptions explicitly.
- [ ] Commit Task 4 files only.

### Task 5: Role-Specific React Pages

**Files:** Replace `frontend/src/App.jsx`, `frontend/src/api.js`; create `frontend/src/auth/SessionProvider.jsx`, `frontend/src/pages/LoginPage.jsx`, `UserResearchPage.jsx`, `AdminResearchPage.jsx`, `AdminAuditsPage.jsx`, `AdminAuditDetailPage.jsx`, `AdminObservabilityPage.jsx`, `AdminAccountsPage.jsx`, `PasswordPage.jsx`; modify `frontend/src/components/SearchBar.jsx`, `frontend/src/editorial.css`, `frontend/vite.config.js`; test `frontend/tests/ui-accounts.mjs`.

**Interfaces:** cookie/CSRF API client, session-gated routes, question-only user composer, admin navigation and controls, audit links/detail pages.

- [ ] Write browser tests using synthetic API fixtures for role gating, account login, user/admin nav, advanced controls, audit detail and account actions at 320/390/768/1440px.
- [ ] Run the browser tests to verify failure.
- [ ] Build separate pages using the existing visual system, move diagnostics to audit detail, and switch API calls to same-origin `/api`.
- [ ] Run browser tests, `npm run build`, and inspect desktop/mobile screenshots.
- [ ] Commit Task 5 files only.

### Task 6: Startup and End-to-End Verification

**Files:** Modify `start.bat`, `scripts/setup_project.py`, `README.md`, `TEST_READY.md`; test `tests/unit/test_setup_and_evaluation.py` and new startup preflight tests.

**Interfaces:** version-aware Node/npm discovery; run-existing-assets startup; explicit administrator provisioning.

- [ ] Write tests for missing/old Node, npm path, existing valid index, port conflict, child cleanup, and no implicit reindex.
- [ ] Run tests to verify failure.
- [ ] Implement startup preflight and docs without replacing the completed corpus or existing secrets.
- [ ] Run relevant unit suite, frontend build/browser checks, and a bounded completed-index smoke test when runtime allows; report live-provider tests separately.
- [ ] Commit Task 6 files only and review total diff for unrelated changes.
