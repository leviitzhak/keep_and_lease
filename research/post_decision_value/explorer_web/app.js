"use strict";
const $ = (id) => document.getElementById(id);
const DAY = 86400000;
const app = {
  token: null,
  boot: null,
  market: null,
  evaluation: null,
  surface: null,
  replay: null,
  busy: false,
  orderId: 0,
};
const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (value, digits = 6) =>
  value == null
    ? "Unavailable"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
const date = (value) =>
  new Date(value).toISOString().replace("T", " ").replace("Z", " UTC");
const pretty = (value) => JSON.stringify(value, null, 2);
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : app.busy ? "busy" : "";
}
async function api(path, data) {
  const options =
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Explorer-Token": app.token,
          },
          body: JSON.stringify(data),
        };
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok)
    throw Error(result.error || `Request failed (${response.status})`);
  return result;
}
async function run(message, fn) {
  if (app.busy) return;
  app.busy = true;
  const buttons = [
    ...document.querySelectorAll("button,input,select,textarea"),
  ];
  const states = buttons.map((b) => b.disabled);
  buttons.forEach((b) => (b.disabled = true));
  notice(message);
  try {
    await fn();
  } catch (error) {
    notice(error.message, true);
  } finally {
    app.busy = false;
    buttons.forEach((b, i) => (b.disabled = states[i]));
    $("generate").disabled = !$("simEnabled").checked;
    $("exportReplay").disabled = !app.replay;
    $("notice").classList.remove("busy");
  }
}
function chooseTab(name) {
  document
    .querySelectorAll(".tab")
    .forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document
    .querySelectorAll(".panel")
    .forEach((p) => p.classList.toggle("active", p.id === name + "Tab"));
}
function invalidate() {
  app.evaluation = null;
  app.surface = null;
  app.replay = null;
  [
    "predicted",
    "reference",
    "errorValue",
    "boundaryValue",
    "toyValue",
    "replayValue",
    "fillCount",
    "finalCash",
  ].forEach((id) => ($(id).textContent = "—"));
  $("heatmap").className = "empty";
  $("heatmap").textContent = "Inputs changed. Build a new surface.";
  $("marketChart").replaceChildren();
  $("stateDetail").textContent = "";
  $("closingDetail").textContent = "";
  $("replayChart").replaceChildren();
  $("timeline").textContent = "Inputs changed. Run a new replay.";
  $("replayTail").textContent = "";
  $("replayStatus").textContent = "Not run for this state";
  $("exportReplay").disabled = true;
  $("admission").textContent = "Inputs changed. Evaluate to check admission.";
}
function currentRequest() {
  const state = {
    time: Date.parse($("time").value + "Z"),
    horizon_ms: Math.round(Number($("horizon").value) * DAY),
    balances: { BTC: Number($("btc").value), USD: Number($("usd").value) },
    collateral: {
      BTC: Number($("btcCollateral").value),
      USD: Number($("usdCollateral").value),
    },
    positions: {},
    flows: JSON.parse($("flows").value),
    orders: [],
    action: {
      kind: $("actionKind").value,
      orders: [],
      targets: $("targets")
        .value.split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    },
  };
  document.querySelectorAll("[data-inventory]").forEach((row) => {
    const quantity = Number(row.querySelector("[data-quantity]").value);
    if (quantity)
      state.positions[row.dataset.inventory] = {
        quantity,
        basis: Number(row.querySelector("[data-basis]").value),
      };
  });
  [...$("orders").rows].forEach((row) => {
    const values = {};
    row
      .querySelectorAll("[data-field]")
      .forEach((input) => (values[input.dataset.field] = input.value));
    values.quantity = Number(values.quantity);
    values.limit = Number(values.limit);
    if (values.status === "candidate") {
      delete values.status;
      state.action.orders.push(values);
    } else state.orders.push(values);
  });
  if (!Number.isFinite(state.time) || !Number.isFinite(state.horizon_ms))
    throw Error("Enter a valid UTC time and remaining horizon.");
  return {
    market_id: app.market.id,
    state,
    seed: Number($("replaySeed").value),
  };
}
function renderCheckpoint(info) {
  $("checkpointName").textContent =
    info.id === "published-diagnostic"
      ? "Treasury scalar · diagnostic"
      : "Local scalar checkpoint";
  $("targetLabel").textContent = info.target;
  $("acceptance").textContent = info.status;
  $("manifest").textContent = pretty(info);
}
function option(value, label) {
  return `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`;
}
function populateMarket(m) {
  app.market = m;
  invalidate();
  const d = m.defaults;
  $("time").value = new Date(d.time).toISOString().slice(0, 23);
  $("time").min = new Date(m.start).toISOString().slice(0, 23);
  $("time").max = new Date(m.decision_end).toISOString().slice(0, 23);
  $("horizon").value = d.horizon_ms / DAY;
  $("btc").value = d.balances.BTC;
  $("usd").value = d.balances.USD;
  $("btcCollateral").value = d.collateral.BTC;
  $("usdCollateral").value = d.collateral.USD;
  $("flows").value = "[]";
  $("orders").replaceChildren();
  $("targets").value = "";
  $("actionKind").value = "wait";
  const options = Object.keys(m.instruments)
    .map((s) => option(s, s))
    .join("");
  $("chartSymbol").innerHTML = options;
  $("surfaceSymbol").innerHTML = options;
  $("inventory").innerHTML = Object.entries(m.instruments)
    .filter(([, i]) => i.payoff !== "spot")
    .map(
      ([s, i]) =>
        `<div data-inventory="${escapeHtml(s)}"><span class="small">${escapeHtml(s)} · ${escapeHtml(i.payoff)} · matures ${date(i.expiry).slice(0, 10)}</span><div class="two"><label>Quantity<input data-quantity type="number" step="${i.lot}" value="0"></label><label>Cost basis<input data-basis type="number" step="${i.tick}" value="${i.payoff === "treasury" ? 100 : 100000}"></label></div></div>`,
    )
    .join("");
  $("sourceTag").textContent =
    m.source.source_kind.replaceAll("_", " ") + " · " + m.rows + " prints";
  $("simulationReceipt").textContent =
    `Selected ${m.rows} trade prints and ${m.funding_events} funding events. ${date(m.start)} → ${date(m.decision_end)}; tail through ${date(m.label_end)}. ID ${m.id.slice(0, 16)}`;
  $("surfaceP").value = "97,98,99";
}
function addOrder(values = {}) {
  const symbol = values.symbol || $("chartSymbol").value;
  const ins = app.market.instruments[symbol];
  const price =
    app.evaluation?.observable.market[symbol]?.price ??
    (ins.payoff === "treasury" ? 100 : 100000);
  const row = document.createElement("tr");
  const id = values.identifier || `order-${++app.orderId}`;
  row.innerHTML = `<td><input data-field="identifier" aria-label="Order ID" value="${escapeHtml(id)}"></td><td><select data-field="symbol" aria-label="Order instrument">${Object.keys(
    app.market.instruments,
  )
    .map((s) => option(s, s))
    .join(
      "",
    )}</select></td><td><input data-field="quantity" aria-label="Signed native quantity" type="number" step="any" value="${escapeHtml(values.quantity ?? 25)}"></td><td><input data-field="limit" aria-label="Limit price" type="number" step="any" value="${escapeHtml(values.limit ?? price)}"></td><td><select data-field="status" aria-label="Order state"><option value="candidate">Candidate</option><option value="working">Working</option><option value="pending">Pending create</option></select></td><td><button aria-label="Remove order">×</button></td>`;
  row.querySelector("[data-field=symbol]").value = symbol;
  row.querySelector("[data-field=status]").value = values.status || "candidate";
  row.querySelector("button").onclick = () => {
    row.remove();
    invalidate();
  };
  $("orders").append(row);
  $("actionKind").value = "create";
}
function svgChart(container, points, lines = [], ylabel = "Price") {
  const width = 900,
    height = 210,
    left = 65,
    right = 22,
    top = 20,
    bottom = 30;
  const usable = points.filter(
    (p) => Number.isFinite(p.x) && Number.isFinite(p.y),
  );
  if (!usable.length) {
    container.innerHTML =
      '<div class="empty">No received observations for this instrument.</div>';
    return;
  }
  const xs = usable.map((p) => p.x),
    ys = [...usable.map((p) => p.y), ...lines.map((l) => l.y)];
  let xmin = Math.min(...xs),
    xmax = Math.max(...xs),
    ymin = Math.min(...ys),
    ymax = Math.max(...ys);
  if (xmin === xmax) {
    xmin -= 3600000;
    xmax += 3600000;
  }
  let pad = Math.max((ymax - ymin) * 0.12, Math.abs(ymin) * 0.0001, 0.001);
  ymin -= pad;
  ymax += pad;
  const x = (v) => left + ((v - xmin) / (xmax - xmin)) * (width - left - right),
    y = (v) =>
      height - bottom - ((v - ymin) / (ymax - ymin)) * (height - top - bottom);
  let s = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(ylabel)} over time"><title>${escapeHtml(ylabel)}; received market data only on the state chart</title>`;
  for (let i = 0; i < 4; i++) {
    const value = ymin + ((ymax - ymin) * i) / 3;
    s += `<line x1="${left}" y1="${y(value)}" x2="${width - right}" y2="${y(value)}" stroke="#e9eee5"/><text x="${left - 8}" y="${y(value) + 3}" text-anchor="end">${fmt(value, 2)}</text>`;
  }
  lines.forEach((l) => {
    s += `<line x1="${left}" x2="${width - right}" y1="${y(l.y)}" y2="${y(l.y)}" stroke="#b77a30" stroke-dasharray="5 5"/><text x="${width - right}" y="${y(l.y) - 5}" text-anchor="end">${escapeHtml(l.label)}</text>`;
  });
  s += `<polyline points="${usable.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")}" fill="none" stroke="#16836b" stroke-width="2"/>`;
  usable.forEach(
    (p) =>
      (s += `<circle cx="${x(p.x)}" cy="${y(p.y)}" r="${usable.length > 500 ? 1 : 3}" fill="#16836b"><title>${escapeHtml(date(p.x))}: ${fmt(p.y)}</title></circle>`),
  );
  s += `<text x="${left}" y="${height - 6}">${escapeHtml(date(xmin).slice(0, 16))}</text><text x="${width - right}" y="${height - 6}" text-anchor="end">${escapeHtml(date(xmax).slice(0, 16))} UTC</text></svg>`;
  container.innerHTML = s;
}
function renderMarketChart() {
  if (!app.evaluation) return;
  const obs = app.evaluation.observable,
    s = $("chartSymbol").value;
  const req = currentRequest();
  const lines = [...req.state.orders, ...req.state.action.orders]
    .filter((o) => o.symbol === s)
    .map((o) => ({
      y: o.limit,
      label: `${o.quantity > 0 ? "Buy" : "Sell"} ${o.quantity} @ ${o.limit}`,
    }));
  svgChart(
    $("marketChart"),
    obs.history
      .filter((t) => t.symbol === s)
      .map((t) => ({ x: t.received, y: t.price })),
    lines,
  );
  const latest = obs.market[s];
  $("marketCaption").textContent = latest
    ? `${s} · ${date(latest.time)} print · received ${date(latest.received)} · age ${fmt((obs.time - latest.received) / 1000, 2)}s · size ${fmt(latest.amount)}`
    : "No received trade";
}
async function evaluate() {
  const result = await api("/api/evaluate", currentRequest());
  app.evaluation = result;
  $("predicted").textContent = fmt(result.prediction.value);
  $("predictionNote").textContent =
    result.prediction.unavailable ||
    result.prediction.validation ||
    result.prediction.reason;
  $("reference").textContent = fmt(result.reference.value);
  $("referenceNote").textContent = result.reference.kind;
  $("errorValue").textContent = fmt(result.signed_error);
  $("admission").textContent =
    `${result.prediction.admissible ? "Admitted" : "Rejected"} · ${result.prediction.reason}`;
  $("boundaryValue").textContent = result.liquidation.done
    ? fmt(result.liquidation.utility)
    : "Incomplete";
  $("boundaryNote").textContent =
    result.liquidation.reason || result.interpretation;
  $("closingDetail").textContent = pretty(result.liquidation);
  $("toyValue").textContent = fmt(result.toy_optimum?.value);
  $("toyNote").textContent =
    result.toy_optimum?.scope ||
    "Unavailable for this state or dataset. This is a separate oracle, not a matching diagnostic label.";
  $("stateDetail").textContent = pretty({
    observable: result.observable,
    instruments: result.instruments,
    benchmark: result.benchmark,
    source: result.source,
    feature_sha256: result.prediction.feature_sha256,
  });
  renderMarketChart();
  notice(
    result.prediction.admissible
      ? "State evaluated. Prediction, reference and boundary retain their separate meanings."
      : "Instruction rejected: " + result.prediction.reason,
    !result.prediction.admissible,
  );
}
function renderSurface() {
  if (!app.surface) return;
  const cells = app.surface.cells,
    key = $("surfaceMetric").value,
    qs = [...new Set(cells.map((c) => c.quantity))],
    ps = [...new Set(cells.map((c) => c.price))],
    values = cells
      .filter((c) => c.admissible && c[key] != null)
      .map((c) => c[key]);
  const lo = Math.min(...values),
    hi = Math.max(...values);
  let html =
    "<table><thead><tr><th>Qty / price</th>" +
    ps.map((p) => `<th>${fmt(p, 4)}</th>`).join("") +
    "</tr></thead><tbody>";
  qs.forEach((q) => {
    html += `<tr><th>${q === 0 ? "Wait" : fmt(q, 4)}</th>`;
    ps.forEach((p) => {
      const c = cells.find((c) => c.quantity === q && c.price === p),
        v = c[key],
        level =
          hi === lo ? 2 : Math.min(5, Math.floor(((v - lo) / (hi - lo)) * 5));
      const cls = !c.admissible
        ? "infeasible"
        : v == null
          ? "unavailable"
          : `level${level}`;
      html += `<td class="${cls}" title="${escapeHtml(c.reason + (c.unavailable ? " · " + c.unavailable : ""))}">${!c.admissible ? "×" : v == null ? "—" : fmt(v, 6)}</td>`;
    });
    html += "</tr>";
  });
  html += "</tbody></table>";
  $("heatmap").className = "heatmap";
  $("heatmap").innerHTML = html;
  const best = app.surface.ranking[0];
  $("surfaceNote").textContent =
    `${app.surface.reference_scope}. ${best ? `Top predicted candidate: qty ${best.quantity}, limit ${best.price}, V̂ ${fmt(best.value)}. Ranking is not a policy-performance claim.` : "No supported model predictions."}`;
}
function renderTimeline() {
  if (!app.replay) return;
  const mode = $("eventFilter").value;
  let rows;
  if (mode === "decisions")
    rows = app.replay.decisions.map((d) => ({
      time: d.time,
      visibility: "received",
      kind: `decision · ${fmt(d.remaining_ms / DAY, 6)} days left`,
      description: pretty(d.instruction),
    }));
  else if (mode === "fills")
    rows = app.replay.fills.map((f) => ({
      time: f.time,
      visibility: "hidden",
      kind: "fill",
      description: `${f.symbol} · ${f.quantity} @ ${f.price} · ${fmt(f.remaining)} remaining`,
    }));
  else
    rows = app.replay.events
      .filter((e) => mode === "all" || e.visibility === mode)
      .map((e) => {
        const cash =
          e.visibility === "received"
            ? e.observed_balances_after
            : e.balances_after;
        const positions =
          e.visibility === "received"
            ? e.observed_positions_after
            : e.positions_after;
        return {
          time: e.time,
          visibility: e.visibility,
          kind: e.kind + (e.report_kind ? " / " + e.report_kind : ""),
          description: e.instruction
            ? JSON.stringify(e.instruction)
            : e.funding
              ? JSON.stringify(e.funding)
              : [
                  e.symbol,
                  e.trade_id,
                  e.price != null ? fmt(e.price) : "",
                  cash
                    ? `USD ${fmt(cash.USD, 2)} / BTC ${fmt(cash.BTC, 6)}`
                    : "",
                  positions && Object.keys(positions).length
                    ? "Inventory " + JSON.stringify(positions)
                    : "",
                ]
                  .filter(Boolean)
                  .join(" · "),
        };
      });
  const shown = rows.slice(0, 500);
  $("timeline").innerHTML =
    `<p class="small">Showing ${shown.length} of ${rows.length} rows. Export includes the full bounded trace.</p><table><thead><tr><th>Time · UTC</th><th>Visibility</th><th>Event</th><th>Detail</th></tr></thead><tbody>${shown.map((r) => `<tr><td>${escapeHtml(date(r.time))}</td><td><span class="badge ${r.visibility === "hidden" ? "amber" : ""}">${escapeHtml(r.visibility)}</span></td><td>${escapeHtml(r.kind)}</td><td>${escapeHtml(r.description)}</td></tr>`).join("")}</tbody></table>`;
}
function downloadJson(name, value) {
  const url = URL.createObjectURL(
    new Blob([pretty(value)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
function csv(id) {
  const text = $(id).value.trim();
  if (!text) throw Error("Enter comma-separated values.");
  const values = text.split(",").map((v) => Number(v.trim()));
  if (values.some((v) => !Number.isFinite(v)))
    throw Error("Every grid value must be finite.");
  return [...new Set(values)];
}
async function loadFixture() {
  const result = await api("/api/market", {
    kind: "fixture",
    id: $("dataset").value,
  });
  populateMarket(result);
  await evaluate();
  const price = app.evaluation.observable.market.BILL.price;
  $("surfaceP").value = [price - 0.5, price, price + 0.5]
    .map((p) => p.toFixed(2))
    .join(",");
  document.querySelector("[data-basis]").value = price;
}
function wire() {
  document
    .querySelectorAll(".tab")
    .forEach((b) => (b.onclick = () => chooseTab(b.dataset.tab)));
  $("stateTab").addEventListener("change", (event) => {
    if (!["dataset", "chartSymbol", "surfaceMetric"].includes(event.target.id))
      invalidate();
  });
  $("dataset").onchange = () =>
    run("Loading development fixture…", async () => {
      if ($("dataset").value === "selected-market") return;
      $("simEnabled").checked = false;
      $("simStatus").textContent = "OFF";
      await loadFixture();
    });
  $("evaluate").onclick = () =>
    run("Evaluating the immediate post-state…", evaluate);
  $("addOrder").onclick = () => {
    addOrder();
    invalidate();
  };
  $("chartSymbol").onchange = renderMarketChart;
  $("boundary").onclick = () => {
    $("horizon").value = 0;
    invalidate();
  };
  $("maturity").onclick = () => {
    $("horizon").value = Math.max(
      0,
      (app.market.decision_end - Date.parse($("time").value + "Z")) / DAY,
    );
    invalidate();
  };
  $("time").onchange = () => {
    const remaining =
      (app.market.decision_end - Date.parse($("time").value + "Z")) / DAY;
    $("horizon").value = Math.max(
      0,
      Math.min(Number($("horizon").value), remaining),
    );
    invalidate();
  };
  $("exampleCash").onclick = () =>
    run("Restoring cash-only example…", async () => {
      populateMarket(app.market);
      await evaluate();
    });
  $("exampleBuy").onclick = () =>
    run("Preparing a purchase-and-hold example…", async () => {
      populateMarket(app.market);
      await evaluate();
      const price = app.evaluation.observable.market.BILL.price;
      addOrder({ symbol: "BILL", quantity: 25, limit: price });
      invalidate();
      await evaluate();
    });
  $("exampleOwned").onclick = () =>
    run("Preparing owned inventory at the boundary…", async () => {
      populateMarket(app.market);
      await evaluate();
      const price = app.evaluation.observable.market.BILL.price,
        fee = app.market.instruments.BILL.fee_bps;
      const row = document.querySelector('[data-inventory="BILL"]');
      row.querySelector("[data-quantity]").value = 25;
      row.querySelector("[data-basis]").value = price;
      $("usd").value = 10000 - 25 * price * (1 + fee / 10000);
      $("horizon").value = 0;
      invalidate();
      await evaluate();
    });
  $("surface").onclick = () =>
    run("Evaluating the bounded quantity / price grid…", async () => {
      app.surface = await api("/api/surface", {
        ...currentRequest(),
        symbol: $("surfaceSymbol").value,
        quantities: csv("surfaceQ"),
        prices: csv("surfaceP"),
      });
      renderSurface();
      notice("Surface ready. Hover infeasible cells for admission reasons.");
    });
  $("surfaceMetric").onchange = renderSurface;
  $("simEnabled").onchange = () =>
    run("Changing market source…", async () => {
      $("simStatus").textContent = $("simEnabled").checked
        ? "ON · NOT GENERATED"
        : "OFF";
      if (!$("simEnabled").checked) {
        $("dataset").value = app.boot.cases[0].id;
        await loadFixture();
      } else
        notice(
          "Simulation enabled. Press Generate to create and select a path.",
        );
    });
  $("generate").onclick = () =>
    run("Generating a reproducible synthetic path…", async () => {
      const configuration = {
        ...app.boot.simulation_defaults,
        enabled: $("simEnabled").checked,
        seed: Number($("simSeed").value),
        universe: $("simUniverse").value,
        trend: $("simTrend").value,
        volatility_annual: Number($("simVol").value),
        initial_spot: Number($("simSpot").value),
        rate_annual: Number($("simRate").value),
        premium_annual: Number($("simPremium").value),
        liquidity: Number($("simLiquidity").value),
        funding_daily_bps: Number($("simFunding").value),
        fee_bps: Number($("simFees").value),
        future_payoff: $("simPayoff").value,
        step_hours: Number($("simStep").value),
      };
      const m = await api("/api/market", { kind: "simulation", configuration });
      populateMarket(m);
      setSelectedMarket("Synthetic market · selected");
      $("simStatus").textContent = "ON · GENERATED";
      await evaluate();
      notice(
        "Synthetic path selected. Its market law is outside checkpoint validation.",
      );
    });
  $("exportMarket").onclick = () =>
    run("Exporting verified dataset…", async () => {
      downloadJson(
        "treasury-market.json",
        await api("/api/market/export", { market_id: app.market.id }),
      );
      notice(
        "Dataset exported with configuration, native instruments, tape and SHA-256.",
      );
    });
  $("importMarket").onclick = () =>
    run("Verifying market bundle…", async () => {
      const file = $("marketFile").files[0];
      if (!file || file.size > 7000000)
        throw Error("Choose a market JSON file under 7 MB.");
      const bundle = JSON.parse(await file.text());
      populateMarket(await api("/api/market", { kind: "import", bundle }));
      setSelectedMarket("Imported dataset · selected");
      $("simEnabled").checked =
        bundle.metadata.source_kind === "synthetic_market";
      $("simStatus").textContent = $("simEnabled").checked
        ? "ON · IMPORTED"
        : "OFF";
      await evaluate();
    });
  $("replay").onclick = () =>
    run("Replaying exact events inside the declared budgets…", async () => {
      app.replay = await api("/api/replay", {
        ...currentRequest(),
        policy: $("replayPolicy").value,
        max_decisions: Number($("replayCap").value),
      });
      const r = app.replay,
        o = r.outcome;
      $("replayValue").textContent = o.done ? fmt(o.utility) : "Incomplete";
      $("replayStatus").textContent = o.done
        ? o.failed
          ? "Completed · constraint failure"
          : "Completed · single realized path"
        : `No utility label · ${o.reason}`;
      $("fillCount").textContent = r.fills.length;
      $("decisionCount").textContent =
        `${r.decisions.length} policy decisions · ${r.events.length} exchange/report events`;
      $("finalCash").textContent = o.done
        ? `${fmt(o.balances.USD, 2)} / ${fmt(o.balances.BTC, 6)}`
        : "Unresolved";
      svgChart(
        $("replayChart"),
        r.events
          .filter((e) => e.balances_after)
          .map((e) => ({ x: e.time, y: e.balances_after.USD })),
        [],
        "Hidden USD cash",
      );
      renderTimeline();
      $("replayTail").textContent = pretty(o);
      notice(
        o.done
          ? "Replay complete. Closing tail is shown separately."
          : `Replay stopped: ${o.reason}. Incomplete outcomes have no value label.`,
      );
    });
  $("eventFilter").onchange = renderTimeline;
  $("exportReplay").onclick = () =>
    downloadJson("treasury-replay.json", app.replay);
  $("selectCheckpoint").onclick = () =>
    run("Loading checkpoint…", async () => {
      renderCheckpoint(
        await api("/api/checkpoint/select", { id: $("checkpoints").value }),
      );
      invalidate();
      notice("Checkpoint loaded. Evaluate the state again.");
    });
  $("downloadCheckpoint").onclick = () =>
    run("Downloading immutable bundle and verifying SHA-256…", async () => {
      const r = await api("/api/checkpoint/download", {});
      renderCheckpoint(r.checkpoint);
      $("checkpoints").value = "published-diagnostic";
      invalidate();
      notice(
        `Verified ${r.bytes.toLocaleString()} bytes and cached the published bundle.`,
      );
    });
  $("importCheckpoint").onclick = () =>
    run("Verifying and loading tensor-only local checkpoint…", async () => {
      const f = $("checkpointFile").files[0],
        sha = $("checkpointHash").value.trim().toLowerCase();
      if (!f || f.size > 2000000 || !/^[a-f0-9]{64}$/.test(sha))
        throw Error(
          "Choose a .pt file under 2 MB and enter its expected SHA-256.",
        );
      const bytes = new Uint8Array(await f.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      renderCheckpoint(
        await api("/api/checkpoint/import", {
          base64: btoa(binary),
          sha256: sha,
        }),
      );
      if (![...$("checkpoints").options].some((o) => o.value === "user"))
        $("checkpoints").add(
          new Option("Loaded local scalar checkpoint", "user"),
        );
      $("checkpoints").value = "user";
      invalidate();
      notice("Local checkpoint loaded. Acceptance is unverified.");
    });
  $("exportSession").onclick = () => {
    try {
      downloadJson("treasury-state.json", {
        schema: "explorer-state-v1",
        ...currentRequest(),
        checkpoint: app.evaluation?.checkpoint || null,
        evaluation: app.evaluation,
      });
    } catch (e) {
      notice(e.message, true);
    }
  };
}
function setSelectedMarket(label) {
  let item = [...$("dataset").options].find(
    (o) => o.value === "selected-market",
  );
  if (!item) {
    item = new Option(label, "selected-market");
    $("dataset").add(item);
  }
  item.textContent = label;
  $("dataset").value = "selected-market";
}
async function start() {
  try {
    app.boot = await api("/api/bootstrap");
    app.token = app.boot.token;
    renderCheckpoint(app.boot.checkpoint);
    $("dataset").innerHTML = app.boot.cases
      .map((c) =>
        option(
          c.id,
          `${c.category.replaceAll("_", " ")} · ${c.split} · ${c.id.split("-").at(-1)}`,
        ),
      )
      .join("");
    $("checkpoints").innerHTML = app.boot.checkpoints
      .map((c) => option(c.id, c.label))
      .join("");
    wire();
    await run("Loading the offline development fixture…", loadFixture);
  } catch (e) {
    notice(`Startup failed: ${e.message}`, true);
  }
}
start();
