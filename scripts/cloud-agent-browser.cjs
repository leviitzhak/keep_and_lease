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

    if (runSmokeStrategy) {
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

      const proportions = {
        weight_silver: "30",
        weight_gold: "30",
        weight_sp500: "30",
        weight_treasury: "10",
      };
      for (const [name, value] of Object.entries(proportions)) {
        await page.locator(`[name="${name}"]`).fill(value);
      }
      await page.locator('[name="portfolio_rebalancing"]').selectOption("daily");
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
      const expectedCommodities = ["gold", "silver", "sp500"];
      const expectedWeights = { silver: 0.3, gold: 0.3, sp500: 0.3, treasury: 0.1 };
      await page.waitForFunction((names) => {
        const observations = document.querySelector("#obs")?.textContent?.trim();
        const button = document.querySelector("#run");
        return button && !button.disabled && observations && observations !== "--" && names.every((name) => {
          const canvas = document.querySelector(`#commodity-${name}-lease`);
          return canvas && canvas.width > 0 && canvas.height > 0;
        });
      }, expectedCommodities, { timeout: 180000 });

      // The result can be large enough for Chromium to evict its response body
      // from the inspector cache. Validate the same data after the application
      // has parsed it and rendered the GUI instead of calling response.json().
      const rendered = await page.evaluate((names) => {
        const numberFromText = (selector) => {
          const text = document.querySelector(selector)?.textContent?.trim() || "";
          const value = Number(text.replaceAll(",", "").replace(/[^0-9.+-]/g, ""));
          return { text, value };
        };
        const weights = Object.fromEntries(["silver", "gold", "sp500", "treasury"].map((name) => [
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
      const expectedHeadings = ["Gold sleeve", "Silver sleeve", "S&P 500 sleeve"];
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
    }

    const sameOriginFailures = failedRequests.filter((request) => {
      try {
        const target = new URL(request.url);
        const optionalRestoreWasAborted = request.method === "GET"
          && target.pathname === "/api/v1/backtests/latest"
          && request.error === "net::ERR_ABORTED";
        return target.origin === origin && !optionalRestoreWasAborted;
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
  process.exitCode = 2;
});
