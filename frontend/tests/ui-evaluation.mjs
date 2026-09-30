import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
const target = process.env.UI_TEST_URL || 'http://127.0.0.1:5174';

async function scenario(role) {
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await context.newPage();
  let session = null;
  const evaluationRequests = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON?.() || {};
    let status = 200;
    let data = {};
    if (url.pathname === '/api/auth/me') { if (!session) status = 401; else data = { account: session }; }
    else if (url.pathname === '/api/auth/login') {
      session = { id: role, username: body.username, display_name: role, role, active: 1, must_change_password: 0 };
      data = { account: session };
    }
    else if (url.pathname === '/api/health') data = { status: 'healthy', service: 'Evidence Atlas' };
    else if (url.pathname === '/api/conversations') data = { total: 0, items: [] };
    else if (url.pathname.startsWith('/api/admin/evaluations')) {
      evaluationRequests.push(url.pathname);
      data = url.pathname === '/api/admin/evaluations'
        ? { items: [{ run_id: 'run-42', report_checksum: 'd'.repeat(64), benchmark_checksum: 'a'.repeat(64), corpus_checksum: 'b'.repeat(64), configuration_checksum: 'c'.repeat(64), query_count: 2, variants: ['dense_only', 'hybrid', 'agentic'] }] }
        : {
          run_id: 'run-42', report_checksum: 'd'.repeat(64), benchmark_checksum: 'a'.repeat(64), corpus_checksum: 'b'.repeat(64), configuration_checksum: 'c'.repeat(64), query_count: 2,
          variants: ['dense_only', 'hybrid', 'agentic'],
          metrics: {
            'dense_only.recall@10': { status: 'completed', value: 0.75, reason: null },
            'hybrid.faithfulness': { status: 'not_run', value: null, reason: 'Credentials are not configured' },
            'agentic.context_precision': { status: 'failed', value: null, reason: 'Provider failed' },
          },
          latency: { dense_only: { count: 2, median: 12.5 } }, failure_categories: { retrieval_miss: 1 },
          robustness: { dense_only: { status: 'completed', value: { scenarios: { noisy_query: { query_context_coverage: -0.2, context_precision: -0.1, candidate_filter_compliance: -0.3 } } }, reason: null } },
          queries: [{
            query_id: 'q1',
            variants: { dense_only: {
              diagnostics: [{ category: 'retriever_miss' }],
              robustness: { scenarios: { noisy_query: { query_context_coverage: -0.2, context_precision: -0.1, candidate_filter_compliance: -0.3 } } },
            } },
          }],
        };
    }
    else if (url.pathname === '/api/auth/logout') { session = null; data = { signed_out: true }; }
    else throw Error(`Unexpected API request ${request.url()}`);
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
  });
  await page.goto(`${target}/login`);
  await page.getByLabel('Username').fill(role === 'admin' ? 'administrator' : 'reader');
  await page.getByLabel('Password').fill('not-a-real-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  if (role === 'admin') {
    await page.getByRole('link', { name: 'Evaluations' }).waitFor();
    await page.getByRole('link', { name: 'Evaluations' }).click();
    await page.getByRole('heading', { name: 'Evaluation reports' }).waitFor();
    await page.getByRole('link', { name: 'View report' }).click();
    await page.getByRole('heading', { name: /run-42/i }).waitFor();
    await page.getByText('recall@10').first().waitFor();
    await page.getByText('Credentials are not configured').waitFor();
    await page.getByText('retrieval_miss').first().waitFor();
    for (const delta of ['-0.2', '-0.1', '-0.3']) await page.getByText(delta).first().waitFor();
    await page.getByText('query_context_coverage').first().waitFor();
    await page.getByText('context_precision').first().waitFor();
    await page.getByText('candidate_filter_compliance').first().waitFor();
    const ablation = page.locator('.evaluation-section').filter({ has: page.getByRole('heading', { name: 'Four-variant ablation' }) });
    assert.deepEqual(await ablation.locator('thead th').allTextContents(), ['Metric', 'dense_only', 'hybrid', 'reranked', 'agentic']);
    const missingVariantCell = ablation.locator('tbody tr').filter({ hasText: 'recall@10' }).locator('td').nth(2);
    assert.match(await missingVariantCell.innerText(), /not_run/i);
    assert.match(await missingVariantCell.innerText(), /variant was not included in this evaluation run/i);
    assert.ok(evaluationRequests.includes('/api/admin/evaluations'));
    assert.equal(evaluationRequests.filter(path => path === '/api/admin/evaluations/run-42').length, 1);
    assert.ok(evaluationRequests.every(path => path === '/api/admin/evaluations' || path === '/api/admin/evaluations/run-42'));
  } else {
    assert.equal(await page.getByRole('link', { name: 'Evaluations' }).count(), 0);
    await page.goto(`${target}/admin/evaluations`);
    await page.waitForURL('**/research');
    assert.equal(await page.getByRole('heading', { name: 'Evaluation reports' }).count(), 0);
    assert.deepEqual(evaluationRequests, [], 'ordinary sessions never request evaluation reports');
  }
  await context.close();
}

try {
  await scenario('admin');
  await scenario('user');
  console.log('PASS administrator evaluation dashboard and ordinary-user isolation');
} catch (error) {
  console.error('FAIL evaluation dashboard UI:', error.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
