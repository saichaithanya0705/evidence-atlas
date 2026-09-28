# Evidence Atlas: accounts, separate workspaces, and persistent audits

Status: proposed written design for user review; not an implementation-completion report.

## 1. Agreed outcome

The user approved the current visual direction and requested distinct user and admin experiences, SQLite-backed accounts, administrator-created accounts only, administrator-only advanced filters, and durable audits of queries from every account. An administrator must be able to open an audit entry and inspect that query's trace on a separate page. Explainability and observability must not be crowded into the research screen.

The implementation must preserve the completed 29,994-record corpus and indexes, preserve existing unrelated work, and make local startup reliable. No public registration, cloud database, or external identity provider is needed for this version.

## 2. Current implementation and gaps

- React/Vite has one application view and a shared administrator-key dialog. Both roles share the research screen; diagnostics are currently collapsed within it.
- FastAPI authorizes diagnostics with `X-Admin-Key`; ordinary queries do not require a named account.
- `ResearchService` stores successful traces in an in-memory, bounded `OrderedDict`. It has no durable per-account audit repository and does not persist failed-query partial traces.
- `TelemetryStore` holds counters and latency samples in memory.
- The current index build completed successfully. Subsequent service startup failed because the launcher could not find npm. Installed Node 20.18.0 is also below the frontend's declared runtime requirement.

## 3. Architecture choice

Use the existing FastAPI service and React application, adding a local SQLite application database and server-side account sessions. Keep corpus artifacts and Qdrant separate from application-account storage.

Alternatives considered:

1. Keep the shared admin key and only split screens: smallest change, but cannot reliably attribute queries to accounts or satisfy account management. Rejected.
2. SQLite accounts, opaque sessions, and durable audits in the existing service: selected; meets the local-project scope without extra infrastructure.
3. External authentication/database service: useful for a later multi-instance deployment, but unnecessary for this requested SQLite version.

The local service is a single backend process. SQLite connections are short-lived or request-scoped, use parameterized SQL, foreign keys, a busy timeout, and WAL mode. Never hold a database transaction open while running retrieval or an LLM. Versioned schema migrations run at startup without deleting existing data. SQLite is not the vector database.

## 4. Identity and access

- Roles are `user` and `admin`; every query requires a valid account session.
- Login uses a normalized, unique username and password. Public registration is absent from both API and UI.
- Passwords are hashed using a maintained Argon2id implementation; passwords and password hashes are never returned in account/audit responses or written into logs.
- The first administrator is provisioned by an explicit local CLI command with a hidden password prompt. No default password and no automatic promotion of the first web visitor. Additional accounts are created through the admin Accounts page.
- Admins can create accounts, deactivate/reactivate them, and issue a temporary password reset. Temporary credentials require a password change before research or other privileged actions. Password change/reset and deactivation revoke existing sessions. Prevent deactivation/demotion of the last active admin.
- Sessions use random opaque tokens in HttpOnly, SameSite=Lax cookies. Only token hashes are stored in SQLite. Sessions expire after 12 hours, rotate on login, and are revoked on logout. Production HTTPS requires Secure cookies; local HTTP is explicitly development-only.
- State-changing endpoints require an allowed Origin and a session-bound CSRF token. Login also enforces an allowed Origin. Add bounded login throttling with generic invalid-credential responses.
- The frontend uses same-origin `/api` requests via the Vite development proxy. This avoids storing credentials in browser local/session storage. Production proxying is documented; cross-origin configuration is not silently enabled.
- The shared `ADMIN_API_KEY` browser workflow is retired. Keeping it as an alternative privilege bypass would undermine account-attributed auditing, so it no longer grants account/admin access. Existing deployment configuration is not deleted blindly.
- Backend authorization checks protect every admin endpoint. A hidden button, client route guard, or submitted role is never an authorization decision.

## 5. Separate interfaces

Shared design tokens preserve the approved cream, teal, navy, readable typography, responsive spacing, and keyboard-accessible paper reader. Separate page components own each experience; avoid expanding the existing monolithic App into a multi-page conditional tree.

| Route | Audience | Purpose |
|---|---|---|
| `/login` | Signed-out visitors | Branded sign-in; no registration link |
| `/account/password` | Signed-in accounts | Password change, including required first-login change |
| `/research` | Users | Focused question composer, readable synthesis, citations, and source abstracts |
| `/admin/research` | Admins | Approved editorial research workspace with advanced controls |
| `/admin/audits` | Admins | Paginated query history across all accounts |
| `/admin/audits/:id` | Admins | Dedicated explainability and trace detail for one query |
| `/admin/observability` | Admins | Request outcomes, latencies, and actual service/index status |
| `/admin/accounts` | Admins | Create and manage accounts |

Users have a quiet header and account menu, not an admin sidebar/dashboard. Their research page contains no publication-year selector, study-type selector, corrective-retrieval budget, ranking-score diagnostics, trace export, or observability controls. They see a plain-language notice that queries are retained and can be reviewed by administrators, plus the existing research-use disclaimer.

Admins have a persistent navigation sidebar on desktop and accessible compact navigation on mobile. Research remains its own workspace; query interpretation, evidence spans, provenance, and execution timelines move to the audit-detail page. A completed admin research run links to its audit entry. The admin paper reader may link to the corresponding trace, but does not duplicate the entire diagnostics page.

The audit list supports account, date range, status, and query-text filters. Each row includes account, timestamp, query, operation, status, and duration. The detail page shows normalized interpretation/PICO, applied controls, retrieval attempts, returned sources/ranking evidence, synthesis/citation checks, stage timings, and sanitized failures where available. Missing stages are labeled unavailable, never invented.

Observability aggregates durable query records for a chosen time range. It distinguishes research, search, and standalone analysis operations so a single user question is not silently counted twice. Show query counts, outcomes, average/p95 latency, and readiness indicators supported by real measurements. In-flight counts are live process state; historical totals survive restart. Filesystem presence alone is not labeled a proven live Qdrant connection.

## 6. SQLite model

Default application database: `data/app/evidence_atlas.sqlite3`, configurable independently of corpus/index paths. Database files, WAL/SHM files, backups, and credential artifacts are excluded from Git.

| Table | Key data |
|---|---|
| `schema_migrations` | Applied schema versions and timestamps |
| `accounts` | Stable ID, normalized username, display name, role, password hash, active flag, required-password-change flag, creator, timestamps |
| `sessions` | Token hash, account ID, CSRF-token hash, creation/expiry timestamps |
| `query_runs` | Stable run ID, account ID, username/role snapshot, operation, original query, requested/applied controls, status, start/end times, duration, sanitized error, result summary |
| `query_events` | Run ID, monotonically increasing sequence, stage/type, timestamp, duration, versioned structured event payload |
| `query_results` | Run ID, versioned final response/trace snapshot for reproducible admin inspection |
| `account_events` | Actor, action, affected account, timestamp; never passwords or tokens |

Use indexes on run timestamp, account/timestamp, status/timestamp, and event run/sequence. Account deactivation preserves audit ownership. Do not hard-delete accounts or automatically expire audit records in this version. Document database growth and a safe SQLite backup procedure; retention controls can be added separately.

The database contains sensitive query content but is not encrypted by SQLite by default. Document local filesystem access controls and the instruction not to enter patient-identifying information. Do not claim this prototype is suitable for regulated clinical deployment.

## 7. Durable query lifecycle

1. Authenticate the session and resolve the account on the server.
2. For each authenticated submission to `/research`, `/search`, or `/analyze-query`, create an audit run before invoking the workflow. Include rejected control requests and validation failures, with bounded captured input. Unauthenticated attempts are security events, not falsely attributed account queries.
3. Enforce role-specific controls. Users may submit only their question; non-default admin-only controls are rejected with a clear forbidden response, not silently honored. The server supplies the standard retrieval budget. Admins retain the existing validated year, study type, and retrieval controls.
4. Assign one run ID at the API boundary and pass it through the workflow. Replace reliance on the bounded in-memory trace cache with a repository/event-sink interface. Record stage starts/completions, retrieval decisions, evidence, citation audits, and timings as the workflow progresses.
5. Persist the final result/trace and terminal status before reporting successful completion. Admin inspection must not need to rerun the query or load the retrieval models.
6. On validation, authorization, retrieval, or synthesis failure, preserve the run and all available partial events with a sanitized error and terminal failure/rejection status. Never fabricate a complete trace for a failed or rejected request.
7. On process restart, unfinished runs from the previous process are marked interrupted, not left permanently running. This recovery rule assumes the single-backend-process deployment above.

Audit-storage failure is fail-closed: reject new research with a clear service-unavailable response if the initial audit cannot be committed. If later persistence fails, stop subsequent stages where possible and do not report a falsely audited success. An LLM call already in progress cannot be retroactively canceled; record/recover the incomplete run when storage becomes available.

Trace payloads contain application evidence and recorded workflow decisions, not hidden model chain-of-thought. Persist allowlisted structured fields; exclude tokens, credentials, full environment dumps, and raw unredacted provider exceptions. Bound input/event sizes without silently truncating the actual accepted query; oversized input is rejected explicitly.

Repeated submissions are separate audit runs. Reloading an audit page never creates a new run. Disconnecting a browser does not delete the audit; if the existing synchronous workflow continues, its eventual outcome is persisted.

## 8. API boundaries and migration

- `/auth/login`, `/auth/logout`, `/auth/me`, `/auth/password`: account/session lifecycle; no signup endpoint.
- `/admin/accounts`: paginated account listing/creation and targeted status/role/password-reset actions.
- `/admin/audits` and `/admin/audits/{id}`: admin-only audit list/detail, with bounded pagination and safe filters.
- `/admin/observability`: historical aggregate metrics and explicitly separated current readiness.
- Existing research/search/paper routes require an authenticated account. Public health remains coarse and does not expose account information.
- Existing `/trace/{id}` can remain an admin-only alias backed by SQLite for stored traces. `/metrics` remains admin-only and distinguishes durable aggregates from process-local metrics. Legacy key-only verification returns a clear migration response and grants no access.
- Ordinary research responses remain restricted to user-facing results, citations, and an opaque run ID. Admin-only data must not be embedded in the public response and merely hidden with CSS.
- API clients/tests are updated for account sessions; pre-account shared-key behavior is intentionally not preserved as an authentication bypass.
- Previous in-memory traces cannot be reconstructed. Do not import sample fixtures as real audit history or claim pre-migration queries were recorded.

## 9. Startup and operational correctness

- Validate Python/Node/npm availability and supported versions before downloads or index preparation. Discover the configured/local Node executable and its matching npm explicitly instead of assuming PATH is refreshed.
- Keep the frontend's supported runtime requirement; do not downgrade dependencies or ship the temporary preview crypto shim as production infrastructure.
- If a runtime install is blocked by the managed network, report the exact blocker and required supported installation. Do not bypass organizational controls or claim full startup passed.
- Add a clear run-existing-assets path, or equivalent manifest-based skips, so routine application startup does not rebuild the completed knowledge base. Rebuild only when relevant corpus/model/config fingerprints change or explicitly requested.
- Initialize/migrate the account database without opening/rebuilding Qdrant. Provide explicit first-admin provisioning and a documented recovery/reset CLI using hidden password input.
- Startup errors identify the failed stage, preserve all indexes/accounts, and clean up only processes started by that launcher. UI preview, backend, and indexing must not fight over ports or Qdrant locks.
- Do not switch LLM provider/mode or overwrite existing API credentials as part of making the application run. Report whether verification used deterministic/mock synthesis or the configured live provider.

## 10. Acceptance and verification

Automated tests use temporary SQLite databases and controlled workflow/provider doubles where appropriate. Existing corpus and real account data are never test fixtures to overwrite.

Required checks:

1. Bootstrap admin, admin creates user, temporary-password change, login/logout/expiry, deactivation, password reset, last-admin protection, and restart persistence.
2. User cannot call admin APIs, view another account's trace, set privileged filters, select an admin role, or regain privileges through stale UI requests or the retired shared key.
3. CSRF/Origin checks, throttling behavior, password hashing, session-token hashing, generic login errors, and exclusion of secrets from response/audit payloads.
4. Each authenticated query has one durable run: success, empty evidence, forbidden controls, invalid input, provider failure, partial trace, interrupted restart, and storage failure are covered.
5. Admin can filter all-account audits and inspect the correct query trace after application restart; ordinary users cannot access these records.
6. User and admin have genuinely different navigation/research controls. Explainability and observability have separate URLs. Keyboard navigation, focus restoration, loading/error states, and 320/390/768/1440px layouts are verified with synthetic records.
7. Frontend production build and relevant backend/full regression suites run; legacy-contract failures are updated deliberately, not hidden. Any unexecuted live/provider tests are reported separately.
8. Startup preflight has tests for missing npm, old Node, existing indexes, port conflicts, and failed child processes. A small completed-index smoke test verifies real retrieval only when startup/runtime prerequisites are available; it does not trigger ingestion or rebuilds.

Completion means code, migrations, tests, setup documentation, and separate responsive screens are delivered; the local application launches successfully unless a specific external prerequisite remains blocked. Merely rendering fixture data is not proof of real retrieval or provider correctness.

## 11. Out of scope

Public signup, email delivery/password-reset emails, OAuth/SSO, MFA, cloud deployment, multi-worker database coordination, automatic audit deletion, encryption-at-rest management, and a replacement vector store. Existing research algorithms are retained except for instrumentation necessary to record durable traces.

## Review handoff

This design records the approved product direction and explicit implementation assumptions. Review the written design before the detailed implementation plan is produced. The plan will sequence database/auth, durable audit integration, separate frontend pages, startup repairs, and verification; it will not require rebuilding the corpus.
