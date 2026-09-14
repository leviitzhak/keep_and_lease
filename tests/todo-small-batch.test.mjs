import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html=readFileSync(new URL('../silver_strategy_gui.html',import.meta.url),'utf8');
const runtime=readFileSync(new URL('../backtest-runs.js',import.meta.url),'utf8');
function source(name){
  const match=new RegExp('^(?:async )?function '+name+'\\(', 'm').exec(html);
  assert.ok(match,name);
  const tail=html.slice(match.index),next=/\n(?:async )?function /.exec(tail);
  return next?tail.slice(0,next.index):tail;
}

function setupHistogram(){
  let ready;
  const bars=[];
  const drawing=Object.fromEntries(['scale','clearRect','fillText','beginPath','moveTo','lineTo','stroke','save','translate','rotate','restore'].map(k=>[k,()=>{}]));
  drawing.fillRect=(...args)=>bars.push(args);
  const canvas={style:{},parentElement:{clientWidth:800},getContext:()=>drawing,getBoundingClientRect:()=>({left:0,width:800})};
  const context={console,matchMedia:()=>({matches:false}),devicePixelRatio:1,fmt:(v,n)=>v.toFixed(n),
    document:{querySelectorAll:()=>[],getElementById:()=>null},addEventListener:(_,cb)=>{ready=cb}};
  vm.createContext(context);
  vm.runInContext(['num','arrayMinimum','arrayMaximum','histogramChart'].map(source).join('\n'),context);
  vm.runInContext(runtime,context);ready();
  return {context,canvas,bars};
}

test('new and old-without-capital presets default to $100,000, explicit $1 survives',()=>{
  assert.match(html,/name="trade_initial_capital_usd" type="number" value="100000"/);
  for(const [saved,expected] of [[{},'100000'],[{trade_initial_capital_usd:'1'},'1'],[{trade_initial_capital_usd:1},1]]){
    const capital={value:''};
    const context={form:{elements:{namedItem:name=>name==='trade_initial_capital_usd'?capital:null}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity:()=>{}};
    vm.runInNewContext(html.split('\n').find(line=>line.startsWith('function applyParameters(')),context);
    context.applyParameters(saved);assert.equal(capital.value,expected);
  }
});

test('DOMContentLoaded never upgrades an intentionally restored $1 strategy',()=>{
  let ready;const capital={value:'1',dataset:{},addEventListener:()=>{}},form={elements:{namedItem:()=>capital}};
  const context={document:{querySelectorAll:()=>[],getElementById:id=>id==='form'?form:null},addEventListener:(_,cb)=>{ready=cb}};
  vm.runInNewContext(runtime,context);ready();assert.equal(capital.value,'1');
});

test('thinner histogram and hover use the same bins and exclude missing values',()=>{
  const {context,canvas,bars}=setupHistogram();
  context.histogramChart(canvas,[0,1,null,undefined,'',NaN], 'blue');
  assert.equal(bars.length,60);
  canvas.onmousemove({clientX:58.1});
  assert.match(canvas.title,/1 observations · 50.000%/);
  canvas.onmousemove({clientX:787.9});assert.match(canvas.title,/1 observations · 50.000%/);
  context.histogramChart(canvas,[null,''], 'blue');assert.equal(canvas.title,'');assert.equal(canvas.onmousemove,null);
});

test('300,000 histogram observations do not overflow the JavaScript argument stack',()=>{
  const {context,canvas,bars}=setupHistogram();
  context.histogramChart(canvas,Array.from({length:300000},(_,i)=>i%2),'blue');
  assert.equal(bars.length,160);canvas.onmousemove({clientX:58.1});assert.match(canvas.title,/150,000 observations · 50.000%/);
});

function progressContext(){
  const elements={auditStatus:{textContent:'',before:el=>{elements[el.id]=el}},loadAuditDetails:{textContent:'Load detailed plots'},downloadRawAudit:{textContent:'Download full audit'}};
  const context={AbortController,Blob,console,auditAbort:null,auditDownloadAbort:null,
    $:id=>elements[id],document:{createElement:()=>({setAttribute(){},removeAttribute(name){delete this[name]}})},
    spreadsheetPeriod:()=>({start:'2026-06-25',end:'2026-06-26'}),
    plotRangeSource:{result:{audit:{base_url:'/api/v1/backtests/job/audit',datasets:{btc:{chunks:[{index:0,start:'2026-06-25',end:'2026-06-25'},{index:1,start:'2026-06-26',end:'2026-06-26'},{index:2,start:'2026-07-01',end:'2026-07-02'}]}}}},sleeves:{btc:{rateChangePoints:['original']}}},
    applyPlotRange:()=>{},saveDownload:()=>{}};
  vm.createContext(context);
  vm.runInContext(['auditEntries','auditProgress','loadAuditDetails','readAuditDownload','downloadRawAudit'].map(source).join('\n'),context);
  return {context,elements};
}

test('detail progress measures selected chunks only and commits complete data',async()=>{
  const {context,elements}=progressContext();const messages=[];
  context.fetchAuditChunk=async(a,p,entry)=>{messages.push(elements.auditStatus.textContent);return [{date:entry.start}]};
  await context.loadAuditDetails();
  assert.deepEqual(messages,['Loading detailed plots: 0 / 2 chunks received.','Loading detailed plots: 1 / 2 chunks received.']);
  assert.equal(context.plotRangeSource.sleeves.btc.rateChangePoints.length,2);
  assert.match(elements.auditStatus.textContent,/loaded: 2 \/ 2/);assert.equal(elements.detailProgress.hidden,true);
});

test('cancelling detail loading preserves earlier data and resets the controls',async()=>{
  const {context,elements}=progressContext();
  context.fetchAuditChunk=async(a,p,e,s,signal)=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError'))));
  const running=context.loadAuditDetails();await context.loadAuditDetails();await running;
  assert.deepEqual(context.plotRangeSource.sleeves.btc.rateChangePoints,['original']);
  assert.match(elements.auditStatus.textContent,/cancelled/);assert.equal(elements.loadAuditDetails.textContent,'Load detailed plots');assert.equal(context.auditAbort,null);
});

test('detail errors do not replace existing chart data',async()=>{
  const {context,elements}=progressContext();
  context.fetchAuditChunk=async()=>{throw Error('Checksum mismatch')};
  await context.loadAuditDetails();assert.match(elements.auditStatus.textContent,/Checksum mismatch/);
  assert.deepEqual(context.plotRangeSource.sleeves.btc.rateChangePoints,['original']);assert.equal(elements.detailProgress.hidden,true);
});

test('audit byte progress supports known, unknown and transport-encoded sizes',async()=>{
  for(const headers of [{'Content-Length':'5'},{},{'Content-Length':'5','Content-Encoding':'gzip'}]){
    const {context}=progressContext(),updates=[];
    const response=new Response(new ReadableStream({start(c){c.enqueue(new Uint8Array([1,2]));c.enqueue(new Uint8Array([3,4,5]));c.close()}}),{headers});
    const blob=await context.readAuditDownload(response,(...args)=>updates.push(args));
    assert.equal(blob.size,5);assert.deepEqual(updates.map(x=>x[0]),[0,2,5]);
    assert.equal(updates[0][1],headers['Content-Length']&&!headers['Content-Encoding']?5:null);
  }
});

test('full audit downloads expose progress and restore controls on success or error',async()=>{
  for(const ok of [true,false]){
    const {context,elements}=progressContext();let saved=null;
    context.fetch=async()=>new Response(ok?'PK-archive':'bad',{status:ok?200:503});
    context.saveDownload=(blob,name)=>{saved={blob,name}};
    await context.downloadRawAudit();
    assert.equal(Boolean(saved),ok);assert.match(elements.auditStatus.textContent,ok?/downloaded: 10 bytes/:/failed \(503\)/);
    assert.equal(elements.downloadRawAudit.textContent,'Download full audit');assert.equal(elements.auditDownloadProgress.hidden,true);
    assert.equal(context.auditDownloadAbort,null);
  }
});

test('full audit cancellation uses AbortController and never saves a partial archive',async()=>{
  const {context,elements}=progressContext();let saved=false;
  context.fetch=async(url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError'))));
  context.saveDownload=()=>{saved=true};const running=context.downloadRawAudit();await context.downloadRawAudit();await running;
  assert.equal(saved,false);assert.match(elements.auditStatus.textContent,/cancelled/);assert.equal(context.auditDownloadAbort,null);
});
