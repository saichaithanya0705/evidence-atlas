import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const target = process.env.UI_TEST_URL || 'http://127.0.0.1:5174';
const failures = [];
const screenshotDir = process.env.UI_SCREENSHOT_DIR;
if (screenshotDir) mkdirSync(screenshotDir, { recursive: true });

async function scenario(role, width) {
  const context = await browser.newContext({ viewport: { width, height: 900 } });
  let session = null;
  let researchBody = null;
  let createdAccount = null;
  let lastAuditParams = null;
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON?.() || {};
    let status = 200;
    let data = {};
    if (url.pathname === '/api/auth/me') { if (!session) status = 401; else data = { account: session }; }
    else if (url.pathname === '/api/auth/login') { session = { id: role, username: body.username, display_name: role, role, active: 1, must_change_password: 0 }; data = { account: session }; }
    else if (url.pathname === '/api/health') data = { status: 'healthy', service: 'Evidence Atlas' };
    else if (url.pathname === '/api/research') { if (body.query === 'expire session') { session = null; status = 401; data = { detail: 'Sign in to continue' }; } else { researchBody = body; data = { request_id: 'sample-run', query: body.query, synthesis: 'VISUAL TEST DATA [PMID: 12345].', cited_pmids: ['12345'], retrieved_papers: [{ pmid: '12345', title: 'Illustrative research record', abstract: 'Visual test fixture, not clinical evidence.', authors: ['Example'], year: 2024, study_type: 'Review' }], evidence_table: [] }; } }
    else if (url.pathname === '/api/paper/12345') data = { pmid: '12345', title: 'Illustrative research record', abstract: 'Visual test fixture, not clinical evidence.', authors: ['Example'], year: 2024, study_type: 'Review' };
    else if (url.pathname === '/api/admin/audits') { lastAuditParams = url.searchParams; data = { total: 1, items: [{ id: 'sample-run', username: 'sample-user', query: 'kidney outcomes', operation: 'research', status: 'completed', started_at: '2026-09-28T19:00:00Z', duration_ms: 130 }] }; }
    else if (url.pathname === '/api/admin/audits/sample-run') data = { id: 'sample-run', username: 'sample-user', query: 'kidney outcomes', status: 'completed', operation: 'research', started_at: '2026-09-28T19:00:00Z', response: { synthesis: 'VISUAL TEST DATA [PMID: 12345].', retrieved_papers: [], evidence_table: [] }, trace: { query_plan: { original_query: 'kidney outcomes', canonical_query: 'kidney outcomes', route: 'SIMPLE' }, stages: [{ stage: 'retrieve', status: 'completed' }], citation_audit: { valid: true }, timings_ms: { total: 130 } }, events: [{ stage: 'retrieve', payload: { status: 'completed' } }] };
    else if (url.pathname === '/api/admin/observability') data = { total_queries: 1, by_status: { completed: 1 }, by_operation: { research: 1 }, average_duration_ms: 130, p95_duration_ms: 130 };
    else if (url.pathname === '/api/admin/accounts') { if (request.method() === 'POST') { createdAccount = body; data = { id: 'new-account', ...body }; } else { const offset = Number(url.searchParams.get('offset') || 0); const limit = Number(url.searchParams.get('limit') || 50); const accounts = Array.from({ length: 26 }, (_, index) => ({ ...session, id: `account-${index}`, username: index === 25 ? 'last-page-reader' : `reader-${index}`, display_name: index === 25 ? 'Last Page Reader' : `Reader ${index}` })); data = { total: accounts.length, items: accounts.slice(offset, offset + limit) }; } }
    else if (url.pathname === '/api/auth/password') { session = null; data = { password_changed: true, sign_in_again: true }; }
    else if (url.pathname === '/api/auth/logout') { session = null; data = { signed_out: true }; }
    else throw Error(`Unexpected API request ${request.url()}`);
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  try {
    await page.goto(`${target}/login`);
    await page.getByLabel('Username').fill(role === 'admin' ? 'administrator' : 'sample-user');
    await page.getByLabel('Password').fill('not-a-real-password');
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByRole('heading', { name: /Medical evidence/i }).waitFor();
    if (role === 'admin' && width === 1440) {
      const rail = await page.getByRole('navigation', { name: 'Administrator' }).boundingBox();
      const workspace = await page.locator('.admin-research').boundingBox();
      assert.ok(rail.x < workspace.x && rail.height > 300, 'The admin workspace should have a desktop side rail');
    }
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/${role}-${width}.png`, fullPage: true });
    if (role === 'user') {
      assert.equal(await page.getByText('Advanced filters').count(), 0);
      assert.equal(await page.getByText('Administrators can review your research questions and query traces.').count(), 1);
      assert.equal(await page.getByLabel('Publication year from').count(), 0);
      assert.equal(await page.getByText('Audit logs').count(), 0);
      await page.goto(`${target}/admin/audits`);
      await page.waitForURL('**/research');
      assert.equal(await page.getByRole('link', { name: 'Audit logs' }).count(), 0);
    } else {
      await page.getByLabel('Publication year from').selectOption('2020');
      await page.getByRole('link', { name: 'Audit logs' }).click();
      await page.getByText('kidney outcomes').waitFor();
      await page.getByLabel('From date').fill('2026-09-28');
      await page.getByLabel('To date').fill('2026-09-28');
      await page.getByRole('button', { name: 'Apply filters' }).click();
      await page.getByText('130 ms').waitFor();
      assert.equal(lastAuditParams.get('from_date'), '2026-09-28');
      assert.equal(lastAuditParams.get('to_date'), '2026-09-29');
      await page.getByRole('link', { name: 'View trace' }).click();
      await page.getByText('Citation validation').waitFor();
      if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/audit-${width}.png`, fullPage: true });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.getByRole('link', { name: 'Observability' }).click();
      await page.getByRole('heading', { name: 'System observability' }).waitFor();
      await page.getByRole('link', { name: 'Accounts' }).click();
      await page.getByRole('heading', { name: 'Accounts' }).waitFor();
      await page.getByRole('button', { name: 'Next' }).click();
      await page.getByText('Last Page Reader').waitFor();
      await page.getByRole('button', { name: 'Previous' }).click();
      await page.getByLabel('Username').fill('new-reader');
      await page.getByLabel('Display name').fill('New Reader');
      await page.getByLabel('Temporary password').fill('temporary-secret-123');
      await page.getByRole('button', { name: 'Create account' }).click();
      await page.getByText('Account created.').waitFor();
      assert.equal(createdAccount.username, 'new-reader');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.getByRole('link', { name: 'Research' }).click();
    }
    await page.getByLabel('Research question').fill('kidney outcomes');
    await page.getByRole('button', { name: 'Research', exact: true }).click();
    await page.getByText('VISUAL TEST DATA', { exact: false }).waitFor();
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/results-${role}-${width}.png`, fullPage: true });
    assert.equal(researchBody.query, 'kidney outcomes');
    assert.equal(role === 'user' ? Object.keys(researchBody).length : researchBody.year_min, role === 'user' ? 1 : 2020);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.getByRole('link', { name: 'Change password' }).click();
    await page.getByRole('heading', { name: 'Set your password' }).waitFor();
    assert.equal(await page.getByText('Your administrator issued a temporary password.').count(), 0);
    await page.getByLabel('Current password').fill('not-a-real-password');
    await page.getByLabel('New password').fill('a-new-test-password-123');
    await page.getByRole('button', { name: 'Change password' }).click();
    await page.getByRole('heading', { name: 'Welcome back.' }).waitFor();
    if (role === 'user') {
      await page.getByLabel('Username').fill('sample-user');
      await page.getByLabel('Password').fill('a-new-test-password-123');
      await page.getByRole('button', { name: 'Sign in' }).click();
      await page.getByLabel('Research question').fill('expire session');
      await page.getByRole('button', { name: 'Research', exact: true }).click();
      await page.getByRole('heading', { name: 'Welcome back.' }).waitFor();
    }
    assert.deepEqual(errors, []);
    console.log('PASS', role, width);
  } catch (error) { failures.push(`${role} ${width}: ${error.message}`); console.error('FAIL', role, width, error.message); }
  finally { await context.close(); }
}

for (const role of ['user', 'admin']) for (const width of [1440, 768, 390, 320]) await scenario(role, width);
await browser.close();
if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
