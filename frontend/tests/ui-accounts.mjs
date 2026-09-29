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
  let nextConversationId = 1;
  let nextTurnId = 1;
  const conversations = new Map();
  const visualPaper = { pmid: '12345', title: 'Illustrative research record', abstract: 'Visual test fixture, not clinical evidence. This is the complete stored abstract.', authors: ['Example Author', 'Second Author'], journal: 'Visual Journal', year: 2024, study_type: 'Review', mesh_terms: ['Clinical Research', 'Evidence Synthesis'], doi: '10.0000/visual' };
  function createVisualTurn(conversationId, message) {
    const turnId = `visual-turn-${nextTurnId++}`;
    const evidence = { pmid: '12345', title: visualPaper.title, key_findings: `Visual finding for ${message}`, outcome: 'Study outcome', limitations: 'Synthetic fixture limitation', supporting_text_spans: [`Visual supporting span for ${message}`] };
    const result = { conversation_id: conversationId, turn_id: turnId, action: 'RESEARCH', answer_status: 'SUPPORTED', assistant_message: `VISUAL TEST DATA for ${message}. [PMID: 12345]`, cited_pmids: ['12345'], evidence_table: [evidence], retrieved_papers: [visualPaper], evidence_gaps: [], consensus_level: 'consensus', progress_summary: 'Synthetic UI fixture completed.', request_id: `visual-run-${turnId}` };
    const savedTurn = { turn_id: turnId, sequence: conversations.get(conversationId).turns.length + 1, user_message: message, action: result.action, answer_status: result.answer_status, assistant_message: result.assistant_message, created_at: '2026-09-29T12:00:00Z', public_response: { cited_pmids: result.cited_pmids, evidence_table: result.evidence_table, retrieved_papers: result.retrieved_papers, evidence_gaps: result.evidence_gaps, consensus_level: result.consensus_level } };
    conversations.get(conversationId).turns.push(savedTurn);
    return result;
  }
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
    else if (url.pathname === '/api/conversations' && request.method() === 'POST') {
      const id = `visual-conversation-${nextConversationId++}`;
      const conversation = { conversation_id: id, title: 'New conversation', created_at: '2026-09-29T12:00:00Z', updated_at: '2026-09-29T12:00:00Z' };
      conversations.set(id, { conversation, turns: [] }); data = conversation;
    }
    else if (url.pathname === '/api/conversations' && request.method() === 'GET') data = { total: conversations.size, items: [...conversations.values()].map(record => record.conversation) };
    else if (/^\/api\/conversations\/[^/]+\/turns$/.test(url.pathname) && request.method() === 'POST') {
      const conversationId = url.pathname.split('/')[3];
      if (body.message === 'expire session') { session = null; status = 401; data = { detail: 'Sign in to continue' }; }
      else {
        researchBody = body;
        data = createVisualTurn(conversationId, body.message);
        if (conversations.get(conversationId).turns.length === 1) conversations.get(conversationId).conversation.title = body.message.slice(0, 80);
      }
    }
    else if (/^\/api\/conversations\/[^/]+$/.test(url.pathname) && request.method() === 'GET') {
      const id = url.pathname.split('/').pop(); const record = conversations.get(id);
      data = { conversation: record.conversation, turns: record.turns, next_cursor: null };
    }
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
    await page.getByRole('heading', { name: /Research conversations/i }).waitFor();
    assert.equal(await page.locator('.conversation-workspace').count(), 1, 'authenticated research opens the conversation workspace');
    if (role === 'admin' && width === 1440) {
      const rail = await page.getByRole('navigation', { name: 'Administrator' }).boundingBox();
      const workspace = await page.locator('.admin-research').boundingBox();
      assert.ok(rail.x < workspace.x && rail.height > 300, 'The admin workspace should have a desktop side rail');
    }
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/${role}-${width}.png`, fullPage: true });
    if (role === 'user') {
      assert.equal(await page.getByText('Advanced filters').count(), 0);
      assert.equal(await page.getByLabel('Publication year from').count(), 0);
      assert.equal(await page.getByText('Audit logs').count(), 0);
      await page.goto(`${target}/admin/audits`);
      await page.waitForURL('**/research');
      assert.equal(await page.getByRole('link', { name: 'Audit logs' }).count(), 0);
    } else {
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
    if (role === 'admin') {
      await page.getByLabel('Publication year from').selectOption('2020');
      await page.getByLabel('Publication year to').selectOption('2024');
      await page.getByLabel('Study type').selectOption('Review');
      await page.getByLabel('Corrective retrieval attempts').selectOption('4');
    }
    await page.getByLabel('Research message').fill('kidney outcomes');
    await page.getByRole('button', { name: 'Send' }).click();
    await page.getByText('VISUAL TEST DATA', { exact: false }).waitFor();
    await page.locator('.citation-button').last().click();
    await page.getByRole('tab', { name: /Illustrative research record/i }).waitFor();
    assert.equal(await page.getByRole('tab').count(), 2, 'source citation opens one paper tab beside Overview');
    await page.getByRole('tabpanel').getByText('Visual supporting span for kidney outcomes', { exact: true }).waitFor();
    if (screenshotDir) await page.screenshot({ path: `${screenshotDir}/results-${role}-${width}.png`, fullPage: true });
    assert.equal(researchBody.message, 'kidney outcomes');
    assert.equal(role === 'user' ? Object.keys(researchBody).length : researchBody.year_min, role === 'user' ? 1 : 2020);
    if (role === 'admin') {
      assert.equal(researchBody.year_max, 2024);
      assert.deepEqual(researchBody.study_types, ['Review']);
      assert.equal(researchBody.max_loops, 4);
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (width <= 768) await page.getByRole('dialog').getByRole('button', { name: 'Close evidence workspace' }).click();
    else await page.locator('.evidence-toggle').click();
    assert.equal(await page.locator('.evidence-toggle').getAttribute('aria-expanded'), 'false', 'evidence workspace can be collapsed');
    await page.locator('.evidence-toggle').click();
    assert.equal(await page.getByRole('tab').count(), 2, 'reopening the evidence workspace restores its paper tab');
    if (width <= 768) await page.getByRole('dialog').getByRole('button', { name: 'Close evidence workspace' }).click();
    else await page.locator('.evidence-toggle').click();
    await page.reload();
    await page.getByText('VISUAL TEST DATA for kidney outcomes.', { exact: false }).waitFor();
    await page.locator('.citation-button').last().click();
    await page.getByRole('tab', { name: /Illustrative research record/i }).waitFor();
    await page.getByRole('tabpanel').getByText('Visual supporting span for kidney outcomes', { exact: true }).waitFor();
    if (width <= 768) await page.getByRole('dialog').getByRole('button', { name: 'Close evidence workspace' }).click();
    else await page.locator('.evidence-toggle').click();
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
      await page.getByLabel('Research message').fill('expire session');
      await page.getByRole('button', { name: 'Send' }).click();
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
