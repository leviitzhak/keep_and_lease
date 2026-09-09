import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../backtest-runs.js', import.meta.url), 'utf8');
class Element {
  constructor(tag, doc) { this.tag = tag; this.ownerDocument = doc; this.children = []; this.dataset = {}; this.attributes = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(key, value) { this.attributes[key] = value; }
}
function harness(fetch, options = {}) {
  const doc = {createElement: tag => new Element(tag, doc)};
  const root = new Element('section', doc), results = [], parameters = [];
  const context = {fetch, setTimeout, clearTimeout, AbortController, structuredClone, console};
  vm.runInNewContext(source, context);
  const controller = context.createBacktestRuns({root, apiUrl: async path => path,
    onResult: (data, job) => results.push({data, id: job.job_id}), onParameters: value => parameters.push(value), ...options});
  return {controller, root, results, parameters};
}
const response = data => ({ok: true, json: async () => data});
const job = (id, status = 'running') => ({job_id: id.repeat(32), status, created_at: 100,
  parameters: {weight_btc: 100, btc_data_source: 'trade_tape'}, detail: 'Replay (45.5%)'});
const flush = () => new Promise(resolve => setImmediate(resolve));

test('submission returns immediately and distinct runs can be submitted while the first runs', async () => {
  const calls = []; let index = 0;
  const h = harness(async (url, options) => { calls.push([url, options.method]); return response(job(String(++index))); });
  const first = await h.controller.submit({variant: 1});
  const second = await h.controller.submit({variant: 2});
  assert.notEqual(first.job_id, second.job_id);
  assert.equal(calls.filter(x => x[1] === 'POST').length, 2);
  assert.equal(h.results.length, 0);
  h.controller.stop();
  assert.equal(calls.filter(x => x[1] === 'DELETE').length, 0);
});

test('fresh page restores durable jobs, polls their completion and can load an older result', async () => {
  let state = 'running';
  const h = harness(async url => url.includes('/result') ? response({summary: {id: url}})
    : response({jobs: [job('b', state), job('a', 'completed')], next_cursor: null}));
  await h.controller.refresh();
  assert.equal(h.results.length, 0);
  state = 'completed';
  await h.controller.refresh();
  assert.equal(h.results[0].id, 'b'.repeat(32));
  await h.controller.select('a'.repeat(32));
  assert.equal(h.results[1].id, 'a'.repeat(32));
});

test('late result cannot replace a more recently selected result or modify form parameters', async () => {
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  const h = harness(async url => {
    if (url.includes('a'.repeat(32) + '/result')) return delayed;
    if (url.endsWith('/result')) return response({summary: {value: 'b'}});
    return response({jobs: [job('a', 'completed'), job('b', 'completed')], next_cursor: null});
  });
  await h.controller.refresh();
  const first = h.controller.select('a'.repeat(32));
  await flush();
  await h.controller.select('b'.repeat(32));
  release(response({summary: {value: 'a'}}));
  await first;
  assert.equal(h.results.length, 1);
  assert.equal(h.results[0].id, 'b'.repeat(32));
  assert.equal(h.parameters.length, 0);
});

test('temporary history errors preserve rows and subsequent refresh recovers', async () => {
  let fail = false;
  const h = harness(async () => {
    if (fail) throw Error('offline');
    return response({jobs: [job('c')], next_cursor: null});
  });
  await h.controller.refresh();
  const list = h.root.children[2];
  assert.equal(list.children.length, 1);
  fail = true; await h.controller.refresh();
  assert.equal(list.children.length, 1);
  assert.match(h.root.children[1].textContent, /continue in the background/);
  fail = false; await h.controller.refresh();
  assert.match(h.root.children[1].textContent, /refreshed/);
});

test('an ambiguous submission is never automatically posted twice', async () => {
  let posts = 0;
  const h = harness(async (_url, options) => {
    if (options.method === 'POST') { posts++; throw Error('Connection lost'); }
    return response({jobs: [], next_cursor: null});
  });
  await assert.rejects(h.controller.submit({}), /Check the run list/);
  await flush();
  assert.equal(posts, 1);
});
