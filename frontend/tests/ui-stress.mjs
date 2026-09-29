import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
const outputDir = process.env.UI_STRESS_OUTPUT || path.join(os.tmpdir(), "evidence-atlas-ui-stress");
const targetUrl = process.env.UI_STRESS_URL || "http://127.0.0.1:5173";
const browserPath = process.env.PLAYWRIGHT_BROWSER_PATH ||
  "C:/Program Files/Google/Chrome/Application/chrome.exe";
const requestTimeoutMs = Number(process.env.UI_STRESS_TIMEOUT_MS || 240_000);
const onlyScenario = process.env.UI_STRESS_ONLY || "";
const userName = process.env.UI_STRESS_USERNAME;
const userPassword = process.env.UI_STRESS_PASSWORD;
if (!userName || !userPassword) throw new Error("Set UI_STRESS_USERNAME and UI_STRESS_PASSWORD for an ordinary-user account before running live stress tests.");

async function signIn(page, username, password) {
  await page.goto(`${targetUrl}/login`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: /Medical evidence/i }).waitFor({ timeout: 30_000 });
}

const queries = [
  "What are the kidney outcomes of SGLT2 inhibitors in chronic kidney disease?",
  "Do SGLT2 inhibitors reduce progression of chronic kidney disease?",
  "Compare renal outcomes of dapagliflozin and canagliflozin in chronic kidney disease.",
  "What adverse kidney events are reported with SGLT2 inhibitors?",
  "How do sodium glucose cotransporter inhibitors affect albuminuria?",
  "What mechanisms explain renal protection from SGLT2 inhibition?",
  "SGLT2 inhibitor randomized trials in patients with chronic kidney disease",
  "Acute kidney injury risk during SGLT2 inhibitor treatment",
  "Long term eGFR outcomes after SGLT2 inhibitor therapy",
  "Evidence for SGLT2 inhibitors in diabetic kidney disease",
];

const forbiddenNormalUserText = [
  "How this search was understood",
  "Evidence table",
  "Research audit trail",
  "Why this paper?",
  "Citation precision",
  "Supporting spans from the abstract",
  "Retrieval provenance",
];

function percentile(values, quantile) {
  if (!values.length) return null;
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.min(ordered.length - 1, Math.ceil(quantile * ordered.length) - 1)];
}

async function runUser(browser, { query, label, viewport = { width: 1440, height: 900 }, inspect = false }) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const startedAt = performance.now();
  const apiResponses = [];
  const consoleErrors = [];
  page.on("response", (response) => {
    if (response.url().includes("/research")) {
      apiResponses.push({ status: response.status(), url: response.url() });
    }
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  try {
    await signIn(page, userName, userPassword);
    await page.getByText("Research service connected", { exact: true }).first().waitFor({
      state: "attached",
      timeout: 30_000,
    });
    if (await page.getByRole("link", { name: "Audit logs" }).count()) throw new Error("Ordinary-user context exposed administrator navigation");

    await page.locator("#research-query").fill(query);
    await page.getByRole("button", { name: "Research", exact: true }).click();
    await page.locator(".paper-title-button").first().waitFor({ timeout: requestTimeoutMs });
    await page.getByRole("button", { name: "Research", exact: true }).waitFor({ state: "visible" });

    const paperCount = await page.locator(".paper-title-button").count();
    const synthesis = (await page.locator(".synthesis-copy").textContent().catch(() => ""))?.trim() || "";
    if (!paperCount) throw new Error("No ranked papers were displayed");
    if (!synthesis) throw new Error("No synthesis text was displayed");
    if (!apiResponses.length || apiResponses.some((response) => response.status >= 400)) {
      throw new Error(`Research request did not complete successfully: ${JSON.stringify(apiResponses)}`);
    }

    for (const text of forbiddenNormalUserText) {
      if (await page.getByText(text, { exact: false }).count()) {
        throw new Error(`Admin-only text was exposed to an ordinary user: ${text}`);
      }
    }

    if (inspect) {
      await page.locator(".paper-title-button").first().click();
      await page.getByRole("tab", { name: "Overview" }).waitFor({ timeout: 20_000 });
      if (await page.getByRole("tab").count() !== 1) {
        throw new Error("Ordinary-user paper drawer exposed admin-only tabs");
      }
      await page.screenshot({
        path: path.join(outputDir, `${label}-result.jpg`),
        type: "jpeg",
        quality: 85,
        scale: "css",
      });
      await page.getByRole("button", { name: "Close selected paper details" }).click();
    }

    const dimensions = await page.evaluate(() => ({
      innerWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    if (dimensions.horizontalOverflow) throw new Error(`Horizontal overflow at ${viewport.width}px`);

    return {
      label,
      query,
      ok: true,
      durationMs: Math.round(performance.now() - startedAt),
      paperCount,
      synthesisLength: synthesis.length,
      apiResponses,
      consoleErrors,
      viewport,
    };
  } catch (error) {
    await page.screenshot({
      path: path.join(outputDir, `${label}-failure.jpg`),
      type: "jpeg",
      quality: 85,
      scale: "css",
      fullPage: false,
    }).catch(() => {});
    const alerts = await page.getByRole("alert").allTextContents().catch(() => []);
    return {
      label,
      query,
      ok: false,
      durationMs: Math.round(performance.now() - startedAt),
      error: error instanceof Error ? error.message : String(error),
      alerts,
      apiResponses,
      consoleErrors,
      viewport,
    };
  } finally {
    await context.close();
  }
}

async function validateYearRange(browser) {
  if (!process.env.UI_STRESS_ADMIN_USERNAME || !process.env.UI_STRESS_ADMIN_PASSWORD) return { ok: true, skipped: "No administrator stress-test credentials configured" };
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await signIn(page, process.env.UI_STRESS_ADMIN_USERNAME, process.env.UI_STRESS_ADMIN_PASSWORD);
    await page.locator("#research-query").fill(queries[0]);
    await page.getByLabel("Publication year from").selectOption("2025");
    await page.getByLabel("Publication year to").selectOption("2020");
    await page.getByRole("button", { name: "Research", exact: true }).click();
    const alert = page.getByRole("alert");
    await alert.waitFor({ timeout: 5_000 });
    const text = (await alert.textContent())?.trim() || "";
    return { ok: text.includes("start year"), text };
  } finally {
    await context.close();
  }
}

await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: browserPath });
const results = [];

try {
  if (onlyScenario !== "mobile") {
    for (let index = 0; index < 3; index += 1) {
      results.push(await runUser(browser, {
        query: queries[index],
        label: `sequential-${index + 1}`,
        inspect: index === 0,
      }));
    }

    for (const concurrency of [2, 5, 10]) {
      const wave = Array.from({ length: concurrency }, (_, index) => runUser(browser, {
        query: queries[index % queries.length],
        label: `c${concurrency}-user-${index + 1}`,
      }));
      results.push(...await Promise.all(wave));
      if (results.slice(-concurrency).some((result) => !result.ok) && concurrency < 10) break;
    }
  }

  results.push(await runUser(browser, {
    query: queries[0],
    label: "mobile-390",
    viewport: { width: 390, height: 844 },
    inspect: true,
  }));

  const validation = await validateYearRange(browser);
  const successfulDurations = results.filter((result) => result.ok).map((result) => result.durationMs);
  const concurrencySummaries = [2, 5, 10].map((concurrency) => {
    const group = results.filter((result) => result.label.startsWith(`c${concurrency}-`));
    return {
      concurrency,
      attempted: group.length,
      succeeded: group.filter((result) => result.ok).length,
      failed: group.filter((result) => !result.ok).length,
      p95Ms: percentile(group.filter((result) => result.ok).map((result) => result.durationMs), 0.95),
      maxMs: group.length ? Math.max(...group.map((result) => result.durationMs)) : null,
    };
  }).filter((summary) => summary.attempted);

  const report = {
    generatedAt: new Date().toISOString(),
    targetUrl,
    ordinaryUserOnly: true,
    totalFlows: results.length,
    succeeded: results.filter((result) => result.ok).length,
    failed: results.filter((result) => !result.ok).length,
    latencyMs: {
      p50: percentile(successfulDurations, 0.5),
      p95: percentile(successfulDurations, 0.95),
      max: successfulDurations.length ? Math.max(...successfulDurations) : null,
    },
    concurrency: concurrencySummaries,
    reversedYearValidation: validation,
    results,
  };
  await fs.writeFile(path.join(outputDir, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({
    totalFlows: report.totalFlows,
    succeeded: report.succeeded,
    failed: report.failed,
    latencyMs: report.latencyMs,
    concurrency: report.concurrency,
    reversedYearValidation: report.reversedYearValidation,
  }, null, 2));
  if (report.failed || !validation.ok) process.exitCode = 1;
} finally {
  await browser.close();
}
