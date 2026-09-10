/* Durable server jobs. Closing this page never cancels a submitted execution. */
(function (global) {
  'use strict';

  const keptStorageKey = 'keep-and-lease:kept-backtests:v1';
  function readKeptRuns() {
    try {
      const raw = global.localStorage?.getItem(keptStorageKey);
      const value = raw ? JSON.parse(raw) : [];
      return new Set(Array.isArray(value) ? value.filter(x => typeof x === 'string') : []);
    } catch (_) { return new Set(); }
  }
  function writeKeptRuns(values) {
    try { global.localStorage?.setItem(keptStorageKey, JSON.stringify([...values])); } catch (_) {}
  }

  function numberField(result, name) {
    const index = Array.isArray(result?.fields) ? result.fields.indexOf(name) : -1;
    return index >= 0 ? index : null;
  }
  function drawMiniChart(canvas, rows, specs) {
    if (!canvas || !rows?.length || !specs?.length) return;
    const parent = canvas.parentElement;
    const width = Math.max(300, parent?.clientWidth || 640), height = 220;
    const dpr = Math.min(global.devicePixelRatio || 1, 1.5);
    canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    ctx.scale(dpr, dpr); ctx.clearRect(0, 0, width, height);
    const margin = {l: 64, r: 14, t: 18, b: 34};
    const values = specs.flatMap(spec => rows.map(row => Number(spec.value(row))).filter(Number.isFinite));
    if (!values.length) return;
    let low = Math.min(...values), high = Math.max(...values);
    if (low === high) { low -= Math.max(1, Math.abs(low) * .05); high += Math.max(1, Math.abs(high) * .05); }
    const x = i => margin.l + i / Math.max(1, rows.length - 1) * (width - margin.l - margin.r);
    const y = v => margin.t + (high - v) / (high - low) * (height - margin.t - margin.b);
    ctx.strokeStyle = '#d0d5dd'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(margin.l, margin.t); ctx.lineTo(margin.l, height - margin.b); ctx.lineTo(width - margin.r, height - margin.b); ctx.stroke();
    ctx.fillStyle = '#667085'; ctx.font = '11px system-ui';
    ctx.fillText(high.toLocaleString(undefined, {maximumFractionDigits: 3}), 4, margin.t + 4);
    ctx.fillText(low.toLocaleString(undefined, {maximumFractionDigits: 3}), 4, height - margin.b + 4);
    const strokes = ['#175cd3', '#b54708', '#027a48'];
    specs.forEach((spec, si) => {
      ctx.strokeStyle = strokes[si % strokes.length]; ctx.lineWidth = 1.6; ctx.beginPath();
      let started = false;
      rows.forEach((row, i) => { const v = Number(spec.value(row)); if (!Number.isFinite(v)) return; const px=x(i), py=y(v); if (!started) {ctx.moveTo(px,py); started=true;} else ctx.lineTo(px,py); });
      if (started) ctx.stroke();
    });
    const legend = specs.map((s, i) => `${i + 1}. ${s.label}`).join('   ');
    ctx.fillStyle = '#475467'; ctx.fillText(legend, margin.l, height - 8);
    canvas.onmousemove = event => {
      const rect = canvas.getBoundingClientRect();
      const i = Math.max(0, Math.min(rows.length - 1, Math.round((event.clientX - rect.left - margin.l) / Math.max(1, width - margin.l - margin.r) * Math.max(1, rows.length - 1))));
      const row = rows[i];
      const valuesText = specs.map(s => `${s.label}: ${s.format ? s.format(s.value(row)) : Number(s.value(row)).toLocaleString()}`).join(' · ');
      canvas.title = `${row[0]} · ${valuesText}`;
    };
  }

  function renderReplayDiagnostics(root, data) {
    const old = root.querySelector?.('#replayExecutionDiagnostics');
    if (old) old.remove();
    if (data?.result_kind !== 'btc_trade_replay' || !Array.isArray(data.series) || !data.series.length) return;
    const document = root.ownerDocument;
    const section = document.createElement('section'); section.id = 'replayExecutionDiagnostics'; section.className = 'backtest-run';
    const heading = document.createElement('strong'); heading.textContent = 'Replay execution diagnostics'; section.append(heading);
    const meta = document.createElement('p');
    const replay = data.trade_replay || {};
    const ratio = Number(replay.min_collateralization_ratio);
    meta.textContent = `Actual filled turnover: ${Number(replay.turnover_usd || 0).toLocaleString(undefined,{maximumFractionDigits:2})} USD · fills: ${Number(replay.fills || 0).toLocaleString()}` +
      (Number.isFinite(ratio) ? ` · minimum cash/futures collateral ratio: ${ratio.toFixed(6)}` : '') +
      (replay.collateral_breach_count ? ` · collateral breaches: ${replay.collateral_breach_count}` : ' · no collateral breach recorded');
    section.append(meta);
    const fi = numberField(data, 'futures_notional_usd'), ti = numberField(data, 'target_futures_notional_usd');
    const freei = numberField(data, 'free_collateral_usd'), turni = numberField(data, 'turnover_usd');
    if (fi !== null && (ti !== null || freei !== null)) {
      const title = document.createElement('p'); title.textContent = 'Futures target, actual collateral and free collateral (USD)'; section.append(title);
      const canvas = document.createElement('canvas'); section.append(canvas);
      const specs = [{label:'Actual futures', value:r=>r[fi]}];
      if (ti !== null) specs.push({label:'Target futures', value:r=>r[ti]});
      if (freei !== null) specs.push({label:'Free collateral', value:r=>r[freei]});
      drawMiniChart(canvas, data.series, specs);
    }
    if (turni !== null) {
      const title = document.createElement('p'); title.textContent = 'Actual simulated fill volume per plotted interval (USD)'; section.append(title);
      const canvas = document.createElement('canvas'); section.append(canvas);
      const rows = data.series.map((row, i) => [row[0], Math.max(0, Number(row[turni] || 0) - Number(i ? data.series[i-1][turni] || 0 : 0))]);
      drawMiniChart(canvas, rows, [{label:'Executed volume', value:r=>r[1]}]);
    }
    root.append(section);
  }

  global.createBacktestRuns = function ({root, apiUrl, onResult, onParameters, onSelect = () => {}, includeBenchmarks = false}) {
    const document = root.ownerDocument;
    const jobs = new Map();
    const kept = readKeptRuns();
    let showAll = kept.size === 0;
    let selected = null, generation = 0, loaded = null, loading = null;
    let nextCursor = null, refreshing = false, timer = null, stopped = false;
    let benchmarksLoaded = false;
    const active = job => ['queued', 'running'].includes(job.status);
    const resumable = job => ['failed', 'cancelled'].includes(job.status) && job.parameters?.btc_data_source === 'trade_tape';
    const extendable = job => job.status === 'completed' && !job.is_benchmark && job.parameters?.btc_data_source === 'trade_tape';
    const node = (tag, text) => { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; return el; };
    const message = node('p'); message.setAttribute('role', 'status');
    const list = node('div'); list.className = 'backtest-run-list';
    const controls = node('div');
    const button = (text, action) => {
      const el = node('button', text); el.type = 'button';
      el.onclick = async () => { el.disabled = true; try { await action(); } catch (error) { message.textContent = error.message; } finally { el.disabled = false; } };
      return el;
    };
    const more = button('Older backtests', () => refresh(true)); more.hidden = true;
    const visibility = button('Show all runs', () => { showAll = !showAll; render(); });
    controls.append(button('Refresh runs', () => refresh()), visibility, more);
    const viewing = node('p', 'Select a completed run to display its results.'); viewing.id = 'viewingBacktest';
    viewing.setAttribute('role', 'status');
    root.append(controls, message, list, viewing);
    async function request(path, options = {}) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), path.endsWith('/result') ? 120000 : 30000);
      try {
        const response = await fetch(await apiUrl(path), {
          credentials: 'include', cache: 'no-store', ...options, signal: controller.signal,
        });
        const data = await response.json();
        if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Backtest request failed (HTTP ' + response.status + ').');
        return data;
      } finally { clearTimeout(timeout); }
    }
    function keep(id, value) {
      if (value) kept.add(id); else kept.delete(id);
      writeKeptRuns(kept);
      if (kept.size) showAll = false;
      else showAll = true;
      render();
    }
    function visible(job) { return showAll || !kept.size || job.is_benchmark || active(job) || selected === job.job_id || kept.has(job.job_id); }
    function render() {
      list.replaceChildren();
      visibility.textContent = showAll || !kept.size ? (kept.size ? 'Show kept runs' : 'All runs shown') : 'Show all runs';
      visibility.disabled = !kept.size;
      const ordered = [...jobs.values()].sort((a, b) => b.created_at - a.created_at || b.job_id.localeCompare(a.job_id));
      let shown = 0;
      for (const job of ordered) {
        if (!visible(job)) continue;
        shown++;
        const row = node('article'); row.className = 'backtest-run'; row.dataset.jobId = job.job_id;
        row.setAttribute('aria-label', 'Backtest ' + job.job_id);
        const p = job.parameters || {};
        const assets = Object.keys(p).filter(key => key.startsWith('weight_') && Number(p[key]) > 0).map(key => key.slice(7)).join(', ');
        row.append(node('strong', job.title || job.status + ' · ' + (assets || 'Strategy') + ' · ' + new Date(job.created_at * 1000).toLocaleString()));
        row.append(node('p', (p.backtest_start || 'Default start') + ' → ' + (p.backtest_end || 'Default end') +
          ' · ' + (p.execution_interval_seconds || 86400) + ' s · ' + (p.btc_data_source || 'daily') +
          (p.trade_ordering ? ' · ' + p.trade_ordering : '') + ' · ' + job.job_id.slice(0, 8)));
        const elapsed = Math.round((job.elapsed_seconds || 0) / 60);
        const heartbeat = active(job) && job.heartbeat_at ? ' · heartbeat ' + Math.max(0, Math.round(Date.now() / 1000 - job.heartbeat_at)) + ' s ago' : '';
        row.append(node('p', (job.error || job.detail || job.stage) + ' · elapsed ' + elapsed + ' min' + heartbeat));
        if (active(job)) {
          const progress = node('progress'); progress.max = 100;
          progress.setAttribute('aria-label', 'Replay progress for ' + job.job_id.slice(0, 8));
          const match = (job.detail || '').match(/\(([0-9.]+)%\)/);
          if (match) progress.value = Math.min(100, Math.max(0, Number(match[1])));
          row.append(progress);
        }
        const selectButton = button(job.status === 'completed' ? 'View results' : active(job) ? 'Follow progress' : 'View details', () => select(job.job_id));
        selectButton.setAttribute('aria-pressed', String(selected === job.job_id));
        row.append(selectButton, button('Use parameters', () => onParameters(structuredClone(p))));
        if (!job.is_benchmark) row.append(button(kept.has(job.job_id) ? 'Remove from saved view' : 'Keep in saved view', () => keep(job.job_id, !kept.has(job.job_id))));
        if (active(job)) row.append(button(job.cancellation_requested ? 'Cancellation requested' : 'Cancel', () => mutate(job.job_id, 'DELETE')));
        if (resumable(job)) row.append(button('Resume checkpoint', () => resume(job.job_id)));
        if (extendable(job)) row.append(button('Extend to form end', () => extend(job.job_id)));
        if (selected === job.job_id) {
          const details = node('div'); details.id = 'selectedBacktestDetails';
          details.setAttribute('role', 'status');
          details.append(node('strong', 'Selected backtest · ' + job.status));
          details.append(node('p', 'Run ID: ' + job.job_id));
          if (job.stage) details.append(node('p', 'Stage: ' + job.stage));
          if (job.detail) details.append(node('p', 'Last progress: ' + job.detail));
          if (job.error) details.append(node('p', 'Error: ' + job.error));
          if (extendable(job)) details.append(node('p', 'To continue this run, set a later Backtest period End above and choose Extend to form end. The parent result stays immutable. Moving the start earlier requires a fresh run unless an earlier compatible checkpoint is separately available.'));
          if (!active(job) && job.status !== 'completed') {
            details.append(node('p', 'This run has stopped. No completed result is available.'));
            if (resumable(job)) details.append(node('p', 'Use Resume checkpoint to request continuation. The server checks whether a compatible checkpoint is available.'));
          }
          row.append(details);
          if (job.status !== 'completed') viewing.textContent = (active(job) ? 'Following ' : 'Selected ' + job.status + ' backtest ') +
            job.job_id.slice(0, 8) + '. Existing charts remain from the last displayed completed result.';
        }
        list.append(row);
      }
      more.hidden = !nextCursor;
      if (!jobs.size) message.textContent = 'No saved backtests yet. Run strategy to start one.';
      else if (!shown) message.textContent = 'No kept backtests in the default view. Use Show all runs to choose runs to keep.';
    }
    async function loadSelected() {
      const job = jobs.get(selected);
      if (!job || job.status !== 'completed' || loaded === selected || loading === selected) return;
      const id = selected, revision = generation;
      loading = id; viewing.textContent = 'Loading results for ' + id.slice(0, 8) + '…';
      try {
        const data = await request(job.result_url || '/api/v1/backtests/' + id + '/result');
        if (revision !== generation || selected !== id || stopped) return;
        await onResult(data, job);
        renderReplayDiagnostics(root, data);
        loaded = id;
        viewing.textContent = 'Viewing ' + (job.title || 'completed backtest ' + id.slice(0, 8) + ' · ' + new Date(job.created_at * 1000).toLocaleString()) + '. Form edits do not change these saved results.';
      } catch (error) {
        if (revision === generation) { viewing.textContent = 'Result could not be loaded. Select View results to retry.'; message.textContent = error.message; }
      } finally { if (loading === id) loading = null; }
    }
    async function select(id, reveal = true) {
      selected = id; generation++; onSelect(jobs.get(id)); render();
      if (reveal) document.getElementById?.('selectedBacktestDetails')?.scrollIntoView({block: 'nearest'});
      await loadSelected();
    }
    async function refresh(older = false) {
      if (refreshing || stopped) return;
      refreshing = true;
      try {
        const cursor = older ? nextCursor : null;
        const page = await request('/api/v1/backtests?limit=50' + (cursor ? '&before=' + encodeURIComponent(cursor) : ''));
        for (const job of page.jobs) jobs.set(job.job_id, job);
        if (includeBenchmarks && !benchmarksLoaded) {
          try {
            const published = await request('/api/v1/benchmarks');
            for (const job of published.jobs) jobs.set(job.job_id, job);
            benchmarksLoaded = true;
          } catch (error) { message.textContent = 'Published benchmarks could not be loaded: ' + error.message; }
        }
        const seen = new Set(page.jobs.map(job => job.job_id));
        for (const job of [...jobs.values()]) if (!job.is_benchmark && !seen.has(job.job_id) && (active(job) || job.job_id === selected)) {
          jobs.set(job.job_id, await request('/api/v1/backtests/' + job.job_id));
        }
        if (older || !nextCursor) nextCursor = page.next_cursor;
        message.textContent = 'Saved server backtests · refreshed ' + new Date().toLocaleTimeString();
        render();
        if (!selected) {
          const running = [...jobs.values()].find(active);
          if (running) { selected = running.job_id; generation++; onSelect(running); render(); }
        }
        await loadSelected();
      } catch (error) { message.textContent = 'Could not refresh runs: ' + error.message + ' Saved jobs continue in the background.'; }
      finally { refreshing = false; }
    }
    async function submit(parameters) {
      let job;
      try {
        job = await request('/api/v1/backtests', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({schema_version: 1, parameters})});
      } catch (error) {
        void refresh();
        throw Error(error.message + ' Check the run list before retrying if the submission response was lost.');
      }
      jobs.set(job.job_id, job); kept.add(job.job_id); writeKeptRuns(kept); showAll = false;
      void select(job.job_id, false);
      message.textContent = 'Backtest ' + job.job_id.slice(0, 8) + ' saved. You may close this page or submit another strategy.';
      return job;
    }
    async function mutate(id, method, suffix = '') {
      const job = await request('/api/v1/backtests/' + id + suffix, {method});
      jobs.set(id, job); render(); return job;
    }
    async function resume(id) {
      const job = await mutate(id, 'POST', '/resume');
      loaded = null; void select(id); return job;
    }
    async function extend(id) {
      const parent = jobs.get(id);
      if (!extendable(parent)) throw Error('Only a completed BTC trade replay can be extended.');
      const form = document.getElementById?.('form');
      const end = form?.elements?.namedItem?.('backtest_end')?.value;
      if (!end) throw Error('Set Backtest period End to a later time before extending this run.');
      const prior = parent.parameters?.backtest_end;
      if (prior && Date.parse(end) <= Date.parse(prior)) throw Error('Backtest period End must be later than the completed run end.');
      const child = await request('/api/v1/backtests/' + id + '/extend', {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({backtest_end:end}),
      });
      jobs.set(child.job_id, child); kept.add(child.job_id); writeKeptRuns(kept); showAll = false;
      loaded = null; void select(child.job_id, false);
      message.textContent = 'Extension ' + child.job_id.slice(0,8) + ' saved from ' + id.slice(0,8) + '. The parent result remains unchanged.';
      return child;
    }
    async function tick() {
      await refresh();
      if (!stopped) timer = setTimeout(tick, 5000);
    }
    function start() { stopped = false; void tick(); }
    function stop() { stopped = true; generation++; clearTimeout(timer); }
    return {start, stop, submit, resume, extend, select, refresh};
  };

  function setupRuntimeUsability() {
    const document = global.document;
    if (!document?.querySelectorAll) return;

    const charts = [...document.querySelectorAll('.chart')];
    let syncing = false;
    charts.forEach(chart => chart.addEventListener('scroll', () => {
      if (syncing) return;
      const max = chart.scrollWidth - chart.clientWidth; if (max <= 0) return;
      const fraction = chart.scrollLeft / max; syncing = true;
      charts.forEach(other => { const om = other.scrollWidth - other.clientWidth; if (other !== chart && om > 0) other.scrollLeft = fraction * om; });
      syncing = false;
    }, {passive:true}));

    const originalHistogram = global.histogramChart;
    if (typeof originalHistogram === 'function') global.histogramChart = function(canvas, values, color) {
      originalHistogram(canvas, values, color);
      const data = (values || []).map(Number).filter(Number.isFinite); if (!canvas || !data.length) return;
      let low = Math.min(...data), high = Math.max(...data); if (low === high) {low -= .5; high += .5;}
      const bins = Math.min(80, Math.max(30, Math.ceil(Math.sqrt(data.length)))), width = (high-low)/bins;
      const counts = Array(bins).fill(0); data.forEach(v => counts[Math.min(bins-1,Math.max(0,Math.floor((v-low)/width)))]++);
      canvas.onmousemove = event => {
        const rect=canvas.getBoundingClientRect(), left=58, right=12, usable=Math.max(1,rect.width-left-right);
        const bin=Math.max(0,Math.min(bins-1,Math.floor((event.clientX-rect.left-left)/usable*bins)));
        const lo=low+bin*width, hi=lo+width, count=counts[bin];
        canvas.title=`Return bin ${lo.toFixed(6)} to ${hi.toFixed(6)} · ${count.toLocaleString()} observations · ${(100*count/data.length).toFixed(3)}%`;
      };
    };

    const replay = document.getElementById('tradeReplayControls');
    const form = document.getElementById('form');
    if (replay && form && !form.elements.namedItem('trade_plot_max_points')) {
      const label=document.createElement('label'); label.textContent='Maximum plotted replay points';
      const input=document.createElement('input'); input.name='trade_plot_max_points'; input.type='number'; input.min='500'; input.max='10000'; input.step='500'; input.value='3000'; label.append(input);
      const note=document.createElement('p'); note.className='statistics-note'; note.id='tradeWorkEstimate';
      replay.insertBefore(label, document.getElementById('tradeRunProgress') || null); replay.insertBefore(note, document.getElementById('tradeRunProgress') || null);
      let coverage=null;
      const updateEstimate=()=>{
        const source=form.elements.namedItem('btc_data_source')?.value; if(source!=='trade_tape'){note.textContent='';return;}
        const interval=Number(form.elements.namedItem('execution_interval_seconds')?.value), maxPoints=Number(input.value);
        const startValue=form.elements.namedItem('backtest_start')?.value || coverage?.start;
        const endValue=form.elements.namedItem('backtest_end')?.value || coverage?.end;
        const start=Date.parse(startValue || ''), end=Date.parse(endValue || '');
        if(!(interval>0&&end>start)){note.textContent='Choose a valid replay interval and period to see planned work units.';return;}
        const decisions=Math.ceil((end-start)/1000/interval);
        note.textContent=`Planned work: ${decisions.toLocaleString()} decision ticks; at most ${maxPoints.toLocaleString()} chart samples. Sampling changes plots only, never execution frequency.`;
      };
      form.addEventListener('input',updateEstimate); form.addEventListener('change',updateEstimate);
      fetch('/api/v1/trade-data',{credentials:'include',cache:'no-store'}).then(r=>r.ok?r.json():null).then(data=>{coverage=data?.datasets?.[0]||null;updateEstimate();}).catch(()=>updateEstimate());
    }

    const capital=form?.elements?.namedItem?.('trade_initial_capital_usd');
    if (capital && capital.value === '1' && !capital.dataset.userEdited) capital.value='100000';
    capital?.addEventListener?.('input',()=>{capital.dataset.userEdited='true';});

    const preset=document.getElementById('strategyPreset'), name=document.getElementById('strategyName');
    if (preset && typeof global.applyParameters === 'function') {
      fetch('/api/v1/strategies',{credentials:'include',cache:'no-store'}).then(r=>r.ok?r.json():null).then(data=>{
        const strategies=data?.strategies||[]; if(!strategies.length)return;
        const map=new Map(); const group=document.createElement('optgroup'); group.label='Repository strategies';
        for(const item of strategies){const option=document.createElement('option'); option.value='repo:'+item.name; option.textContent=item.name; group.append(option); map.set(option.value,item.parameters);}
        preset.append(group);
        preset.addEventListener('change',event=>{
          if(!String(preset.value).startsWith('repo:'))return;
          event.stopImmediatePropagation(); const parameters=map.get(preset.value); if(!parameters)return;
          global.applyParameters(structuredClone(parameters)); if(name)name.value=preset.value.slice(5);
          let status=document.getElementById('repositoryStrategyStatus'); if(!status){status=document.createElement('p');status.id='repositoryStrategyStatus';status.className='statistics-note';preset.closest('label')?.after(status);} if(status)status.textContent='Loaded repository strategy: '+preset.value.slice(5);
        },true);
        form?.addEventListener('input',event=>{if(!String(preset.value).startsWith('repo:')||event.target===name)return;const status=document.getElementById('repositoryStrategyStatus');if(status)status.textContent='Modified from repository strategy: '+preset.value.slice(5);},true);
      }).catch(()=>{});
    }
  }
  if (global.addEventListener) global.addEventListener('DOMContentLoaded', setupRuntimeUsability, {once:true});
})(globalThis);
