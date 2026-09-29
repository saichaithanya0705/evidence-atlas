import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const target = process.env.UI_TEST_URL || 'http://127.0.0.1:5174';
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
page.setDefaultTimeout(8000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let session = null;
let nextId = 1;
let expireNextList = false;
let delayTurn = false;
let failNextTurn = false;
const conversations = new Map();

function turn(status, message) {
  const labels = { SUPPORTED: 'SUPPORTED', LIMITED: 'LIMITED', INSUFFICIENT: 'INSUFFICIENT', FAILED: 'FAILED' };
  const answer = message === 'clarify' ? 'Which population should the review focus on?' : `${labels[status]} response for ${message}. [PMID: 12345]`;
  return { conversation_id: 'conversation-1', turn_id: `turn-${Date.now()}`, action: message === 'clarify' ? 'CLARIFY' : 'RESEARCH', answer_status: status, assistant_message: answer, cited_pmids: ['12345'], evidence_table: [], retrieved_papers: [{ pmid: '12345', title: 'Illustrative research record', abstract: 'Fixture abstract.', authors: ['Example'], year: 2024, study_type: 'Review' }], evidence_gaps: status === 'INSUFFICIENT' ? ['No matching population data'] : [], consensus_level: status === 'INSUFFICIENT' ? 'insufficient' : 'consensus', progress_summary: 'Evidence review completed.', request_id: 'run-1' };
}

await page.route('**/api/**', async route => {
  const request = route.request();
  const url = new URL(request.url());
  const body = request.postDataJSON?.() || {};
  let status = 200;
  let data = {};
  if (url.pathname === '/api/auth/me') { if (session) data = { account: session }; else status = 401; }
  else if (url.pathname === '/api/auth/login') { session = { id: 'reader', username: body.username, display_name: 'Reader', role: 'user', active: 1, must_change_password: 0 }; data = { account: session }; }
  else if (url.pathname === '/api/health') data = { status: 'healthy' };
  else if (url.pathname === '/api/auth/logout') { session = null; data = { signed_out: true }; }
  else if (url.pathname === '/api/conversations' && request.method() === 'POST') {
    const id = `conversation-${nextId++}`;
    const conversation = { conversation_id: id, title: 'New conversation', created_at: '2026-09-29T12:00:00Z', updated_at: '2026-09-29T12:00:00Z' };
    conversations.set(id, { conversation, turns: [] }); data = conversation;
  } else if (url.pathname === '/api/conversations' && request.method() === 'GET') {
    if (expireNextList) { expireNextList = false; session = null; status = 401; data = { detail: 'Sign in to continue' }; }
    else data = { total: conversations.size, items: [...conversations.values()].map(item => item.conversation) };
  } else if (/\/api\/conversations\/[^/]+\/turns$/.test(url.pathname)) {
    if (failNextTurn) { failNextTurn = false; await route.abort('failed'); return; }
    const id = url.pathname.split('/')[3];
    if (delayTurn) await new Promise(resolve => setTimeout(resolve, 350));
    const record = conversations.get(id);
    const answerStatus = body.message === 'limited' ? 'LIMITED' : body.message === 'insufficient' ? 'INSUFFICIENT' : body.message === 'failed' ? 'FAILED' : 'SUPPORTED';
    const result = turn(answerStatus, body.message);
    result.conversation_id = id;
    if (record.turns.length === 0) record.conversation.title = body.message.slice(0, 80);
    record.turns.push({ turn_id: result.turn_id, sequence: record.turns.length + 1, user_message: body.message, action: result.action, answer_status: result.answer_status, assistant_message: result.assistant_message, created_at: '2026-09-29T12:00:00Z', result });
    data = result;
  } else if (/\/api\/conversations\/[^/]+$/.test(url.pathname)) {
    const id = url.pathname.split('/').pop();
    const record = conversations.get(id);
    data = { conversation: record.conversation, turns: record.turns, next_cursor: null };
  } else throw Error(`Unexpected API request ${request.url()}`);
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
});

try {
  await page.goto(`${target}/login`);
  await page.getByLabel('Username').fill('reader');
  await page.getByLabel('Password').fill('not-a-real-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('heading', { name: /Research conversations/i }).waitFor();
  assert.match(page.url(), /\/research$/);
  await page.getByText('Research support, not medical advice. Review the original papers.').waitFor();

  const composer = page.getByLabel('Research message');
  await composer.fill('first question');
  delayTurn = true;
  await page.keyboard.press('Enter');
  await page.waitForURL(/\/research\/conversation-1$/);
  await page.getByRole('region', { name: 'Conversation messages' }).getByText('first question', { exact: true }).waitFor();
  await page.getByRole('status').filter({ hasText: /Retrieving|reviewing|evidence/i }).waitFor();
  assert.equal(await page.getByText(/draft answer|preliminary answer/i).count(), 0, 'progress must not show unverified answer claims');
  const send = page.locator('.conversation-composer button[type="submit"]');
  assert.equal(await send.isDisabled(), true, 'duplicate submit must be disabled while request is running');
  await page.getByText('SUPPORTED response for first question.').waitFor();
  delayTurn = false;

  await page.getByRole('button', { name: /New conversation/i }).click();
  await page.getByRole('heading', { name: /Research conversations/i }).waitFor();
  await composer.fill('limited'); await page.keyboard.press('Enter');
  await page.getByText('LIMITED response for limited.').waitFor();
  await composer.fill('insufficient'); await page.keyboard.press('Enter');
  await page.getByText('INSUFFICIENT response for insufficient.').waitFor();
  await composer.fill('failed'); await page.keyboard.press('Enter');
  await page.getByText('FAILED response for failed.').waitFor();
  await composer.fill('clarify'); await page.keyboard.press('Enter');
  await page.getByText('Which population should the review focus on?').waitFor();
  failNextTurn = true;
  await composer.fill('retry this text'); await page.keyboard.press('Enter');
  await page.getByText('A technical failure prevented this turn from completing.').waitFor();
  assert.equal(await page.getByLabel('Research message').inputValue(), 'retry this text', 'retryable errors preserve the entered message');
  await page.getByLabel('Research message').fill('');

  await page.reload();
  await page.getByText('Which population should the review focus on?').waitFor();
  await page.getByText('INSUFFICIENT', { exact: true }).waitFor();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: /first question/i }).click();
  await page.getByText('SUPPORTED response for first question.').waitFor();
  await page.getByRole('button', { name: 'PMID: 12345' }).first().click();
  await page.getByText('Selected source 12345.').waitFor();
  await page.getByLabel('Research message').fill('line one');
  await page.keyboard.press('Shift+Enter');
  await page.getByLabel('Research message').press('End');
  await page.getByLabel('Research message').pressSequentially('line two');
  assert.match(await page.getByLabel('Research message').inputValue(), /line one\nline two/);

  expireNextList = true;
  await page.reload();
  await page.getByRole('heading', { name: 'Welcome back.' }).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS conversation persistence and interaction');
} catch (error) {
  console.error('FAIL conversation persistence and interaction:', error.message);
  process.exitCode = 1;
} finally { await context.close(); await browser.close(); }
