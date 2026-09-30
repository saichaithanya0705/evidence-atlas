# Task 10: Research explainability integration

## Result

The conversation workflow now mounts the public interpretation, qualitative evidence table, and unranked source list. Ordinary users see the canonical question, PICO and MeSH concepts, search approach, planned subquestions, qualitative coverage, exact supporting spans, and qualitative retrieval channel labels. The public views do not render confidence, routing reasoning, numeric retrieval ranks or scores, evaluation metrics, graph paths, or trace controls.

Administrators get a collapsed AuditTrail for each completed turn. It requests `/trace/{request_id}` only when expanded. For restored conversation history, a separate administrator response model provides the linked request ID; the public detail model and ordinary response omit it. The evidence workspace continues to own source navigation, with one tab per normalized PMID and focus on the selected supporting span.

## TDD evidence

- Browser fixtures were extended before production edits with sanitized interpretation, coverage, exact spans, qualitative channels, contaminated top-level diagnostic sentinels, and a trace-request recorder.
- RED: `npm run test:ui-conversations` failed because the live conversation did not render the fixture's canonical interpretation.
- RED: the restored-history service regression failed with `KeyError: 'request_id'` for an administrator detail response.
- GREEN: after integration, conversation UI and the restored-history regression passed. The browser test also verifies that users see no trace control and make no trace request; administrators make no request while collapsed, then request the correct run ID on explicit expansion, including after history reload.

## Verification

- `npm run test:ui-conversations` - PASS, including same-PMID tab reuse and exact active-span focus.
- `npm run test:ui-accounts` - PASS for user and administrator at 1440, 768, 390, and 320 pixels.
- `npm run build` - PASS.
- Focused auth/conversation backend tests — 64 passed; the added restored-history route test also passed independently.
- Full backend suite — 1100 passed, 2 skipped.
- `git diff --check` - PASS.

## Self-review and concerns

- Public interpretation and evidence rendering consume only the public projection fields. The conversation no longer uses `RankedPapers`, whose ordinal markers would expose numeric ranks; its replacement preserves clickable source selection without ranking labels.
- Audit data is loaded through the administrator-only trace endpoint after explicit expansion. Restored history gets its request ID only through the administrator-specific detail projection; `ConversationTurnRecord` remains free of this field.
- Existing evidence tabs, conversation switching, account navigation, authentication, and responsive layouts remained covered by the UI suites.
- The installed Node.js is 20.18.0 while Vite requests 20.19+ or 22.12+. The build completed successfully with that engine warning. The backend suite emitted existing FastAPI lifecycle and local Qdrant warnings.
- The commit hash is supplied in the completion handoff because a commit cannot contain its own final content hash without changing that hash.

## Review follow-up: immediate turn response and export boundary

The review found that newly submitted ordinary turns still received `request_id` in the shared response model, and the JSON export helper emitted request/audit keys even when passed ordinary-user state. The public `ConversationTurnResponse` now excludes the identifier; `AdminConversationTurnResponse` adds it only for administrators. The turn route selects explicit role-specific serialization, while the service continues retaining the audit link in storage for the admin-only restored-history projection. Ordinary JSON export now uses a dedicated public allowlist, so stale request IDs, trace URLs, and traces are not copied into the file. Administrator trace fetching remains collapsed/lazy.

OpenAPI documents both the public and administrator variants for GET detail and POST turns using schema-only unions; runtime behavior does not serialize through a union. Regression tests assert ordinary POST omits and admin POST includes `request_id`, both paths appear in the documented schemas, and the browser fixture's ordinary export omits both `request_id` and `audit_trace` despite the response fixture containing a request ID.

### Follow-up TDD and verification

- RED: focused route tests first failed because ordinary POST included `request_id` and GET detail OpenAPI referenced only `ConversationDetailResponse`.
- GREEN: focused auth/conversation tests passed (27 passed); conversation UI passed with export-ID assertions; accounts UI passed across user/admin viewports; build passed.
- `npm run test:ui-conversations` - PASS, including ordinary export checks with stale request ID in the API fixture.
- `npm run test:ui-accounts` - PASS for user and administrator at 1440, 768, 390, and 320 pixels.
- `npm run build` - PASS.
- Focused auth/conversation backend tests - 27 passed.
- Full backend suite - 1103 passed, 2 skipped, 9 warnings.
- `git diff --check` - PASS.
- Environment concern: Node.js 20.18.0 is below Vite's stated 20.19+ requirement; tests and build completed successfully with an engine warning.
