import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const developmentPreviewMeta =
  /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

test("renders development preview metadata", async () => {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  const response = await worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );

  assert.equal(response.status, 200);
  assert.match(
    response.headers.get("content-type") ?? "",
    /^text\/html\b/i,
  );
  assert.match(await response.text(), developmentPreviewMeta);
});

test("documents data corrections and the daily attribution formulas", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /Data corrections/);
  assert.match(html, /Affected return date/);
  assert.match(html, /19 Mar 1980/);
  assert.match(html, /How the daily-return decomposition is calculated/);
  assert.match(html, /futures basis contribution/);
  assert.match(html, /NAV\[t\+1\]/);
});

test("orders shared plots before commodity plots and synchronizes chart dates", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.ok(
    html.indexOf("Common portfolio plots") < html.indexOf("Plots by commodity"),
  );
  assert.match(html, /id="commonPortfolioCharts"/);
  assert.match(html, /function ensureLegend/);
  assert.match(html, /selectedDate=date/);
  assert.match(html, /organizeResultCharts\(\)/);
  assert.match(html, /bindTooltips\(\)/);
});

test("shows exact maturity-line formulas and dynamic hierarchical attribution", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /Maturity-line allocation formulas/);
  assert.match(html, /LineLong\(Dᵢ\)/);
  assert.match(html, /LineShort\(Dᵢ\)/);
  assert.match(html, /AddedRelativeᵢ/);
  assert.match(html, /−Lᵢ − LineShort/);
  assert.match(html, /above its line adds a positive score/);
  assert.match(html, /id="dailyAttributionPanel"/);
  assert.match(html, /id="dailyMarketCurves"/);
  assert.match(html, /function inspectMarketDay/);
  assert.match(html, /id="generalScatterCharts"/);
  assert.match(html, /Treasury market scatters/);
  assert.match(html, /function drawDailyAttribution/);
  assert.match(html, /Effective start-of-day weight/);
});
