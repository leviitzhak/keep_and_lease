import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const c={};vm.createContext(c);vm.runInContext(readFileSync(new URL('../shared-run-plots.js',import.meta.url),'utf8'),c);
const api=c.KeepLeasePlots;
function replay(extra={}){
  return {result_kind:'btc_trade_replay',trade_replay:{capital_usd:100000,plot_sample_every:100},
    fields:['date','nav','direct_nav','cash_usd','spot_value_usd','futures_notional_usd','turnover_usd','fees_usd','max_mark_age_seconds','spot_pnl_usd','futures_pnl_usd','treasury_interest_usd'],
    series:[['2026-06-06T00:00:00.000000',1,1,0,100000,0,0,0,2,0,0,0],
      ['2026-06-06T01:00:00.000000',1.2,1.1,80000,40000,60000,70000,20,15,10000,10000,20],
      ['2026-06-06T02:00:00.000000',1.1,1.2,70000,40000,60000,90000,30,3,8000,1500,530]],...extra};
}
test('shared catalog spans both directions, without running an engine',()=>{
 for(const id of ['nav','drawdown','holdings','target','volume','fees','mark-age','prices','premiums','lease-rates','maturities','legs','lease-values','book-returns','book-indexes','reconstruction'])assert.ok(api.catalog.some(d=>d.id===id),id);
});
test('replay books reconcile in underlying equivalents and short books stay disabled',()=>{
 const source=replay(),before=JSON.stringify(source),m=api.replayModel(source),r=m.rows[1];
 assert.ok(Math.abs(r.leaseValue-(r.directUnderlying+r.futureUnderlying))<1e-12);
 assert.equal(r.balanceNav,1.2);assert.equal(r.keepValue,null);assert.equal(m.hasShort,false);
 assert.equal(JSON.stringify(source),before);
 assert.ok(Math.abs(r.directReturn-10)<1e-12);assert.equal(m.rows[0].returnPct,null);
});
function pairedReplay(overrides={}){
 const source=replay(),extra={free_cash_usd:10000,posted_cash_usd:70000,reserved_cash_usd:3000,available_cash_usd:6000,unsettled_pnl_usd:5000,pending_variation_usd:-1500,treasury_value_usd:10000,liabilities_usd:2000,commodity_nav_btc:1.315,...overrides};
 source.trade_replay.strategy='cost_aware_paired';source.trade_replay.paired_transfer={};
 source.fields.push(...Object.keys(extra));
 source.series=[source.series[1].concat(...Object.values(extra))];
 source.series[0][source.fields.indexOf('nav')]=(80000+40000+extra.unsettled_pnl_usd+extra.pending_variation_usd+extra.treasury_value_usd-extra.liabilities_usd)/100000;
 return source;
}
test('paired reconstruction includes every funding asset and liability without adding reservations twice',()=>{
 const source=pairedReplay(),before=JSON.stringify(source),model=api.replayModel(source),row=model.rows[0];
 assert.equal(model.paired,true);assert.equal(row.cash,80000);
 assert.equal(row.freeCash+row.postedCash,row.cash);
 assert.equal(row.fundingEquity,91500);assert.equal(row.balanceNav,1.315);
 assert.equal(row.balanceNav,row.nav);assert.equal(row.free,31500);assert.equal(row.ratio,91500/60000);
 assert.equal(row.availableCash,6000);assert.equal(row.reservedCash,3000);
 assert.ok(Math.abs(row.futureUnderlying-91500/110000)<1e-12);
 assert.ok(Math.abs(row.directUnderlying+row.futureUnderlying-row.leaseValue)<1e-12);
 assert.equal(JSON.stringify(source),before);
 assert.match(model.note,/Immediately available cash is shown separately/);
});
test('settling paired P&L between unrealized, pending and cash leaves book NAV invariant',()=>{
 const points=[];
 for(const [unsettled,pending,cash] of [[1000,0,80000],[0,1000,80000],[0,0,81000]]){
  const source=pairedReplay({unsettled_pnl_usd:unsettled,pending_variation_usd:pending,treasury_value_usd:0,liabilities_usd:0});
  source.series[0][source.fields.indexOf('cash_usd')]=cash;
  source.series[0][source.fields.indexOf('nav')]=1.21;
  points.push(api.replayModel(source).rows[0]);
 }
 for(const row of points){assert.equal(row.balanceNav,1.21);assert.equal(row.fundingEquity,81000);assert.ok(Math.abs(row.leaseValue-row.directUnderlying-row.futureUnderlying)<1e-12);}
});
test('missing or null paired ledger constituents stay unknown instead of using legacy cash-only identity',()=>{
 for(const field of ['unsettled_pnl_usd','pending_variation_usd','treasury_value_usd','liabilities_usd'])for(const absent of [true,false]){
  const source=pairedReplay(),index=source.fields.indexOf(field);
  if(absent){source.fields.splice(index,1);source.series[0].splice(index,1);}else source.series[0][index]=null;
  const row=api.replayModel(source).rows[0];
  for(const key of ['balanceNav','futureUnderlying','fundingEquity','free','ratio'])assert.equal(row[key],null,field+' '+key);
  assert.equal(row.cash,80000);assert.equal(row.availableCash,6000);
 }
});
test('paired chart labels distinguish cash liquidity from economic funding while legacy schema stays unchanged',()=>{
 const defs=new Map(api.catalog.map(def=>[def.id,def]));
 assert.equal(defs.get('reconstruction').series.at(-1)[1],'Cash + spot identity');
 assert.equal(defs.get('reconstruction').pairedView.series.at(-1)[1],'Asset/liability identity');
 assert.match(defs.get('holdings').pairedView.series[1][1],/^Cash/);
 assert.equal(defs.get('cash-availability').pairedOnly,true);
 assert.equal(defs.get('funding-components').pairedOnly,true);
 const legacy=api.replayModel(replay()).rows[1];
 assert.ok(!('fundingEquity' in legacy));assert.ok(!('availableCash' in legacy));
 assert.equal(legacy.balanceNav,1.2);assert.equal(legacy.free,20000);
 assert.ok(Math.abs(legacy.futureUnderlying-80000/110000)<1e-12);
});
test('schema names, not numeric indexes, locate collateral, costs and mark age',()=>{
 const source=replay(),fields=[...source.fields].reverse(),series=source.series.map(r=>[...r].reverse());
 // Date remains the first field by the public wire contract.
 const di=fields.indexOf('date');fields.splice(di,1);fields.unshift('date');
 for(const r of series){const date=r.splice(di,1)[0];r.unshift(date);}
 const a=api.replayModel(source),b=api.replayModel({...source,fields,series});
 assert.equal(JSON.stringify(a.rows),JSON.stringify(b.rows));
 assert.equal(b.rows[1].age,15);assert.equal(b.rows[1].free,20000);
});
test('historical unknown target, turnover and reconstruction stay null',()=>{
 const source=replay();source.fields=source.fields.filter(f=>!['turnover_usd','spot_pnl_usd','futures_pnl_usd','treasury_interest_usd'].includes(f));
 source.series=source.series.map(r=>r.slice(0,6).concat(r[7],r[8]));
 const m=api.replayModel(source);
 for(const r of m.rows){assert.equal(r.target,null);assert.equal(r.turnover,null);assert.equal(r.volume,null);assert.equal(r.reconstructed,null);assert.equal(r.directReturn,null);}
});
test('zero notional has no ratio; null and empty are never converted to zero',()=>{
 const m=api.replayModel(replay());assert.equal(m.rows[0].ratio,null);
 for(const value of [null,undefined,'',NaN,Infinity])assert.equal(api.finite(value),null);
 assert.equal(api.finite(0),0);
});
test('period selection retains prior full-run peak and cumulative-counter baseline',()=>{
 const m=api.replayModel(replay()),rows=api.selectRows(m,date=>date.includes('02:00'));
 assert.equal(rows.length,1);assert.equal(rows[0].volume,20000);
 assert.ok(Math.abs(rows[0].drawdown-(1.1/1.2-1)*100)<1e-12);
 assert.ok(Math.abs(rows[0].returnPct-(1.1/1.2-1)*100)<1e-12);
});
test('daily start exposures are not confused with interval-end NAV',()=>{
 const fields=['date','exit_date','compounded_return_pct','interval_return_pct','slv_compounded_return_pct','slv_weight_pct','treasury_weight_pct','long_futures_notional_pct','short_futures_notional_pct','plot_turnover_total','initial_replicating_leg_value','initial_futures_treasury_value'];
 const series=[['2026-01-01','2026-01-02',10,10,8,40,60,60,0,0.8,0.4,0.6],['2026-01-02','2026-01-05',21,10,10,30,70,70,0,1.3,0.4,0.6]];
 const m=api.dailyModel({fields,series,execution:{model:'legacy_close'}},'silver'),r=m.rows[0];
 assert.equal(r.date,'2026-01-02');assert.equal(r.start,'2026-01-01');assert.equal(r.nav,1.1);assert.equal(r.cash,.6);assert.equal(r.long,.6);assert.equal(r.free,0);
 assert.equal(r.ratio,1);assert.equal(r.target,.6);assert.equal(r.age,null);assert.equal(r.short,null);
 assert.equal(m.initial.nav,1);assert.equal(m.initial.date,'2026-01-01');
 assert.equal(m.rows[1].volume,.5);
});
test('observed daily results do not equate achieved exposure with pending targets',()=>{
 const m=api.dailyModel({fields:['date','compounded_return_pct','interval_return_pct','slv_weight_pct','treasury_weight_pct','long_futures_notional_pct','short_futures_notional_pct'],series:[['2026-01-01',0,0,20,80,30,0]],execution:{model:'observed'}},'btc');
 assert.equal(m.rows[0].target,null);assert.equal(m.rows[0].free,.5);
});
test('full sources survive UI period filtering and retain held-instrument alignment',()=>{
 const s={fields:['date','exit_date','compounded_return_pct','interval_return_pct'],series:[['2026-01-02','2026-01-03',0,0]],held_futures_diagnostics:[[{symbol:'wrong'}]]};
 const original={series:[['2026-01-01','2026-01-02',10,10],...s.series],heldFuturesDiagnostics:[[{symbol:'one'}],[{symbol:'two'}]],returnDistributions:[['2026-01-02',1,0]]};
 const models=api.models({commodity_sleeves:{silver:s}},{silver:original});
 assert.equal(models.silver.rows.length,2);assert.equal(models.silver.rows[1].holdings[0].symbol,'two');assert.equal(models.silver.distributions.length,1);
});
test('packaging and both draw paths include the shared viewer and schema-safe age',()=>{
 const html=readFileSync(new URL('../silver_strategy_gui.html',import.meta.url),'utf8');
 assert.match(html,/<script src="\/shared-run-plots.js\?v=1"><\/script>/);
 assert.ok(html.split('drawSharedRunPlots();').length>=3);
 assert.match(html,/i:last.fields.indexOf\('max_mark_age_seconds'\)/);
 assert.match(readFileSync(new URL('../Dockerfile.web',import.meta.url),'utf8'),/public\/shared-run-plots.js/);
});


test('replacing a plot family releases renderer references and canvas bitmaps',()=>{
  const canvases=Array.from({length:4},()=>({width:8000,height:250,onmousemove:()=>{},onclick:()=>{},onmouseleave:()=>{}}));
  const registry=new Map(canvases.map(c=>[c,{rows:[[1,2]]}]));
  api.disposeCanvases({querySelectorAll:()=>canvases},canvas=>registry.delete(canvas));
  assert.equal(registry.size,0);
  for(const canvas of canvases){assert.equal(canvas.width,0);assert.equal(canvas.height,0);assert.equal(canvas.onmousemove,null);}
});
