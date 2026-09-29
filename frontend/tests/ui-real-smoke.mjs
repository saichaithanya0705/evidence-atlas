import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const url = process.env.UI_TEST_URL || 'http://127.0.0.1:5173';
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${url}/login`);
  await page.getByRole('heading', { name: 'Welcome back.' }).waitFor();
  assert.match(await page.title(), /Evidence Atlas/i);
  assert.equal(await page.getByText('Research service connected').count(), 0);
  assert.equal(await page.getByLabel('Username').count(), 1);
  assert.equal(await page.getByLabel('Password').count(), 1);
  assert.deepEqual(errors, []);
  if (process.env.UI_REAL_USERNAME && process.env.UI_REAL_PASSWORD) {
    await page.getByLabel('Username').fill(process.env.UI_REAL_USERNAME);
    await page.getByLabel('Password').fill(process.env.UI_REAL_PASSWORD);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByRole('heading', { name: /Medical evidence/i }).waitFor();
    assert.equal(await page.getByRole('link', { name: 'Audit logs' }).count(), process.env.UI_REAL_ROLE === 'admin' ? 1 : 0);
    await page.getByRole('button', { name: 'Sign out' }).click();
    await page.getByRole('heading', { name: 'Welcome back.' }).waitFor();
    assert.deepEqual(errors, []);
  }
  if (process.env.UI_SCREENSHOT_PATH) await page.screenshot({ path: process.env.UI_SCREENSHOT_PATH, fullPage: true });
  console.log('PASS real-server signed-out page and API proxy');
} finally {
  await browser.close();
}
