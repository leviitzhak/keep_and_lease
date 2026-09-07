#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const webUri = process.env.KEEP_AND_LEASE_WEB_URI;
  const token = process.env.KEEP_AND_LEASE_ID_TOKEN;
  const outputDir = process.env.KEEP_AND_LEASE_OUTPUT_DIR;
  const expectedCommit = process.env.KEEP_AND_LEASE_EXPECTED_COMMIT || "";
  const runSmokeStrategy = process.env.KEEP_AND_LEASE_RUN_SMOKE_STRATEGY === "true";
  const runSubsecond = process.env.KEEP_AND_LEASE_RUN_SUBSECOND === "true";
  const runBtcAudit = process.env.KEEP_AND_LEASE_RUN_BTC_AUDIT === "true";
  if (!webUri || !token || !outputDir) {
    throw new Error("KEEP_AND_LEASE_WEB_URI, KEEP_AND_LEASE_ID_TOKEN, and KEEP_AND_LEASE_OUTPUT_DIR are required");
  }

  const origin = new URL(webUri).origin;
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
  });

  // Attach the Google identity token only to the private Cloud Run origin. Never
  // forward it to third-party scripts, fonts, analytics, or redirect targets.
  await context.route("**/*", async (route) => {
    const request = route.request();
    const target = new URL(request.url());
    if (target.origin === origin) {
      await route.continue({
        headers: { ...request.headers(), authorization: `Bearer ${token}` },
      });
      return;
    }
    await route.continue();
  });

  const page = await context.newPage();
  const consoleMessages = [];
  const pageErrors = [];
  const failedRequests = [];
  const verifiedDownloadPaths = new Set();
  let responseStatus = null;
  let documentState = null;
  let strategy = null;
  let failure = null;
  page.on("console", (message) => {
    consoleMessages.push({ type: message.type(), text: message.text().slice(0, 2000) });
  });
  page.on("pageerror", (error) => pageErrors.push(String(error).slice(0, 4000)));
  page.on("requestfailed", (request) => {
    failedRequests.push({
      method: request.method(),
      url: request.url(),
      error: request.failure()?.errorText || "unknown",
    });
  });

  try {
    const response = await page.goto(`${origin}/?engine=server`, {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });
    responseStatus = response?.status() ?? null;
    if (responseStatus !== 200) {
      throw new Error(`GUI returned HTTP ${responseStatus}`);
    }
    await page.waitForFunction(() => {
      const button = document.querySelector("#run");
      const status = (document.querySelector("#status")?.textContent || "").toLowerCase();
      return button && !button.disabled && status.includes("server") && status.includes("ready");
    }, null, {
      timeout: 180000,
    });

    if (expectedCommit) {
      await page.waitForFunction((commit) => {
        return document.querySelector("#buildInfo")?.getAttribute("title") === commit;
      }, expectedCommit, { timeout: 30000 });
    }

    documentState = await page.evaluate(() => ({
      title: document.title,
      heading: document.querySelector("h1")?.textContent?.trim() || null,
      bodyText: document.body?.innerText?.slice(0, 5000) || "",
      readyState: document.readyState,
      buildCommit: document.querySelector("#buildInfo")?.getAttribute("title") || null,
      status: document.querySelector("#status")?.textContent?.trim() || null,
    }));
    if (documentState.title !== "Multi-commodity lease strategy") {
      throw new Error(`Unexpected GUI title: ${documentState.title}`);
    }

    if (runSmokeStrategy || runBtcAudit) {
      await page.selectOption('[name="btc_data_source"]', "minute");
      let submittedJobId = null;
      const observedResultResponses = new Map();
      let settleResultResponse;
      const resultResponsePromise = new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error("Timed out waiting for the submitted backtest result")), 15 * 60 * 1000);
        timeout.unref();
        settleResultResponse = (response) => {
          clearTimeout(timeout);
          resolve(response);
        };
      });
      resultResponsePromise.catch(() => {});
      page.on("response", (candidate) => {
        const target = new URL(candidate.url());
        if (target.origin !== origin) return;
        const match = target.pathname.match(/^\/api\/v1\/backtests\/([0-9a-f]{32})\/result$/);
        if (!match) return;
        observedResultResponses.set(match[1], candidate);
        if (match[1] === submittedJobId) settleResultResponse(candidate);
      });
      const submissionResponsePromise = page.waitForResponse((candidate) => {
        const target = new URL(candidate.url());
        return target.origin === origin
          && target.pathname === "/api/v1/backtests"
          && candidate.request().method() === "POST";
      }, { timeout: 120000 });

      // This fresh test context may restore a previous strategy
      // under the deployment identity. Start the fixture from form defaults.
      await page.evaluate(() => {
        form.reset();
        commodityProfiles = {};
        activeCommodity = 'silver';
      });
      const proportions = runBtcAudit ? {
        weight_silver:"0",weight_gold:"0",weight_sp500:"0",weight_btc:"100",weight_treasury:"0"
      } : {
        weight_silver: "30",
        weight_gold: "30",
        weight_sp500: "30",
        weight_treasury: "10",
      };
      for (const [name, value] of Object.entries(proportions)) {
        await page.locator(`[name="${name}"]`).fill(value);
      }
      if (runBtcAudit) {
        await page.locator("#parameterFile").setInputFiles(process.env.KEEP_AND_LEASE_BTC_PRESET);
        await page.waitForFunction(() => document.querySelector('#status')?.textContent?.startsWith('Loaded '));
      }
      await page.locator('[name="portfolio_rebalancing"]').selectOption("daily");
      const invalidControls = await page.locator('#form').evaluate(form =>
        [...form.elements].filter(field => field.willValidate && !field.checkValidity())
          .map(field => ({name:field.name,message:field.validationMessage})));
      if (invalidControls.length) throw new Error('Invalid strategy controls: '+JSON.stringify(invalidControls));
      await page.locator("#run").click();

      const submissionResponse = await submissionResponsePromise;
      if (![200, 202].includes(submissionResponse.status())) {
        throw new Error(`Backtest submission returned HTTP ${submissionResponse.status()}`);
      }
      const submission = await submissionResponse.json();
      if (!/^[0-9a-f]{32}$/.test(submission.job_id || "")) {
        throw new Error("Backtest submission did not return a valid job ID");
      }
      submittedJobId = submission.job_id;
      if (observedResultResponses.has(submittedJobId)) {
        settleResultResponse(observedResultResponses.get(submittedJobId));
      }
      if (expectedCommit && submission.provenance?.engine_commit !== expectedCommit) {
        throw new Error(`Backtest uses commit ${submission.provenance?.engine_commit || "unknown"}, expected ${expectedCommit}`);
      }

      const guiFailurePromise = page.waitForFunction(() => {
        const status = document.querySelector("#status");
        return status?.classList.contains("error") ? status.textContent?.trim() : false;
      }, null, { timeout: 15 * 60 * 1000 }).then((handle) => handle.jsonValue()).then((message) => {
        throw new Error(`GUI strategy run failed: ${message}`);
      });
      const resultResponse = await Promise.race([resultResponsePromise, guiFailurePromise]);
      if (resultResponse.status() !== 200) {
        throw new Error(`Backtest result returned HTTP ${resultResponse.status()}`);
      }
      if (!resultResponse.url().endsWith(`${submission.job_id}/result`)) {
        throw new Error("GUI downloaded a result for a different backtest job");
      }
      const expectedCommodities = runBtcAudit ? ["btc"] : ["gold", "silver", "sp500"];
      const expectedWeights = runBtcAudit ? {btc:1,treasury:0} : { silver: 0.3, gold: 0.3, sp500: 0.3, treasury: 0.1 };
      await Promise.race([page.waitForFunction((names) => {
        const observations = document.querySelector("#obs")?.textContent?.trim();
        const button = document.querySelector("#run");
        return button && !button.disabled && observations && observations !== "--" && names.every((name) => {
          const canvas = document.querySelector(`#commodity-${name}-lease`);
          return canvas && canvas.width > 0 && canvas.height > 0;
        });
      }, expectedCommodities, { timeout: 180000 }), guiFailurePromise]);

      // The result can be large enough for Chromium to evict its response body
      // from the inspector cache. Validate the same data after the application
      // has parsed it and rendered the GUI instead of calling response.json().
      const rendered = await page.evaluate((names) => {
        const numberFromText = (selector) => {
          const text = document.querySelector(selector)?.textContent?.trim() || "";
          const value = Number(text.replaceAll(",", "").replace(/[^0-9.+-]/g, ""));
          return { text, value };
        };
        const weights = Object.fromEntries(["silver", "gold", "sp500", "btc", "treasury"].map((name) => [
          name,
          Number(document.querySelector(`[name="weight_${name}"]`)?.value) / 100,
        ]));
        const headings = [...document.querySelectorAll("#commoditySleeveCharts > .commodity-grid > h2")]
          .map((heading) => heading.textContent?.trim() || "");
        return {
          weights,
          observations: numberFromText("#obs"),
          status: document.querySelector("#status")?.textContent?.trim() || "",
          commodities: names.filter((name) => document.querySelector(`#commodity-${name}-lease`)),
          headings,
        };
      }, expectedCommodities);
      for (const [name, expected] of Object.entries(expectedWeights)) {
        if (Math.abs(Number(rendered.weights[name]) - expected) > 1e-12) {
          throw new Error(`Unexpected rendered ${name} portfolio weight: ${rendered.weights[name]}`);
        }
      }
      if (!(rendered.observations.value > 0)) {
        throw new Error(`Rendered multi-commodity result has invalid observations: ${rendered.observations.text}`);
      }
      if (JSON.stringify(rendered.commodities.sort()) !== JSON.stringify(expectedCommodities)) {
        throw new Error(`Unexpected rendered commodities: ${rendered.commodities.join(", ") || "none"}`);
      }
      const expectedHeadings = runBtcAudit ? ["Bitcoin sleeve"] : ["Gold sleeve", "Silver sleeve", "S&P 500 sleeve"];
      for (const heading of expectedHeadings) {
        if (!rendered.headings.includes(heading)) {
          throw new Error(`Rendered result is missing the ${heading} section`);
        }
      }

      strategy = {
        jobId: submission.job_id,
        cached: Boolean(submission.cached),
        commodities: rendered.commodities,
        weights: rendered.weights,
        observations: rendered.observations.value,
        status: rendered.status,
        renderedLeaseCanvases: expectedCommodities,
      };
      if (runBtcAudit) {
        const evidence = await page.evaluate(async (statusUrl) => {
          const state = await (await fetch(statusUrl)).json();
          const result = plotRangeSource.result;
          const audit = result.audit;
          if (!audit?.datasets?.btc || audit.datasets.btc.rows !== 129599) throw Error('Incomplete BTC audit manifest');
          for (const entry of [audit.datasets.btc.chunks[0], audit.datasets.btc.chunks.at(-1)]) {
            const response = await fetch(audit.base_url+'/btc/'+entry.index);
            if (!response.ok) throw Error('Stored BTC audit chunk is unavailable');
            const chunk = await response.json();
            if (chunk.sha256 !== entry.sha256 || chunk.rows.length !== entry.rows) throw Error('Audit chunk mismatch');
          }
          return {summary:result.summary,execution:result.commodity_sleeves.btc.execution,
            auditRows:audit.datasets.btc.rows,peakRssMiB:state.peak_rss_mb,resultBytes:state.result_size_bytes};
        }, submission.status_url);
        if (evidence.summary.observations !== 129599 || evidence.summary.missing_intervals !== 0
            || Math.abs(evidence.summary.compounded_return-43.733581054241654)>1e-6
            || evidence.execution.zero_volume_fills !== 0
            || !(evidence.peakRssMiB > 0 && evidence.peakRssMiB < 4096)
            || !(evidence.resultBytes > 0 && evidence.resultBytes < 268435456)) {
          throw Error('Full BTC result failed numerical or resource acceptance');
        }
        await page.locator('#plotPeriod').selectOption('range');
        await page.locator('#plotStart').fill('2026-06-06');
        await page.locator('#plotEnd').fill('2026-06-06');
        await page.locator('#applyPlotRange').click();
        await page.locator('#loadAuditDetails').click();
        await page.waitForFunction(() => document.querySelector('#auditStatus')?.textContent?.startsWith('Detailed plots loaded'), null, {timeout:180000});
        const downloadReady=page.waitForEvent('download',{timeout:180000});
        await page.locator('#downloadSpreadsheet').click();
        const download=await downloadReady;
        if (await download.failure()) throw Error('BTC workbook download failed');
        const downloadPath=await download.path();
        evidence.workbookBytes=fs.statSync(downloadPath).size;
        if (evidence.workbookBytes < 1000) throw Error('Empty BTC workbook');
        const cdp=await context.newCDPSession(page);
        await cdp.send('Performance.enable');
        const metrics=await cdp.send('Performance.getMetrics');
        evidence.browserHeapMiB=metrics.metrics.find(item=>item.name==='JSHeapUsedSize')?.value/1024**2;
        strategy.btcAudit=evidence;
        console.log('BTC minute acceptance: '+JSON.stringify({
          commit:expectedCommit,observations:evidence.summary.observations,
          strategyReturnPct:evidence.summary.compounded_return,
          directHoldingReturnPct:evidence.summary.direct_holding_return,
          zeroVolumeFills:evidence.execution.zero_volume_fills,
          peakRssMiB:evidence.peakRssMiB,resultBytes:evidence.resultBytes,
          auditRows:evidence.auditRows,workbookBytes:evidence.workbookBytes,
          browserHeapMiB:evidence.browserHeapMiB,
        }));
        // A fresh, short computation uses the new period controls, not plot cropping.
        const shortStarted=Date.now();
        await page.locator('[name="backtest_start"]').fill('2026-06-25T00:00');
        await page.locator('[name="backtest_end"]').fill('2026-06-26T00:00');
        const shortSubmitted=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/backtests'&&r.request().method()==='POST');
        await page.locator('#run').click();
        const shortResponse=await shortSubmitted;
        if (![200,202].includes(shortResponse.status())) throw Error('Short-period submission failed');
        const shortJob=await shortResponse.json();
        if (Date.parse(shortJob.parameters.backtest_start+'Z')!==Date.UTC(2026,5,25)) throw Error('GUI omitted selected period');
        await page.waitForFunction(()=>!document.querySelector('#run').disabled &&
          Date.parse(plotRangeSource?.result?.backtest_period?.requested_start+'Z')===Date.UTC(2026,5,25),null,{timeout:300000});
        const shortEvidence=await page.evaluate(()=>{
          const r=plotRangeSource.result,fields=r.portfolio_fields;
          return {summary:r.summary,period:r.backtest_period,initialNav:r.portfolio_series[0][fields.indexOf('start_nav')],
            auditRows:r.audit.datasets.btc.rows};
        });
        if(shortEvidence.summary.observations!==1440||shortEvidence.auditRows!==1440||shortEvidence.initialNav!==1||
          shortEvidence.period.actual_start!=='2026-06-25T00:00:00'||shortEvidence.period.actual_end!=='2026-06-26T00:00:00')
          throw Error('Short-period boundaries, initial NAV or audit coverage failed');
        shortEvidence.wallSeconds=(Date.now()-shortStarted)/1000;
        strategy.btcShortPeriod=shortEvidence;
        console.log('BTC selected-period acceptance: '+JSON.stringify(shortEvidence));
      }
    }

    if (runSubsecond) {
      await page.selectOption('[name="btc_data_source"]', 'trade_tape');
      await page.click('#loadTradeExample');
      const resultResponse = page.waitForResponse(r => /\/api\/v1\/backtests\/[0-9a-f]{32}\/result$/.test(new URL(r.url()).pathname), {timeout: 15*60*1000});
      await page.click('#run');
      const response = await resultResponse;
      if (!response.ok()) throw Error('Trade replay result HTTP '+response.status());
      const result = await response.json();
      if (result.result_kind !== 'btc_trade_replay' || result.trade_replay.interval_seconds !== .5 || result.trade_replay.market_events !== 12006 || result.summary.observations !== 600) throw Error('Unexpected 500 ms trade replay coverage');
      if (Math.abs(result.summary.compounded_return - 0.023825048740855337) > 1e-8) throw Error('GCS trade replay differs from local financial result');
      if (result.trade_replay.manifest_sha256 !== '9c05efc03118699303e7a55e14205bed29783683a85c165f99319dd3fabc055d') throw Error('Wrong immutable trade dataset');
      await page.waitForSelector('#tradeReplayResults', {state:'visible'});
      await page.waitForFunction(()=>!document.querySelector('#run').disabled);
      const csvDownload = page.waitForEvent('download');
      await page.click('#tradeReplayCsv');
      const download = await csvDownload;
      const csvPath = path.join(outputDir,'btc-trade-valuations.csv');
      await download.saveAs(csvPath);
      if (fs.readFileSync(csvPath,'utf8').trim().split('\n').length !== 601) throw Error('Valuation CSV lost rows');
      verifiedDownloadPaths.add(new URL(download.url()).pathname);
      const entry=result.audit.datasets.btc_trade_events.chunks[0];
      const auditResponse=await page.evaluate(async url=>{const r=await fetch(url);return {status:r.status,body:await r.json()};},result.audit.base_url+'/btc_trade_events/'+entry.index);
      if(auditResponse.status!==200||auditResponse.body.rows.length!==entry.rows)throw Error('Trade audit chunk failed');
      await page.locator('#tradeReplayNav').hover({position:{x:120,y:100}});
      if(!(await page.locator('#tooltip').isVisible()))throw Error('Trade chart hover failed');
      fs.writeFileSync(path.join(outputDir,'subsecond.json'),JSON.stringify({summary:result.summary,trade_replay:result.trade_replay,csv_rows:600,audit_chunk_rows:entry.rows},null,2));
      // Exercise a true millisecond decision clock with fractional UTC bounds.
      await page.fill('[name="execution_interval_seconds"]','0.001');
      await page.fill('[name="backtest_start"]','2026-06-25T00:00:00.2');
      await page.fill('[name="backtest_end"]','2026-06-25T00:00:01.2');
      const fineResponse=page.waitForResponse(r=>/\/api\/v1\/backtests\/[0-9a-f]{32}\/result$/.test(new URL(r.url()).pathname),{timeout:10*60*1000});
      await page.click('#run');
      const fine=await (await fineResponse).json();
      if(fine.trade_replay?.interval_seconds!==.001||fine.backtest_period.requested_start!=='2026-06-25T00:00:00.200000'||fine.backtest_period.actual_end!=='2026-06-25T00:00:01.200000'||fine.summary.observations<1)throw Error('Millisecond replay or fractional date preservation failed');
      await page.waitForFunction(()=>!document.querySelector('#run').disabled);
      fs.writeFileSync(path.join(outputDir,'millisecond.json'),JSON.stringify({summary:fine.summary,trade_replay:fine.trade_replay},null,2));
      // Invalid coverage is rejected synchronously, before launching a worker.
      const invalid=await page.evaluate(async p=>{p.backtest_end='2026-06-27';const r=await fetch('/api/v1/backtests',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({parameters:p})});return r.status;},result.parameters);
      if(invalid!==400)throw Error('Unsupported trade dates were accepted');
      console.log('Subsecond GUI acceptance passed: 500 ms/GCS equivalence, CSV, audit, hover, and 1 ms fractional window.');
    }

    const sameOriginFailures = failedRequests.filter((request) => {
      try {
        const target = new URL(request.url);
        const optionalRestoreWasAborted = request.method === "GET"
          && target.pathname === "/api/v1/backtests/latest"
          && request.error === "net::ERR_ABORTED";
        const verifiedDownload = request.method === "GET"
          && verifiedDownloadPaths.has(target.pathname) && request.error === "net::ERR_ABORTED";
        return target.origin === origin && !optionalRestoreWasAborted && !verifiedDownload;
      } catch {
        return false;
      }
    });
    if (pageErrors.length) {
      throw new Error(`GUI raised ${pageErrors.length} page error(s)`);
    }
    if (sameOriginFailures.length) {
      throw new Error(`GUI had ${sameOriginFailures.length} failed same-origin request(s)`);
    }
  } catch (error) {
    failure = error;
    if (runBtcAudit) {
      const state = await page.evaluate(() => ({
        status:document.querySelector('#status')?.textContent,
        auditStatus:document.querySelector('#auditStatus')?.textContent,
        observations:document.querySelector('#obs')?.textContent,
        runDisabled:document.querySelector('#run')?.disabled,
      })).catch(() => null);
      console.error('BTC GUI failure state: '+JSON.stringify(state));
    }
    throw error;
  } finally {
    await page.screenshot({
      path: path.join(outputDir, "gui.png"),
      fullPage: false,
    }).catch(() => {});
    fs.writeFileSync(
      path.join(outputDir, "gui-report.json"),
      JSON.stringify(
        {
          url: page.url(),
          responseStatus,
          document: documentState,
          strategy,
          consoleMessages,
          pageErrors,
          failedRequests,
          error: failure ? String(failure.message || failure) : null,
        },
        null,
        2,
      ) + "\n",
    );
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`browser check failed: ${error.message}`);
  const reportPath = path.join(process.env.KEEP_AND_LEASE_OUTPUT_DIR || "", "gui-report.json");
  try {
    const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    if (report.failedRequests?.length) {
      console.error("failed same-origin requests:", JSON.stringify(report.failedRequests, null, 2));
    }
    if (report.pageErrors?.length) {
      console.error("page errors:", JSON.stringify(report.pageErrors, null, 2));
    }
    if (report.consoleMessages?.length) {
      console.error("browser console messages:", JSON.stringify(report.consoleMessages, null, 2));
    }
  } catch {
    // The artifact writer may itself have failed; preserve the original error.
  }
  process.exitCode = 2;
});
