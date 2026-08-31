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

test("reinitializes and applies plot periods to every visible data source", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /let plotRangeSource=null/);
  assert.match(html, /plotRangeSource\?\.result!==last/);
  assert.match(
    html,
    /last\.portfolio_series=plotRangeSource\.portfolioSeries\.filter/,
  );
  assert.match(
    html,
    /sleeve\.series=source\.series\.filter/,
  );
  assert.match(
    html,
    /sleeve\.statistics_points=source\.statisticsPoints\.filter/,
  );
  assert.match(
    html,
    /sleeve\.rate_change_attribution_points=source\.rateChangePoints\.filter/,
  );
  assert.match(
    html,
    /last\.treasury_rate_change_points=plotRangeSource\.treasuryRateChangePoints\.filter/,
  );
});

test("restores the latest durable run and renders every rate-change curve", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /\/api\/v1\/backtests\/latest/);
  assert.doesNotMatch(html, /\/api\/strategy-state/);
  assert.match(html, /treasury_rate_change_points/);
  assert.match(html, /Frozen-curve rate-change return vs\. maturity/);
  assert.match(html, /Yield-change return vs\. maturity/);
  assert.match(html, /No observations are available for this graph/);
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
  assert.match(html, /name="long_line_maturity_1"/);
  assert.match(html, /name="long_line_rate_2"/);
  assert.match(html, /name="short_line_maturity_1"/);
  assert.match(html, /name="short_line_rate_2"/);
  assert.match(html, /configured rate scale/);
  assert.match(
    html,
    /name="long_score_rate_scale"[^>]*min="0\.01"[^>]*step="0\.01"/,
  );
  assert.match(
    html,
    /name="short_score_rate_scale"[^>]*min="0\.01"[^>]*step="0\.01"/,
  );
  assert.match(html, /function scoreDiagnosticTable/);
  assert.match(html, /name="long_pure_maturity_strength"/);
  assert.match(html, /name="short_pure_maturity_strength"/);
  assert.match(html, /Pure maturity multiplier/);
  assert.doesNotMatch(html, /name="long_maturity_line_intercept"/);
  assert.doesNotMatch(html, /name="short_maturity_line_intercept"/);
  assert.match(html, /id="dailyAttributionPanel"/);
  assert.match(html, /id="dailyMarketCurves"/);
  assert.match(html, /function inspectMarketDay/);
  assert.match(html, /id="generalScatterCharts"/);
  assert.match(html, /Treasury market scatters/);
  assert.match(html, /Treasury yield vs\. maturity/);
  assert.match(html, /installParameterHelp/);
  assert.match(html, /PARAMETER_HELP/);
  assert.match(html, /commonPortfolioCharts'\)\.innerHTML=''/);
  assert.match(html, /name="long_line_rate_1"[^>]*step="0\.001"/);
  assert.match(html, /function drawDailyAttribution/);
  assert.match(html, /Effective start-of-day weight/);
});

test("bundles Python dependencies required by the browser worker", async () => {
  const worker = await readFile(
    new URL("../public/backtest-worker-v12.js", import.meta.url),
    "utf8",
  );
  assert.match(worker, /"maturity_scoring\.py"/);
  assert.match(worker, /"rate_change_attribution\.py"/);
  assert.match(worker, /"market_data_store\.py"/);
  assert.match(worker, /sys\.path\.insert\(0, "\/data"\)/);
});

test("loads authenticated market assets sequentially with retries", async () => {
  const worker = await readFile(
    new URL("../public/backtest-worker-v12.js", import.meta.url),
    "utf8",
  );
  assert.match(worker, /index < DATA_FILES\.length/);
  assert.match(worker, /credentials: "same-origin"/);
  assert.match(worker, /Could not load \$\{name\}/);
  assert.doesNotMatch(worker, /Promise\.all\(DATA_FILES/);
});

test("uses the server adapter while preserving the Pyodide worker fallback", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  const adapter = await readFile(
    new URL("../public/backtest-worker-v13.js", import.meta.url),
    "utf8",
  );
  assert.match(html, /backtest-worker-v13\.js/);
  assert.match(adapter, /\/api\/v1\/backtests/);
  assert.match(adapter, /\/api\/v1\/inspections/);
  assert.match(adapter, /new Worker\("\/backtest-worker-v12\.js/);
  assert.match(adapter, /requestedEngine === "pyodide"/);
  assert.match(adapter, /requestedEngine === "server"/);
});

test("displays the application version and deployed commit", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  const buildInfo = JSON.parse(await readFile(
    new URL("../public/build-info.json", import.meta.url),
    "utf8",
  ));
  assert.match(html, /fetch\('\/build-info\.json'/);
  assert.match(html, /Version 1\.3/);
  assert.equal(buildInfo.version, "1.3");
  assert.match(buildInfo.commit, /^(?:[0-9a-f]{40}|unknown)$/);
});

test("downloads and loads strategy parameters as JSON", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, />Download JSON</);
  assert.match(html, />Load JSON</);
  assert.match(html, /keep-and-lease-parameters\.json/);
  assert.match(html, /schema_version:PARAM_SCHEMA_VERSION,parameters:values\(\)/);
  assert.match(html, /The selected file is not valid JSON/);
  assert.match(html, /contains no recognized strategy parameters/);
  assert.match(html, /e\.target\.value=''/);
});
