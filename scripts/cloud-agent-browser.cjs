#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const webUri = process.env.KEEP_AND_LEASE_WEB_URI;
  const token = process.env.KEEP_AND_LEASE_ID_TOKEN;
  const outputDir = process.env.KEEP_AND_LEASE_OUTPUT_DIR;
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

  let responseStatus = null;
  try {
    const response = await page.goto(`${origin}/?engine=server`, {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });
    responseStatus = response?.status() ?? null;
    await page.waitForLoadState("networkidle", { timeout: 30000 }).catch(() => {});
    await page.screenshot({
      path: path.join(outputDir, "gui.png"),
      fullPage: true,
    });
    const documentState = await page.evaluate(() => ({
      title: document.title,
      heading: document.querySelector("h1")?.textContent?.trim() || null,
      bodyText: document.body?.innerText?.slice(0, 5000) || "",
      readyState: document.readyState,
    }));
    fs.writeFileSync(
      path.join(outputDir, "gui-report.json"),
      JSON.stringify(
        {
          url: page.url(),
          responseStatus,
          document: documentState,
          consoleMessages,
          pageErrors,
          failedRequests,
        },
        null,
        2,
      ) + "\n",
    );
    if (responseStatus !== 200) {
      throw new Error(`GUI returned HTTP ${responseStatus}`);
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(`browser check failed: ${error.message}`);
  process.exitCode = 2;
});
