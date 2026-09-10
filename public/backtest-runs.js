/* Durable server jobs. Closing this page never cancels a submitted execution. */
(function (global) {
  'use strict';
  global.createBacktestRuns = function ({root, apiUrl, onResult, onParameters, onSelect = () => {}}) {
    const document = root.ownerDocument;
    const jobs = new Map();
    let selected = null, generation = 0, loaded = null, loading = null;
    let nextCursor = null, refreshing = false, timer = null, stopped = false;
    const active = job => ['queued', 'running'].includes(job.status);
    const resumable = job => ['failed', 'cancelled'].includes(job.status) && job.parameters?.btc_data_source === 'trade_tape';
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
    controls.append(button('Refresh runs', () => refresh()), more);
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
    function render() {
      list.replaceChildren();
      const ordered = [...jobs.values()].sort((a, b) => b.created_at - a.created_at || b.job_id.localeCompare(a.job_id));
      for (const job of ordered) {
        const row = node('article'); row.className = 'backtest-run'; row.dataset.jobId = job.job_id;
        row.setAttribute('aria-label', 'Backtest ' + job.job_id);
        const p = job.parameters || {};
        const assets = Object.keys(p).filter(key => key.startsWith('weight_') && Number(p[key]) > 0).map(key => key.slice(7)).join(', ');
        row.append(node('strong', job.status + ' · ' + (assets || 'Strategy') + ' · ' + new Date(job.created_at * 1000).toLocaleString()));
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
        if (active(job)) row.append(button(job.cancellation_requested ? 'Cancellation requested' : 'Cancel', () => mutate(job.job_id, 'DELETE')));
        if (resumable(job)) {
          row.append(button('Resume checkpoint', () => resume(job.job_id)));
        }
        if (selected === job.job_id) {
          const details = node('div'); details.id = 'selectedBacktestDetails';
          details.setAttribute('role', 'status');
          details.append(node('strong', 'Selected backtest · ' + job.status));
          details.append(node('p', 'Run ID: ' + job.job_id));
          if (job.stage) details.append(node('p', 'Stage: ' + job.stage));
          if (job.detail) details.append(node('p', 'Last progress: ' + job.detail));
          if (job.error) details.append(node('p', 'Error: ' + job.error));
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
    }
    async function loadSelected() {
      const job = jobs.get(selected);
      if (!job || job.status !== 'completed' || loaded === selected || loading === selected) return;
      const id = selected, revision = generation;
      loading = id; viewing.textContent = 'Loading results for ' + id.slice(0, 8) + '…';
      try {
        const data = await request('/api/v1/backtests/' + id + '/result');
        if (revision !== generation || selected !== id || stopped) return;
        await onResult(data, job);
        loaded = id;
        viewing.textContent = 'Viewing completed backtest ' + id.slice(0, 8) + ' · ' + new Date(job.created_at * 1000).toLocaleString() + '. Form edits do not change these saved results.';
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
        // Refresh active jobs on older loaded pages too.
        const seen = new Set(page.jobs.map(job => job.job_id));
        for (const job of [...jobs.values()]) if (!seen.has(job.job_id) && (active(job) || job.job_id === selected)) {
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
      jobs.set(job.job_id, job);
      // Return after acknowledgement, including cached results; no worker wait.
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
    async function tick() {
      await refresh();
      if (!stopped) timer = setTimeout(tick, 5000);
    }
    function start() { stopped = false; void tick(); }
    function stop() { stopped = true; generation++; clearTimeout(timer); }
    return {start, stop, submit, resume, select, refresh};
  };
})(globalThis);
