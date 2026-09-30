import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
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
let failNextConversationDetail = false;
let heldTurn = null;
let heldTurnReady = Promise.resolve();
let announceHeldTurn = () => {};
let lastTurnBody = null;
const conversations = new Map();
const auditRows = [];
const traceRequests = [];

function turn(status, message) {
  const labels = { SUPPORTED: 'SUPPORTED', LIMITED: 'LIMITED', INSUFFICIENT: 'INSUFFICIENT', FAILED: 'FAILED' };
  const answer = message === 'clarify' ? 'Which population should the review focus on?' : `${labels[status]} response for ${message}. [PMID: 12345]`;
  const spans = [`Supporting span for ${message}`, `Second supporting span for ${message}`];
  const paper = { pmid: '12345', title: 'Illustrative research record', abstract: 'Fixture abstract with full stored text.', authors: ['Example Author', 'Second Author'], journal: 'Example Journal', year: 2024, study_type: 'Review', mesh_terms: ['Clinical Research', 'Evidence Synthesis'] };
  const secondPaper = { pmid: '67890', title: 'Second illustrative paper', abstract: 'Second full abstract text.', authors: ['Second Study Author'], journal: 'Other Journal', year: 2023, study_type: 'Trial', mesh_terms: ['Clinical Research'], detailError: true, sessionExpired: true, empty: true };
  return { conversation_id: 'conversation-1', turn_id: `turn-${Date.now()}`, action: message === 'clarify' ? 'CLARIFY' : 'RESEARCH', answer_status: status, assistant_message: answer, cited_pmids: ['12345'], evidence_table: [{ pmid: '12345', title: paper.title, key_findings: `Finding for ${message}`, outcome: 'Clinical outcome', limitations: 'Fixture limitation', supporting_text_spans: spans, retrieval_channels: ['bm25', 'dense'], subquestion_ids: ['sq-1'] }], retrieved_papers: [paper, secondPaper], evidence_gaps: status === 'INSUFFICIENT' ? ['No matching population data'] : [], consensus_level: status === 'INSUFFICIENT' ? 'insufficient' : 'consensus', progress_summary: 'Evidence review completed.', request_id: 'run-1', interpretation: { canonical_question: `Canonical question for ${message}`, pico: { population: 'Adults with condition X', intervention: 'Treatment A', comparator: 'Usual care', outcome: 'Clinical outcome' }, mesh_concepts: ['Condition X', 'Treatment A'], route: 'MODERATE', subquestions: [{ id: 'sq-1', question: `Does Treatment A improve outcomes for ${message}?` }], coverage_statuses: [{ subquestion_id: 'sq-1', status: 'COVERED' }] }, router_confidence: 0.98, router_reasoning: 'PRIVATE ROUTER REASONING', evaluation_metrics: { precision: 0.97 }, score: 0.97, graph_path: ['PRIVATE GRAPH NODE'], internal_trace: 'PRIVATE TRACE FIELD' };
}

await page.route('**/api/**', async route => {
  const request = route.request();
  const url = new URL(request.url());
  const body = request.postDataJSON?.() || {};
  let status = 200;
  let data = {};
  if (url.pathname === '/api/auth/me') { if (session) data = { account: session }; else status = 401; }
  else if (url.pathname === '/api/auth/login') { const role = body.username === 'administrator' ? 'admin' : 'user'; session = { id: role, username: body.username, display_name: role === 'admin' ? 'Administrator' : 'Reader', role, active: 1, must_change_password: 0 }; data = { account: session }; }
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
    lastTurnBody = body;
    if (body.message.startsWith('hold ')) await new Promise(resolve => { heldTurn = { resolve, id, message: body.message }; announceHeldTurn(heldTurn); });
    const record = conversations.get(id);
    if (body.message === 'hold failed A') {
      const failed = { turn_id: `turn-${Date.now()}`, sequence: record.turns.length + 1, user_message: body.message, action: 'RESEARCH', answer_status: 'FAILED', assistant_message: 'A technical failure prevented this turn from completing. Please try again.', created_at: '2026-09-29T12:00:00Z', result: null };
      record.turns.push(failed); status = 503; data = { detail: 'The conversation turn could not be completed' };
    } else {
    const answerStatus = body.message === 'limited' ? 'LIMITED' : body.message === 'insufficient' ? 'INSUFFICIENT' : body.message === 'failed' ? 'FAILED' : 'SUPPORTED';
    const result = turn(answerStatus, body.message);
    result.conversation_id = id;
    if (record.turns.length === 0) record.conversation.title = body.message.slice(0, 80);
    const savedTurn = { turn_id: result.turn_id, sequence: record.turns.length + 1, user_message: body.message, action: result.action, answer_status: result.answer_status, assistant_message: result.assistant_message, created_at: '2026-09-29T12:00:00Z', public_response: { cited_pmids: result.cited_pmids, evidence_table: result.evidence_table, retrieved_papers: result.retrieved_papers, evidence_gaps: result.evidence_gaps, consensus_level: result.consensus_level, interpretation: result.interpretation } };
    if (session?.role === 'admin') savedTurn.request_id = result.request_id;
    record.turns.push(savedTurn);
    if (session?.role === 'admin') auditRows.unshift({ id: result.request_id, query: body.message, username: session.username, role: session.role, operation: 'conversation_turn', status: 'completed', answer_status: result.answer_status, conversation_id: id, turn_id: result.turn_id, started_at: '2026-09-29T12:00:00Z', duration_ms: 12 });
    data = result;
    }
  } else if (url.pathname === '/api/admin/audits' && request.method() === 'GET') {
    data = { items: auditRows, total: auditRows.length };
  } else if (/\/api\/admin\/audits\/[^/]+$/.test(url.pathname)) {
    const id = url.pathname.split('/').pop();
    const item = auditRows.find(row => row.id === id) || auditRows[0];
    data = { ...item, error: null, response: { synthesis: 'SUPPORTED response for admin controlled question. [PMID: 12345]', cited_pmids: ['12345'], evidence_table: [{ pmid: '12345', supporting_text_spans: ['Supporting span for admin controlled question'] }], retrieved_papers: [{ pmid: '12345', title: 'Illustrative research record' }] }, trace: { citation_audit: { valid: true, cited_pmids: ['12345'] }, timings_ms: { total: 12 } }, events: [{ stage: 'agent_decision', payload: { action: 'RESEARCH', complexity_hint: 'SIMPLE' } }, { stage: 'answer_released', payload: { status: 'SUPPORTED', claim_count: 1 } }] };
  } else if (/^\/api\/trace\/[^/]+$/.test(url.pathname)) {
    traceRequests.push({ role: session?.role, id: url.pathname.split('/').pop() });
    if (session?.role !== 'admin') { status = 403; data = { detail: 'Administrator access required' }; }
    else data = { request_id: 'run-1', original_query: 'admin controlled question', query_plan: { canonical_query: 'Admin canonical query', route: 'MODERATE', router_confidence: 0.98, router_reasoning: 'ADMIN TRACE ROUTING DETAILS', subqueries: ['Admin trace expanded query'] }, retrieval_iterations: [{ iteration: 1, subqueries: ['Admin trace retrieval query'], channels_used: ['bm25'], retrieved_pmids: ['12345'], reason: 'Admin trace retrieval reason' }], final_evidence_pmids: ['12345'], timestamp: '2026-09-29T12:00:00Z', synthesis_metadata: { evaluation_metric: 'ADMIN TRACE METRIC 0.97' } };
  } else if (/\/api\/conversations\/[^/]+$/.test(url.pathname)) {
    const id = url.pathname.split('/').pop();
    const record = conversations.get(id);
    if (failNextConversationDetail) { failNextConversationDetail = false; status = 503; data = { detail: 'Conversation detail temporarily unavailable' }; }
    else data = { conversation: record.conversation, turns: record.turns, next_cursor: null };
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
  const publicConversation = page.getByRole('region', { name: 'Conversation messages' });
  await publicConversation.getByText('Canonical question for first question').waitFor();
  assert.equal(await publicConversation.getByText('Does Treatment A improve outcomes for first question?', { exact: true }).count(), 2, 'planned subquestion and its qualitative coverage are both shown');
  assert.equal(await publicConversation.getByText('Covered', { exact: true }).count(), 2, 'qualitative coverage appears in interpretation and evidence table');
  await publicConversation.getByText('bm25', { exact: true }).waitFor();
  await publicConversation.getByText(/Supporting span for first question/).waitFor();
  const [publicExportDownload] = await Promise.all([
    page.waitForEvent('download'),
    publicConversation.getByRole('button', { name: 'JSON' }).click(),
  ]);
  const publicExport = JSON.parse(await readFile(await publicExportDownload.path(), 'utf8'));
  assert.equal(Object.hasOwn(publicExport, 'request_id'), false, 'ordinary exports omit stale request IDs');
  assert.equal(Object.hasOwn(publicExport, 'audit_trace'), false, 'ordinary exports omit stale audit trace data');
  for (const secret of ['PRIVATE ROUTER REASONING', '0.98', '0.97', 'PRIVATE GRAPH NODE', 'PRIVATE TRACE FIELD', 'ADMIN TRACE ROUTING DETAILS']) assert.equal(await publicConversation.getByText(secret, { exact: false }).count(), 0, `ordinary view must hide ${secret}`);
  assert.equal(await publicConversation.getByRole('button', { name: /Research audit trail/i }).count(), 0, 'ordinary users see no trace control');
  assert.equal(await publicConversation.getByRole('heading', { name: 'Ranked papers' }).count(), 0, 'ordinary users see no ranked paper surface');
  assert.equal(await publicConversation.getByText(/^Rank \d+$/).count(), 0, 'ordinary users see no numeric retrieval ranks');
  assert.equal(traceRequests.length, 0, 'ordinary users make no audit trace request');
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
  await page.getByText('A technical failure prevented this turn from completing.').last().waitFor();
  assert.equal(await page.getByLabel('Research message').inputValue(), 'retry this text', 'retryable errors preserve the entered message');
  await page.getByLabel('Research message').fill('');

  await page.reload();
  await page.getByText('Which population should the review focus on?').waitFor();
  await page.getByText('INSUFFICIENT', { exact: true }).waitFor();
  await page.getByRole('button', { name: /Conversations/i }).click();
    await page.getByRole('button', { name: 'first question', exact: true }).click();
  await page.getByText('SUPPORTED response for first question.').waitFor();
  await page.getByRole('button', { name: 'PMID: 12345' }).first().click();
  await page.getByRole('tab', { name: /Illustrative research record/i }).waitFor();
  await page.getByLabel('Research message').fill('line one');
  await page.keyboard.press('Shift+Enter');
  await page.getByLabel('Research message').press('End');
    await page.getByLabel('Research message').pressSequentially('line two');
    assert.match(await page.getByLabel('Research message').inputValue(), /line one\nline two/);

  await page.locator('.evidence-toggle').click();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'first question', exact: true }).click();
  heldTurnReady = new Promise(resolve => { announceHeldTurn = resolve; });
  await page.getByLabel('Research message').fill('hold completion A');
  await page.keyboard.press('Enter');
  await heldTurnReady;
  await page.getByRole('status').filter({ hasText: /Retrieving|reviewing|evidence/i }).waitFor();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'limited', exact: true }).click();
  heldTurn.resolve(); heldTurn = null;
  await page.waitForTimeout(80);
  assert.equal(await page.getByRole('region', { name: 'Conversation messages' }).getByText('hold completion A', { exact: true }).count(), 0, 'a completed turn from A must not append to B');
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'first question', exact: true }).click();
  await page.getByText('SUPPORTED response for hold completion A.').waitFor();
  await page.getByRole('button', { name: 'Illustrative research record' }).last().waitFor();
  await page.getByText('Finding for hold completion A').first().waitFor();
  await page.getByRole('button', { name: 'Illustrative research record' }).last().click();
  await page.getByRole('tab', { name: /Illustrative research record/i }).waitFor();
  assert.equal(await page.getByRole('tab').count(), 2, 'a conversation has one overview and one tab per normalized PMID');
  assert.equal(await page.getByRole('tab', { name: /Overview/i }).count(), 1, 'overview is a permanent tab');
  const spanFromFirst = page.getByRole('region', { name: 'Conversation messages' }).locator('.conversation-message').filter({ hasText: 'SUPPORTED response for first question.' }).locator('.citation-button');
  const spanFromSecond = page.getByRole('region', { name: 'Conversation messages' }).locator('.conversation-message').filter({ hasText: 'SUPPORTED response for hold completion A.' }).locator('.evidence-span').first();
  await spanFromFirst.click();
  await page.getByRole('tab', { name: /Illustrative research record/i }).waitFor();
  assert.equal(await page.getByRole('tab').count(), 2, 'reopening a PMID from another turn focuses its existing tab');
  await page.locator('.evidence-toggle').click();
  await spanFromSecond.click();
  await page.getByRole('tabpanel').getByText('Supporting span for hold completion A', { exact: true }).waitFor();
  assert.equal(await page.locator('[data-evidence-span].is-highlighted').count(), 1, 'the selected supporting span is highlighted');
  assert.equal(await page.getByRole('tabpanel').count(), 1, 'the active tab owns one semantic tabpanel');
  assert.equal(await page.getByRole('link', { name: /View on PubMed/i }).getAttribute('target'), '_blank');
  assert.match(await page.getByRole('link', { name: /View on PubMed/i }).getAttribute('rel'), /noopener/);
  await page.getByRole('button', { name: 'Second illustrative paper' }).last().click();
  assert.equal(await page.getByRole('tab').count(), 3, 'a different PMID creates a distinct paper tab');
  await page.getByRole('alert').filter({ hasText: /Paper details could not be loaded/i }).waitFor();
  await page.getByRole('status').filter({ hasText: /session expired/i }).waitFor();
  await page.getByText(/No additional paper details were returned/i).waitFor();
  await page.getByRole('button', { name: 'Continue with available record' }).click();
  assert.equal(await page.getByRole('tab').count(), 3, 'recovering from a paper-detail error keeps all evidence tabs open');
  await page.getByRole('button', { name: /Close Second illustrative paper/i }).click();
  assert.equal(await page.getByRole('tab', { name: /Illustrative research record/i }).getAttribute('aria-selected'), 'true', 'closing the active tab selects its nearest remaining paper');
  await page.getByRole('button', { name: /Close Illustrative research record/i }).click();
  assert.equal(await page.getByRole('tab').count(), 1, 'closing the active paper returns to Overview');

  const evidenceToggle = page.locator('.evidence-toggle');
  await evidenceToggle.click();
  assert.equal(await evidenceToggle.getAttribute('aria-expanded'), 'false', 'collapse hides the panel and preserves workspace state');
  await evidenceToggle.click();
  assert.equal(await page.getByRole('tab').count(), 1, 'reopening restores the tab strip state');
  await page.getByRole('button', { name: 'PMID: 12345' }).first().click();
  await page.getByRole('tab', { name: /Illustrative research record/i }).waitFor();
  await page.locator('.evidence-toggle').click();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'limited', exact: true }).click();
  await page.locator('.evidence-toggle').click();
  assert.equal(await page.getByRole('tab').count(), 1, 'a different conversation starts Overview-only');
  await page.locator('.evidence-toggle').click();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'first question', exact: true }).click();
  await page.locator('.evidence-toggle').click();
  assert.equal(await page.getByRole('tab').count(), 2, 'returning to a conversation restores its paper tabs');

  await page.locator('.evidence-toggle').click();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'limited', exact: true }).click();
  failNextConversationDetail = true;
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'first question', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: /temporarily unavailable/i }).waitFor();
  await page.locator('.evidence-toggle').click();
  assert.equal(await page.getByRole('tab').count(), 2, 'conversation-detail errors leave the session-memory evidence tabs intact');
  await page.locator('.evidence-toggle').click();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'limited', exact: true }).click();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'first question', exact: true }).click();
  await page.getByText('SUPPORTED response for first question.').waitFor();
  await page.locator('.evidence-toggle').click();

  await page.setViewportSize({ width: 1440, height: 900 });
  const splitter = page.getByRole('separator', { name: /Resize evidence workspace/i });
  const box = await splitter.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + 10);
  await page.mouse.down(); await page.mouse.move(0, box.y + 10); await page.mouse.up();
  assert.ok((await page.locator('.evidence-workspace').boundingBox()).width <= 720, 'pointer resize respects the min(50vw, 760px) maximum');
  await splitter.focus(); await page.keyboard.press('Home');
  assert.equal(Math.round((await page.locator('.evidence-workspace').boundingBox()).width), 360, 'keyboard Home sets the desktop minimum');
  await page.keyboard.press('ArrowRight');
  assert.equal(Math.round((await page.locator('.evidence-workspace').boundingBox()).width), 360, 'keyboard decrement respects the desktop minimum');
  await page.keyboard.press('End');
  assert.equal(Math.round((await page.locator('.evidence-workspace').boundingBox()).width), 720, 'keyboard End respects the desktop maximum');
  for (const width of [768, 390, 320]) {
    await page.setViewportSize({ width, height: 850 });
    if (await page.locator('.evidence-toggle').getAttribute('aria-expanded') !== 'true') await page.locator('.evidence-toggle').click();
    await page.getByRole('dialog', { name: /Evidence workspace/i }).waitFor();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `${width}px layout has no horizontal page overflow`);
    if (width === 768) {
      const mobileTabs = page.getByRole('dialog').getByRole('tab');
      await mobileTabs.first().focus(); await page.keyboard.press('ArrowRight');
      assert.equal(await mobileTabs.nth(1).getAttribute('aria-selected'), 'true', 'ArrowRight switches the active evidence tab');
      await page.keyboard.press('ArrowLeft');
      assert.equal(await mobileTabs.first().getAttribute('aria-selected'), 'true', 'ArrowLeft returns to Overview');
    }
    await page.keyboard.press('Escape');
    await page.getByRole('dialog', { name: /Evidence workspace/i }).waitFor({ state: 'detached' });
  }
  await page.setViewportSize({ width: 390, height: 850 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('.evidence-toggle').click();
  const mobileDialog = page.getByRole('dialog', { name: /Evidence workspace/i });
  await mobileDialog.waitFor();
  assert.equal(await mobileDialog.getAttribute('aria-modal'), 'true');
  assert.equal(await page.evaluate(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches), true, 'reduced-motion preference is respected by the workspace');
  assert.equal(await mobileDialog.locator('.evidence-tabpanel').evaluate(node => getComputedStyle(node).scrollBehavior), 'auto', 'reduced motion disables smooth panel scrolling');
  await mobileDialog.getByRole('tab', { name: /Overview/i }).focus();
  await page.keyboard.press('Shift+Tab');
  assert.ok(await mobileDialog.evaluate(node => node.contains(document.activeElement)), 'keyboard focus stays inside the mobile drawer');
  const mobileFocusables = mobileDialog.locator('button:not([disabled]), a[href], [tabindex="0"]');
  await mobileFocusables.last().focus(); await page.keyboard.press('Tab');
  assert.equal(await mobileDialog.evaluate(node => node.contains(document.activeElement)), true, 'Tab from the final control wraps inside the drawer');
  await page.keyboard.press('Escape');
  await mobileDialog.waitFor({ state: 'detached' });
  assert.match(await page.evaluate(() => document.activeElement?.getAttribute('aria-label') || ''), /Evidence workspace/i, 'Escape restores focus to the top-bar toggle');
  assert.deepEqual(errors, []);

  heldTurnReady = new Promise(resolve => { announceHeldTurn = resolve; });
  await page.getByLabel('Research message').fill('hold failed A');
  await page.keyboard.press('Enter');
  await heldTurnReady;
  await page.getByRole('status').filter({ hasText: /Retrieving|reviewing|evidence/i }).waitFor();
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'limited', exact: true }).click();
  heldTurn.resolve(); heldTurn = null;
  await page.waitForTimeout(80);
  assert.equal(await page.getByRole('alert').count(), 0, 'a failed turn from A must not show an error in B');
  await page.getByRole('button', { name: /Conversations/i }).click();
  await page.getByRole('button', { name: 'first question', exact: true }).click();
  await page.getByText('FAILED', { exact: true }).first().waitFor();

  assert.equal(await page.getByLabel('Publication year from').count(), 0, 'ordinary accounts cannot access admin research controls');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await page.getByLabel('Username').fill('administrator');
  await page.getByLabel('Password').fill('not-a-real-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('heading', { name: /Research conversations/i }).waitFor();
  assert.equal(await page.getByLabel('Publication year from').count(), 1);
  await page.getByLabel('Publication year from').selectOption('2020');
  await page.getByLabel('Publication year to').selectOption('2024');
  await page.getByLabel('Study type').selectOption('Review');
  await page.getByLabel('Corrective retrieval attempts').selectOption('4');
  await page.getByLabel('Research message').fill('admin controlled question');
  await page.keyboard.press('Enter');
  await page.getByText('SUPPORTED response for admin controlled question.').waitFor();
  await page.getByText('Canonical question for admin controlled question').waitFor();
  assert.equal(traceRequests.length, 0, 'admin trace is not requested before expansion');
  const adminConversation = page.getByRole('region', { name: 'Conversation messages' });
  assert.equal(await adminConversation.getByText('PRIVATE ROUTER REASONING', { exact: true }).count(), 0, 'admin diagnostics do not come from the public turn payload');
  assert.equal(await adminConversation.getByRole('button', { name: /Research audit trail/i }).count(), 1, 'administrator has an audit expansion control');
  await page.getByRole('button', { name: /Research audit trail/i }).click();
  await page.getByText('Admin trace expanded query').waitFor();
  assert.deepEqual(traceRequests.at(-1), { role: 'admin', id: 'run-1' }, 'admin trace request follows explicit audit expansion');
  await page.reload();
  await page.getByRole('button', { name: /Research audit trail/i }).waitFor();
  assert.equal(traceRequests.length, 1, 'restored admin history keeps audit trace collapsed without a request');
  await page.getByRole('button', { name: /Research audit trail/i }).click();
  await page.getByText('Admin trace expanded query').waitFor();
  assert.deepEqual(traceRequests.at(-1), { role: 'admin', id: 'run-1' }, 'restored admin history loads its trace only after expansion');
  assert.deepEqual(lastTurnBody, { message: 'admin controlled question', year_min: 2020, year_max: 2024, study_types: ['Review'], max_loops: 4 });
  await page.getByRole('link', { name: 'Audit logs' }).click();
  await page.getByRole('cell', { name: 'admin controlled question' }).waitFor();
  await page.getByRole('link', { name: 'View trace' }).click();
  await page.getByRole('heading', { name: 'Query trace' }).waitFor();
  await page.getByText(/Conversation phase timeline/i).waitFor();
  await page.getByText('admin controlled question', { exact: true }).first().waitFor();
  await page.getByRole('link', { name: 'Research', exact: true }).click();
  await page.getByRole('heading', { name: /Research conversations/i }).waitFor();

  expireNextList = true;
  await page.reload();
  await page.getByRole('heading', { name: 'Welcome back.' }).waitFor();
  assert.deepEqual(errors, []);
  console.log('PASS conversation persistence and interaction');
} catch (error) {
  console.error('FAIL conversation persistence and interaction:', error.message, 'URL:', page.url(), 'BODY:', (await page.locator('body').innerText()).slice(0, 900));
  process.exitCode = 1;
} finally { await context.close(); await browser.close(); }
