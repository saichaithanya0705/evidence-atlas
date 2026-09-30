# API contract: research and evaluation visibility

All research endpoints require an authenticated, ready account. Cookie-authenticated state-changing requests also require the same-origin CSRF token.

| Endpoint | Access | Contract |
|---|---|---|
| `GET /health` | Public | Service health and version; does not return evaluation data. |
| `POST /research` | Authenticated user or administrator | Research answer, evidence, citations, and source projection. The ordinary-user projection omits internal scores and trace data. |
| `POST /search` | Authenticated user or administrator | Search candidates. Advanced filters and trace details are administrator-controlled. |
| `POST /analyze-query` | Administrator | Structured query analysis. |
| `GET /trace/{request_id}` | Administrator | Bounded audit trace for a request. |
| `GET /admin/evaluations` | Administrator | List of checksum-valid reports referenced by the promotion manifest. |
| `GET /admin/evaluations/{run_id}` | Administrator | Allowlisted report summary and safe per-query diagnostics. |

Evaluation reads do not run models, score queries, write files, or promote a report. A report is visible only when referenced by the manifest and when report, Markdown, query-artifact, and checksum validation succeeds. Unavailable or corrupt reports fail closed. Evaluation metric statuses are `completed`, `not_run`, or `failed`; non-completed values are null and include a reason.

The administrator evaluation API and dashboard are the only product surfaces for aggregate evaluation metrics and report details. Ordinary-user research views and responses do not expose them.
