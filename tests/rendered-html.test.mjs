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

test("runs the Sites preview against the same-origin server API in strict mode", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const vite = await readFile(new URL("../vite.config.ts", import.meta.url), "utf8");
  const packageJson = JSON.parse(await readFile(
    new URL("../package.json", import.meta.url),
    "utf8",
  ));
  const launcher = await readFile(
    new URL("../scripts/dev-with-api.sh", import.meta.url),
    "utf8",
  );
  assert.match(page, /silver_strategy_gui\.html\?engine=server/);
  assert.match(vite, /"\/api\/v1"/);
  assert.match(vite, /KEEP_AND_LEASE_LOCAL_API_URL/);
  assert.equal(packageJson.scripts.dev, "bash scripts/dev-with-api.sh");
  assert.match(launcher, /python server_main\.py/);
  assert.match(launcher, /\/api\/v1\/health/);
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
  assert.match(html, /exact product decomposition/);
  assert.match(html, /1\+R = Π exp\(gᵢ\)/);
  assert.doesNotMatch(html, /name="enable_slv_leg"/);
  assert.match(html, /function drawBookDecompositions/);
  assert.match(html, /lease_book_compounded_return_pct/);
  assert.match(html, /unextended lease implementations — value/);
  assert.match(html, /lease-underlying-values/);
  assert.match(html, /actual component values by P\(t\)\/P\(0\)/);
  assert.match(html, /Keep book — extended lease \+ short/);
  assert.match(html, /whole portfolio starts at 1/);
  assert.match(html, /initial_replicating_leg_value/);
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

test("exports completed backtests with position and book roll-forward checks", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /function accountingWorkbook/);
  assert.match(html, /holding_ledger/);
  assert.match(html, /Futures value/);
  assert.match(html, /carried at zero after daily settlement/);
  assert.match(html, /book start — holdings sum/);
  assert.match(html, /book end — roll-forward/);
  assert.match(html, /book standalone return \(%\)/);
  assert.match(html, /book contribution to sleeve return \(%\)/);
  assert.match(html, /book external\/rebalancing transfer/);
  assert.match(html, /book internal transfer check/);
  assert.match(html, /Parameters/);
  assert.match(html, /selectedDates\.has\(record\.exit_date\)/);
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
  assert.match(html, /LineLong\(T\)/);
  assert.match(html, /LineShort\(T\)/);
  assert.match(html, /P\(T,r\) = R × M/);
  assert.match(html, /−r − LineShort/);
  assert.match(html, /name="long_line_maturity_1"/);
  assert.match(html, /name="long_line_rate_2"/);
  assert.match(html, /name="short_line_maturity_1"/);
  assert.match(html, /name="short_line_rate_2"/);
  assert.match(html, /Score rate scale/);
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
  assert.match(html, /name="long_pure_maturity_scale_days"/);
  assert.match(html, /name="long_pure_maturity_clip"/);
  assert.match(html, /name="short_pure_maturity_scale_days"/);
  assert.match(html, /name="short_pure_maturity_clip"/);
  assert.match(html, /Pure maturity adjustment/);
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

test("previews long and short parameter-only weighting independently", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /id="previewLongScore"/);
  assert.match(html, /id="previewShortScore"/);
  assert.match(html, /id="scorePreviewDialog"/);
  assert.match(html, /id="scorePreviewIncludeEntry"/);
  assert.match(html, /heatmap colour is the signed parameter-only logit/i);
  assert.match(html, /SCORE_PREVIEW_MAX_DAYS=3652\.5/);
  assert.match(html, /Years to maturity T/);
  assert.match(html, /silver and gold observations reach about 5 years/i);
  assert.match(html, /function drawScoreParameterHeatmap/);
  assert.match(html, /function scorePreviewConfig/);
  assert.match(html, /A<sub>.*<\/sub>\(T,r\) = A<sub>rate<\/sub>/);
  assert.match(html, /q<sub>i<\/sub> = B<sub>i<\/sub>/);
  assert.match(html, /w<sub>i<\/sub> = Q<sub>/);
  assert.match(html, /softmax allocation/);
  assert.match(html, /updateScorePreviewButtons/);
});

test("parameter-only preview matches the canonical long and short multipliers", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  const source = html.slice(
    html.indexOf("function scoreField"),
    html.indexOf("function scoreHeatColor"),
  );
  const values = {
    min_days: 10,
    long_pure_maturity_scale_days: 365,
    long_pure_maturity_clip: 3,
    short_pure_maturity_scale_days: 365,
    short_pure_maturity_clip: 3,
    long_line_maturity_1: 30,
    long_line_rate_1: 0.033,
    long_line_maturity_2: 365,
    long_line_rate_2: 0.4,
    long_relative_strength: 1,
    long_score_rate_scale: 1,
    long_score_adjustment_clip: 3,
    long_pure_maturity_strength: 0.5,
    long_futures_entry_mode: "fixed",
    positive_entry_rate: 0,
    max_futures_treasury_fraction: 50,
    short_line_maturity_1: 30,
    short_line_rate_1: 0.033,
    short_line_maturity_2: 365,
    short_line_rate_2: 0.4,
    short_relative_strength: 1,
    short_score_rate_scale: 1,
    short_score_adjustment_clip: 3,
    short_pure_maturity_strength: 0.5,
    short_futures_entry_mode: "fixed",
    negative_short_start_rate: -0.5,
    max_short_fraction_of_long_leg: 50,
  };
  const form = {
    elements: { namedItem: (name) => ({ value: values[name] }) },
  };
  const scorePreviewConfig = new Function(
    "form",
    `${source}; return scorePreviewConfig;`,
  )(form);
  const long = scorePreviewConfig("long").components(365, 1.4);
  const short = scorePreviewConfig("short").components(365, -1.4);
  assert.ok(Math.abs(long.rateAdjustment - 1) < 1e-12);
  assert.equal(long.pureAdjustment, -0.5);
  assert.ok(Math.abs(long.parameterLogit - 0.5) < 1e-12);
  assert.ok(Math.abs(long.entryBase - 1.4) < 1e-12);
  assert.ok(Math.abs(long.entryLogit - 1.9) < 1e-12);
  assert.ok(Math.abs(short.rateAdjustment - 1) < 1e-12);
  assert.equal(short.pureAdjustment, 0.5);
  assert.ok(Math.abs(short.parameterLogit - 1.5) < 1e-12);
  assert.ok(Math.abs(short.entryBase - 0.9) < 1e-12);
  assert.ok(Math.abs(short.entryLogit - 2.4) < 1e-12);
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
  assert.match(adapter, /Empty response from/);
  assert.match(adapter, /Invalid JSON from/);
  assert.match(adapter, /result without a summary/);
  assert.match(adapter, /function runBrowserRequest/);
  assert.match(adapter, /config\.requestedEngine === "auto"/);
  assert.match(html, /if\(data\.result==null\)/);
  assert.match(html, /!data\.summary/);
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

test("downloads a formula-driven daily holdings and reconciliation spreadsheet", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /id="downloadSpreadsheet"/);
  assert.match(html, /function downloadSpreadsheet\(\)/);
  assert.match(html, /application\/vnd\.openxmlformats-officedocument\.spreadsheetml\.sheet/);
  assert.match(html, /One row per holding interval/);
  assert.match(html, /Daily Holdings/);
  assert.match(html, /matched USD rate \(%\)/);
  assert.match(html, /lease-book return in underlying \(%\)/);
  assert.match(html, /Portfolio return reconciliation difference \(pp\)/);
  assert.match(html, /<f>/);
  assert.match(html, /fullCalcOnLoad="1"/);
  assert.match(html, /plotRangeSource\.portfolioSeries\.filter\(row=>dateInPlotRange/);
  assert.match(html, /keep-and-lease-portfolio-/);
  assert.match(html, /Preparing spreadsheet/);
  assert.match(html, /document\.body\.appendChild\(link\)/);
  assert.doesNotMatch(html, /\.\.\.keys\.map\(\(\)=>22\)/);
  const dockerignore = await readFile(
    new URL("../.dockerignore", import.meta.url),
    "utf8",
  );
  assert.match(dockerignore, /^!public\/fflate\.js$/m);
  const webDockerfile = await readFile(
    new URL("../Dockerfile.web", import.meta.url),
    "utf8",
  );
  assert.match(
    webDockerfile,
    /^COPY .*public\/fflate\.js .*\.\/public\/$/m,
  );
});

test("actual held futures charts aggregate by side and retain contract hover details", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /Held long futures — weighted/);
  assert.match(html, /Held short futures — weighted/);
  assert.match(html, /meta\.heldDetails/);
  assert.match(html, /matched_usd_rate_pct/);
  assert.doesNotMatch(html, /label:\(side==='short'\?'Short ':'Long '\)\+symbol/);
});

test("daily holdings builder emits contract columns and auditable formulas", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  const source = html.slice(
    html.indexOf("function spreadsheetRows"),
    html.indexOf("async function downloadSpreadsheet"),
  );
  const fields = [
    "date", "exit_date", "interval_return_pct", "slv_price", "slv_exit_price",
    "slv_weight_pct", "replicating_leg_value", "treasury_weight_pct",
    "treasury_position_price_index", "futures_treasury_value", "lease_book_value",
    "keep_book_value", "lease_book_underlying_value", "keep_book_underlying_value",
  ];
  const series = [["2020-01-01", "2020-01-02", 1, 100, 102, 50, 0.51, 50, 100.01, 0.5, 1.01, 0, 0.9901960784, 0]];
  const sleeve = {
    product_label: "Silver", holding_label: "Replicating fund", fields, series,
    held_futures_diagnostics: [[{
      side: "long", symbol: "SIH20", weight_pct: 50, price: 103,
      spot_price: 100, premium_pct: 3, matched_usd_rate_pct: 1.5,
      lease_pct: -1.5, maturity_days: 60,
    }]],
  };
  const context = {
    result: {
      portfolio_fields: ["date", "start_date", "nav", "interval_return_pct", "silver_contribution_pct"],
      portfolio: { weights: { silver: 1 } }, commodity_sleeves: { silver: sleeve },
      daily_attribution: [{ date: "2020-01-02", assets: { silver: { effective_weight_pct: 100 } } }],
    },
    sleeves: { silver: { series: sleeve.series } },
  };
  const makeRows = new Function("plotRangeSource", "num", "xlsxColumn", `${source}; return spreadsheetRows;`)(
    context,
    (value) => { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null; },
    (index) => { let name = ""; for (let n = index + 1; n; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + (n - 1) % 26) + name; return name; },
  );
  const result = makeRows({ rows: [["2020-01-02", "2020-01-01", 1.01, 1, 1]], start: "2020-01-02", end: "2020-01-02" });
  assert.equal(result.dailyRows.length, 2);
  assert.ok(result.dailyRows[0].includes("Instrument 1 — name"));
  assert.ok(result.dailyRows[0].includes("Instrument 1 — matched USD rate (%)"));
  assert.equal(
    result.dailyRows[1][result.dailyRows[0].indexOf("Instrument 1 — name")],
    "SIH20",
  );
  const formulaIndex = result.dailyRows[0].indexOf("Silver — reconstructed daily return (%)");
  assert.match(result.dailyRows[1][formulaIndex].formula, /^=\(\(1\+/);
});

test("shows precise proxy expense and compounded portfolio attribution", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /name="slv_expense"[^>]*step="0\.01"/);
  assert.match(html, /function drawPortfolioComparisons/);
  assert.match(html, /direct_unrebalanced_compounded_return_pct/);
  assert.match(html, /_attributed_factor_compounded_return_pct/);
  assert.match(html, /never rebalanced/);
  assert.match(html, /portfolio value \(initial = 1\)/);
  assert.match(html, /f\('start_date'\)/);
  assert.match(html, /Longest aligned holding interval/);
});

test("embedded GUI script is syntactically valid", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  const match = html.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(match);
  assert.doesNotThrow(() => new Function(match[1]));
});
