import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

test("BTC-only preset import preserves its execution and cost profile", async () => {
  const html=await readFile(new URL("../public/silver_strategy_gui.html",import.meta.url),"utf8");
  const source=html.split('\n').find(line=>line.startsWith('function applyParameters('));
  const preset=JSON.parse(await readFile(new URL("../strategies/research-btc-long-gradual-1m-fee-1bp.json",import.meta.url),"utf8"));
  const fields=new Map(Object.keys(preset.parameters).map(name=>[name,{value:''}]));
  const context={commodityProfiles:{},COMMODITIES:['silver','gold','sp500','btc'],
    LEG_FIELDS:['slv_expense','futures_contract_type','execution_model','trading_fee_bps'],
    form:{elements:{namedItem:name=>fields.get(name)}},loadCommodity:()=>{}};
  vm.runInNewContext(source,context);
  context.applyParameters(preset.parameters);
  assert.equal(context.commodityProfiles.btc.trading_fee_bps,'1');
  assert.equal(context.commodityProfiles.btc.execution_model,'observed');
  assert.deepEqual(context.commodityProfiles.btc,preset.parameters.commodity_parameters.btc);
  assert.ok(context.commodityProfiles.silver);
});

test("Run waits for saved-result restoration as well as server readiness", async () => {
  const html=await readFile(new URL("../public/silver_strategy_gui.html",import.meta.url),"utf8");
  assert.match(html, /<button id="run"[^>]*\bdisabled\b/);
  const handler=html.split('\n').find(line=>line.startsWith('worker.onmessage='));
  let finishRestore;
  const context={worker:{},workerReady:false,button:{disabled:true},status:{},
    backtestRuns:{start:()=>{}},parametersReady:Promise.resolve(),resultsReady:new Promise(resolve=>{finishRestore=resolve}),
    $:()=>({}),pending:new Map()};
  vm.runInNewContext(handler,context);
  const ready=context.worker.onmessage({data:{type:'ready',engine:'server'}});
  await Promise.resolve();
  assert.equal(context.workerReady,false);
  assert.equal(context.button.disabled,true);
  finishRestore(true);
  await ready;
  assert.equal(context.workerReady,true);
  assert.equal(context.button.disabled,false);
  assert.match(context.status.textContent,/Last saved run restored/);
});

test("late durable results preserve edits and untouched sessions still restore", async () => {
  const html=await readFile(new URL("../public/silver_strategy_gui.html",import.meta.url),"utf8");
  const source=html.split('\n').find(line=>line.startsWith('async function restoreLastResult('));
  for(const editDuringLoad of [true,false]) {
    let finishBody,bodyStarted;
    const started=new Promise(resolve=>{bodyStarted=resolve});
    const body=new Promise(resolve=>{finishBody=resolve});
    const prior={summary:{observations:2}},saved={summary:{observations:129599}};
    const applied=[],shown=[];
    const context={parameterRevision:0,last:prior,computationApiUrl:async path=>path,
      fetch:async path=>path.endsWith('/latest')
        ? {ok:true,status:200,json:async()=>({result_url:'/saved',parameters:{weight_btc:100}})}
        : {ok:true,status:200,json:()=>{bodyStarted();return body}},
      normalizePortfolioResult:value=>value,applyParameters:value=>applied.push(value),
      showSummary:value=>shown.push(value),draw:()=>{},console};
    vm.runInNewContext(source,context);
    const restored=context.restoreLastResult();
    await started;
    if(editDuringLoad)context.parameterRevision++;
    finishBody(saved);
    assert.equal(await restored,!editDuringLoad);
    assert.equal(context.last,editDuringLoad?prior:saved);
    assert.equal(applied.length,editDuringLoad?0:1);
    assert.equal(shown.length,editDuringLoad?0:1);
  }
});

test("large minute charts retain every point without argument-limit errors", async () => {
  const html=await readFile(new URL("../public/silver_strategy_gui.html",import.meta.url),"utf8");
  const start=html.indexOf('function lineChart('),end=html.indexOf('\nfunction ',start+1);
  const bounds=html.split('\n').filter(line=>/^function array(?:Minimum|Maximum)\(/.test(line)).join('\n');
  const drawing=Object.fromEntries(['scale','clearRect','fillText','beginPath','moveTo','lineTo','stroke','arc','fill','save','translate','rotate','restore'].map(name=>[name,()=>{}]));
  const canvas={style:{},parentElement:{clientWidth:800,querySelector:()=>({textContent:'Large minute chart'})},getContext:()=>drawing};
  const rows=Array.from({length:129600},(_,i)=>['2026-06-06',i,-i,2*i]);
  const charts=new Map();
  const context={canvas,rows,charts,matchMedia:()=>({matches:false}),devicePixelRatio:1,ensureLegend:()=>{},num:Number,fmt:String,hover:()=>{},leave:()=>{}};
  vm.runInNewContext(bounds+'\n'+html.slice(start,end)+"\nlineChart(canvas,rows,[{i:1},{i:2},{i:3}],'value',{zero:false});",context);
  const rendered=charts.get(canvas);
  assert.equal(rendered.rows,rows);
  assert.ok(rendered.scales.left.low < -129599);
  assert.ok(rendered.scales.left.high > 2*129599);
});

test("every numeric default satisfies its browser range and step constraints", async () => {
  const html = await readFile(new URL("../public/silver_strategy_gui.html", import.meta.url), "utf8");
  for (const tag of html.matchAll(/<input\b[^>]*>/g)) {
    const attributes = Object.fromEntries([...tag[0].matchAll(/([\w-]+)="([^"]*)"/g)].map(match=>[match[1],match[2]]));
    if (attributes.type !== "number" || attributes.value === undefined) continue;
    const value=Number(attributes.value), minimum=Number(attributes.min??0), step=Number(attributes.step??1);
    assert.ok(Number.isFinite(value), attributes.name);
    if (attributes.min !== undefined) assert.ok(value>=minimum, attributes.name+" minimum");
    if (attributes.max !== undefined) assert.ok(value<=Number(attributes.max), attributes.name+" maximum");
    if (attributes.step !== "any") {
      const offset=(value-(attributes.min!==undefined?minimum:value))/step;
      assert.ok(Math.abs(offset-Math.round(offset))<1e-8, attributes.name+" step mismatch");
    }
  }
});

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
  assert.match(html, /lease_book_underlying_daily_return_pct/);
  assert.match(html, /unextended lease book — value in underlying/);
  assert.match(html, /lease-underlying-values/);
  assert.match(html, /Commodity-quoted values divide each dollar value/);
  assert.match(html, /Keep book — extended lease \+ short/);
  assert.match(html, /effective start-of-interval proportion/);
  assert.match(html, /initial_replicating_leg_value/);
  assert.match(html, /function histogramChart/);
  assert.match(html, /lease-book daily-return distribution/);
  assert.match(html, /NAV reconstruction check/);
  assert.doesNotMatch(html, /id="'\+prefix\+'-book-standalone"/);
  assert.doesNotMatch(html, /id="'\+prefix\+'-book-factors"/);
  assert.doesNotMatch(html, /id="'\+prefix\+'-lease-standalone"/);
  assert.doesNotMatch(html, /id="'\+prefix\+'-lease-factors"/);
});

test("exposes BTC source-resolution execution intervals and causal Treasury guidance", async () => {
  const html = await readFile(
    new URL("../public/silver_strategy_gui.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /name="execution_interval_seconds"/);
  assert.match(html, /Binance BTC\/USDT/);
  assert.match(html, /No historical USDT\/USD conversion is applied/);
  assert.match(html, /6 June–3 September 2026 UTC/);
  assert.match(html, /one minute \(60 seconds\)/);
  assert.doesNotMatch(html, /currently packaged history is daily/);
  assert.match(html, /whole multiple of the detected BTC data resolution/);
  assert.match(html, /latest observable yield/);
  assert.match(html, /no future daily mark or time interpolation/);
  assert.match(html, /calendarDate=String\(date\)\.slice\(0,10\)/);
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
  assert.match(html, /backtest-workbook-v1\.js/);
  assert.match(html, /KeepLeaseWorkbook\.buildSheets/);
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

test("uses the server adapter with deployment-aware browser initialization", async () => {
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
  assert.doesNotMatch(adapter, /function runBrowserRequest/);
  assert.match(adapter, /config\.browserFallback === false/);
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
  assert.match(dockerignore, /^!public\/backtest-workbook-v1\.js$/m);
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
  const bounds=html.split('\n').filter(line=>/^function array(?:Minimum|Maximum)\(/.test(line)).join('\n');
  const makeRows = new Function("plotRangeSource", "num", "xlsxColumn", `${bounds}\n${source}; return spreadsheetRows;`)(
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

test("backtest UTC boundaries persist and older presets clear a previous range", async()=>{
  const html=await readFile(new URL('../public/silver_strategy_gui.html',import.meta.url),'utf8');
  for(const name of ['backtest_start','backtest_end'])assert.match(html,new RegExp('name="'+name+'" type="datetime-local"'));
  const source=html.split('\n').find(line=>line.startsWith('function applyParameters('));
  const fields=new Map(['backtest_start','backtest_end'].map(name=>[name,{value:''}]));
  const context={commodityProfiles:{},COMMODITIES:['silver','btc'],LEG_FIELDS:[],
    form:{elements:{namedItem:name=>fields.get(name)}},loadCommodity:()=>{}};
  vm.runInNewContext(source,context);
  context.applyParameters({backtest_start:'2026-06-25T03:00:00+03:00',backtest_end:'2026-06-26'});
  assert.equal(fields.get('backtest_start').value,'2026-06-25T00:00:00');
  assert.equal(fields.get('backtest_end').value,'2026-06-26T00:00:00');
  context.applyParameters({backtest_start:'2026-06-25T03:00:00.123+03:00'});
  assert.equal(fields.get('backtest_start').value,'2026-06-25T00:00:00.123');
  context.applyParameters({});
  assert.equal(fields.get('backtest_start').value,'');
  assert.equal(fields.get('backtest_end').value,'');
  const normalize=html.split('\n').find(line=>line.startsWith('function normalizePortfolioResult('));
  const ctx={};vm.runInNewContext(normalize,ctx);
  const period={actual_start:'2026-06-25',actual_end:'2026-06-26'};
  assert.equal(ctx.normalizePortfolioResult({commodity_sleeves:{btc:{}},backtest_period:period}).backtest_period,period);
});


test("backtest boundaries are portfolio settings rather than commodity profiles", async()=>{
  const html=await readFile(new URL('../public/silver_strategy_gui.html',import.meta.url),'utf8');
  const globalLine=html.split('\n').find(line=>line.startsWith('const GLOBAL_FIELDS='));
  const legLine=html.split('\n').find(line=>line.startsWith('const LEG_FIELDS='));
  const capture=html.split('\n').find(line=>line.startsWith('function captureCommodity('));
  const fields=[{name:'backtest_start',value:'2026-06-25T00:00'},
    {name:'backtest_end',value:'2026-06-26T00:00'},{name:'min_days',value:'10'}];
  fields.namedItem=name=>fields.find(f=>f.name===name);
  const ctx={form:{elements:fields},commodityProfiles:{},activeCommodity:'btc'};
  vm.runInNewContext(globalLine+'\n'+legLine+'\n'+capture+'\ncaptureCommodity();',ctx);
  assert.equal(ctx.commodityProfiles.btc.min_days,'10');
  assert.equal(Object.hasOwn(ctx.commodityProfiles.btc,'backtest_start'),false);
  assert.equal(Object.hasOwn(ctx.commodityProfiles.btc,'backtest_end'),false);
});
