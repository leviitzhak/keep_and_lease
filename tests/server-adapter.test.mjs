import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const source = (await readFile(new URL('../public/backtest-worker-v13.js', import.meta.url), 'utf8'))
  .replace(/initialize\(\);\s*$/, '');
const base = 'https://preview.example';
const job = {job_id:'a'.repeat(32), status:'queued', status_url:'/api/v1/backtests/'+ 'a'.repeat(32),
  result_url:'/api/v1/backtests/'+ 'a'.repeat(32)+'/result'};
const complete = {...job, status:'completed', elapsed_seconds:200};
const result = {summary:{compounded_return:43.7335811}};
const response = (body, status=200, extra={}) => ({ok: status >= 200 && status < 300, status,
  headers:{get:()=> 'application/json'}, text: async()=>JSON.stringify(body),
  json:async()=>body, ...extra});
function harness(fetcher) {
  const calls=[], messages=[], workers=[], timers=new Map();
  let nextTimer=0;
  const context = vm.createContext({URL, TypeError, AbortController, performance,
    fetch: async (url, options={}) => { calls.push({url,options}); return fetcher(url,options,calls); },
    setTimeout(fn,ms) { const id=++nextTimer; if(ms<30000) queueMicrotask(fn); else timers.set(id,{fn,ms}); return id; },
    clearTimeout(id) { timers.delete(id); },
    self:{location:{href:base+'/backtest-worker-v13.js',origin:base},postMessage:msg=>messages.push(msg)},
    Worker:class {constructor(url){workers.push(url);}},
  });
  vm.runInContext(source, context);
  return {context,calls,messages,workers,timers,
    run:()=>context.handleServerMessage(base,{id:1,type:'run',payload:{weight_btc:100}}),
  };
}

test('network failures and HTTP 503 resume the same job with one submission', async()=>{
  let reads=0;
  const h=harness((url,options)=>{
    if(options.method==='POST') return response(job);
    if(url.endsWith('/result')) return response(result);
    reads++;
    if(reads===1) throw new TypeError('Failed to fetch');
    if(reads===2) return response({},503);
    return response(complete);
  });
  await h.run();
  assert.equal(JSON.stringify(h.messages.at(-1).result),JSON.stringify(result));
  assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);
  assert.equal(h.messages.filter(m=>m.message==='Reconnecting to server calculation').length,2);
  assert.equal(h.workers.length,0);
  assert.equal(h.timers.size,0);
});

test('request timeout covers stalled body reads, aborts and clears its timer',async()=>{
  const h=harness((_url,options)=>response({},200,{text:()=>new Promise((resolve,reject)=>{
    options.signal.addEventListener('abort',()=>reject(new Error('aborted')));
  })}));
  const request=h.context.jsonRequest(base+'/api/v1/health');
  await new Promise(resolve=>setImmediate(resolve));
  for(const {fn} of h.timers.values()) fn();
  await assert.rejects(request,/timed out after 30s/);
  assert.equal(h.calls[0].options.signal.aborted,true);
  assert.equal(h.timers.size,0);
});

test('exhausted polling retains the job for a later same-parameter retry',async()=>{
  let offline=true;
  const h=harness((url,options)=>{
    if(options.method==='POST') return response(job);
    if(offline) throw new TypeError('Failed to fetch');
    return response(url.endsWith('/result')?result:complete);
  });
  await h.run();
  assert.match(h.messages.at(-1).error,/Job a{32}.*Retry with unchanged parameters/);
  assert.equal(h.calls.length,6); // one POST, five bounded GET attempts
  offline=false;
  await h.run();
  assert.equal(JSON.stringify(h.messages.at(-1).result),JSON.stringify(result));
  assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);
  assert.equal(h.workers.length,0);
});

test('interrupted result stream is fetched again without recalculation',async()=>{
  let downloads=0;
  const h=harness((url,options)=>{
    if(options.method==='POST') return response(complete);
    assert.ok(url.endsWith('/result'));
    if(++downloads===1) return response({},200,{text:async()=>{throw new TypeError('connection reset');}});
    return response(result);
  });
  await h.run();
  assert.equal(JSON.stringify(h.messages.at(-1).result),JSON.stringify(result));
  assert.equal(downloads,2);
  assert.equal(h.calls.filter(c=>c.options.method==='POST').length,1);
});

test('authentication failures report sign-in and job ID without retries or browser execution',async()=>{
  for(const authResponse of [response({},401),response({},403),response({},200,{redirected:true})]) {
    const h=harness((_url,options)=>response(options.method==='POST'?job:{},200));
    h.context.fetch=async(url,options={})=>{h.calls.push({url,options});return options.method==='POST'?response(job):authResponse;};
    await h.run();
    assert.match(h.messages.at(-1).error,/Job a{32}.*sign-in/);
    assert.equal(h.calls.length,2);
    assert.equal(h.workers.length,0);
  }
});

test('server failure stays visible and never launches the browser engine',async()=>{
  const h=harness((_url,options)=>response(options.method==='POST'?job:
    {...job,status:'failed',error:'Worker exceeded memory limit'}));
  await h.run();
  assert.match(h.messages.at(-1).error,/Worker exceeded memory limit/);
  assert.doesNotMatch(h.messages.at(-1).error,/not been cancelled/);
  assert.equal(h.workers.length,0);
});

test('ambiguous submission is not repeated or replaced by a browser run',async()=>{
  const h=harness(()=>{throw new TypeError('Failed to fetch');});
  await h.run();
  assert.equal(h.calls.length,1);
  assert.match(h.messages.at(-1).error,/Could not confirm job submission/);
  assert.equal(h.workers.length,0);
});

test('Cloud Run configuration suppresses unavailable Pyodide initialization',async()=>{
  const h=harness(url=>{
    if(url==='/compute-config.json') return response({apiBaseUrl:'',browserFallback:false});
    throw new TypeError('Failed to fetch');
  });
  await h.context.initialize();
  assert.equal(h.messages.at(-1).type,'error');
  assert.match(h.messages.at(-1).error,/Calculation server unavailable/);
  assert.equal(h.workers.length,0);
});
