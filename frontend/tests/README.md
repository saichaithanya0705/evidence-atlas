# Isolated visual checks

Use Node 20.19+ or 22.12+ (as required by Vite). Install the locked frontend dependencies with `npm ci`.

Start the frontend alone on the separate QA port:

```powershell
npm run dev -- --port 5174
```

In another terminal, from `frontend`:

```powershell
npm run test:ui-preview
```

The account-aware preview suite intercepts API requests in Playwright and returns clearly labeled synthetic records. It does not start the backend, open the index, or write corpus data. A normal browser tab does **not** receive these test responses. Tests cover sign-in, user/admin separation, advanced-filter authorization in the UI, query traces, audit date filters, account pagination, password changes, expired sessions, and responsive layouts at 1440, 768, 390, and 320px. `npm run test:ui-accounts` runs the same suite directly. `node tests/vite-config.mjs` checks custom backend port proxying.

Set `UI_TEST_URL` to the Vite origin if it is not `http://127.0.0.1:5174`. To save screenshots outside the repository, set `UI_SCREENSHOT_DIR` to a temporary directory. By default the suite uses installed Chrome at `C:/Program Files/Google/Chrome/Application/chrome.exe`.

`test:ui-stress` is the separate **live-backend** suite and requires `UI_STRESS_USERNAME` and `UI_STRESS_PASSWORD` for an administrator-created ordinary-user account. Optional `UI_STRESS_ADMIN_USERNAME` and `UI_STRESS_ADMIN_PASSWORD` enable administrator-only year-range validation. Do not run it against an index that is still being built. Passing the isolated checks does not validate retrieval quality or real synthesis.
