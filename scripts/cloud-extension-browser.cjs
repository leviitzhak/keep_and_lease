#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function main() {
  const webUri = process.env.KEEP_AND_LEASE_WEB_URI;
  const token = process.env.KEEP_AND_LEASE_ID_TOKEN;
  const outputDir = process.env.KEEP_AND_LEASE_OUTPUT_DIR;
  const expectedCommit = process.env.KEEP_AND_LEASE_EXPECTED_COMMIT || '';
  if (!webUri || !token || !outputDir) {
    throw new Error('KEEP_AND_LEASE_WEB_URI, KEEP_AND_LEASE_ID_TOKEN, and KEEP_AND_LEASE_OUTPUT_DIR are required');
  }

  const origin = new URL(webUri).origin;
  fs.mkdirSync(outputDir, {recursive: true});
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  await context.route('**/*', async route => {
    const request = route.request();
    const target = new URL(request.url());
    if (target.origin === origin) {
      await route.continue({headers: {...request.headers(), authorization: `Bearer ${token}`}});
    } else {
      await route.continue();
    }
  });

  const page = await context.newPage();
  async function api(pathname, options = {}) {
    return page.evaluate(async ({pathname, options}) => {
      const response = await fetch(pathname, {...options, credentials: 'include', cache: 'no-store'});
      let body;
      try { body = await response.json(); } catch (_) { body = null; }
      return {status: response.status, ok: response.ok, body};
    }, {pathname, options});
  }
  async function waitJob(jobId, timeoutMs = 15 * 60 * 1000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const response = await api(`/api/v1/backtests/${jobId}`);
      if (!response.ok) throw new Error(`Job ${jobId.slice(0, 8)} status HTTP ${response.status}`);
      const job = response.body;
      if (job.status === 'completed') return job;
      if (job.status === 'failed' || job.status === 'cancelled') {
        throw new Error(`Job ${jobId.slice(0, 8)} stopped: ${job.error || job.detail || job.status}`);
      }
      await sleep(5000);
    }
    throw new Error(`Timed out waiting for job ${jobId.slice(0, 8)}`);
  }
  async function result(jobId) {
    const response = await api(`/api/v1/backtests/${jobId}/result`);
    if (!response.ok) throw new Error(`Result ${jobId.slice(0, 8)} HTTP ${response.status}: ${response.body?.detail || 'unknown error'}`);
    return response.body;
  }
  async function setDateTime(name, value) {
    const locator = page.locator(`[name="${name}"]`);
    const actual = await locator.evaluate((element, nextValue) => {
      element.value = nextValue;
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
      return element.value;
    }, value);
    if (!actual) throw new Error(`Browser rejected ${name}=${value}`);
    return actual;
  }

  try {
    const response = await page.goto(`${origin}/?engine=server`, {waitUntil: 'domcontentloaded', timeout: 120000});
    if (response?.status() !== 200) throw new Error(`GUI returned HTTP ${response?.status()}`);
    await page.waitForFunction(() => {
      const button = document.querySelector('#run');
      const status = (document.querySelector('#status')?.textContent || '').toLowerCase();
      return button && !button.disabled && status.includes('server') && status.includes('ready');
    }, null, {timeout: 180000});
    if (expectedCommit) {
      await page.waitForFunction(commit => document.querySelector('#buildInfo')?.getAttribute('title') === commit,
        expectedCommit, {timeout: 30000});
    }

    await page.selectOption('[name="btc_data_source"]', 'trade_tape');
    await page.click('#loadTradeExample');
    await page.fill('[name="execution_interval_seconds"]', '3600');
    await setDateTime('backtest_start', '2026-06-25T00:00:00.000');
    await setDateTime('backtest_end', '2026-06-25T01:00:01.000');

    const submitted = page.waitForResponse(r => new URL(r.url()).pathname === '/api/v1/backtests' && r.request().method() === 'POST', {timeout: 60000});
    await page.click('#run');
    const parentResponse = await submitted;
    const parentBody = await parentResponse.json();
    if (![200, 202].includes(parentResponse.status()) || !parentBody.job_id) {
      throw new Error(`Parent replay submission failed: HTTP ${parentResponse.status()}`);
    }
    const parentId = parentBody.job_id;
    const parentJob = await waitJob(parentId);
    const parentResult = await result(parentId);
    if (parentResult.backtest_period?.actual_end !== '2026-06-25T01:00:01.000000') {
      throw new Error(`Parent replay ended at ${parentResult.backtest_period?.actual_end}`);
    }
    if (!String(parentJob.parameters?.backtest_end || '').startsWith('2026-06-25T01:00:01')) {
      throw new Error('Parent saved parameters lost the requested end');
    }

    await setDateTime('backtest_end', '2026-06-25T01:00:03.000');
    await page.getByRole('button', {name: 'Refresh runs', exact: true}).click();
    const row = page.locator(`#backtestRuns [data-job-id="${parentId}"]`);
    await row.waitFor({state: 'visible', timeout: 30000});
    const extendResponsePromise = page.waitForResponse(r =>
      new URL(r.url()).pathname === `/api/v1/backtests/${parentId}/extend` && r.request().method() === 'POST',
      {timeout: 60000});
    await row.getByRole('button', {name: 'Extend to form end', exact: true}).click();
    const extendResponse = await extendResponsePromise;
    const extension = await extendResponse.json();
    if (!extendResponse.ok()) {
      throw new Error(`Extension request failed HTTP ${extendResponse.status()}: ${extension.detail || 'unknown error'}`);
    }
    if (!extension.job_id || extension.job_id === parentId || extension.extension_parent_job_id !== parentId) {
      throw new Error('Extension response lost parent/child lineage');
    }
    if (Object.keys(extension.parameters || {}).some(key => key.startsWith('__keep_and_lease_'))) {
      throw new Error('Internal extension metadata leaked through the public API');
    }

    const childId = extension.job_id;
    await waitJob(childId);
    const childResult = await result(childId);
    const expectedResumeUs = Date.parse('2026-06-25T01:00:00Z') * 1000;
    if (childResult.backtest_period?.actual_end !== '2026-06-25T01:00:03.000000'
        || childResult.backtest_period?.requested_end !== '2026-06-25T01:00:03.000000') {
      throw new Error(`Extension ended at ${childResult.backtest_period?.actual_end}`);
    }
    if (childResult.trade_replay?.resumed_after_us !== expectedResumeUs) {
      throw new Error(`Extension did not resume from the hourly checkpoint: ${childResult.trade_replay?.resumed_after_us}`);
    }
    if (childResult.summary?.observations < 2 || childResult.summary?.missing_intervals !== 0) {
      throw new Error('Extended replay has invalid valuation coverage');
    }

    const parentAfter = await result(parentId);
    if (parentAfter.backtest_period?.actual_end !== parentResult.backtest_period.actual_end
        || parentAfter.summary?.ending_nav !== parentResult.summary?.ending_nav) {
      throw new Error('Extension mutated the completed parent result');
    }

    const evidence = {
      commit: expectedCommit,
      parent_job_id: parentId,
      child_job_id: childId,
      parent_end: parentResult.backtest_period.actual_end,
      child_end: childResult.backtest_period.actual_end,
      resumed_after_us: childResult.trade_replay.resumed_after_us,
      child_observations: childResult.summary.observations,
      parent_ending_nav: parentResult.summary.ending_nav,
      child_ending_nav: childResult.summary.ending_nav,
    };
    fs.writeFileSync(path.join(outputDir, 'extension.json'), JSON.stringify(evidence, null, 2));
    console.log('Completed replay extension acceptance passed: ' + JSON.stringify(evidence));
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error('extension browser check failed:', error.stack || error);
  process.exitCode = 2;
});
