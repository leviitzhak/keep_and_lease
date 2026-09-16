import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html=readFileSync(new URL('../silver_strategy_gui.html',import.meta.url),'utf8');
function source(name){
  const start=html.indexOf('function '+name+'(');
  assert.ok(start>=0,name);
  const end=html.indexOf('\nfunction ',start+1);
  return html.slice(start,end<0?undefined:end);
}

test('old parameter imports reset paired policy and costs while preserving explicit paired imports',()=>{
  const fields=new Map(['trade_strategy','paired_horizon_days','paired_spot_fixed_fee_usd','paired_max_unpaired_btc','paired_repricing_mode','paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds'].map(key=>[key,{value:'prior paired run'}]));
  const context={form:{elements:{namedItem:name=>fields.get(name)}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity(){}};
  vm.runInNewContext(source('applyParameters'),context);
  context.applyParameters({});
  assert.equal(fields.get('trade_strategy').value,'legacy');
  assert.equal(fields.get('paired_horizon_days').value,'1,3,7,14,30');
  assert.equal(fields.get('paired_spot_fixed_fee_usd').value,'0');
  assert.equal(fields.get('paired_max_unpaired_btc').value,'0.01');
  assert.equal(fields.get('paired_repricing_mode').value,'fixed');
  for(const name of ['paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds'])assert.equal(fields.get(name).value,'0');
  context.applyParameters({trade_strategy:'cost_aware_paired',paired_spot_fixed_fee_usd:'1.75',paired_horizon_days:'0.25,1,3'});
  assert.equal(fields.get('trade_strategy').value,'cost_aware_paired');
  assert.equal(fields.get('paired_spot_fixed_fee_usd').value,'1.75');
  assert.equal(fields.get('paired_horizon_days').value,'0.25,1,3');
});

test('import migrates the BTC transport delay without adding the legacy delay twice',()=>{
  const fields=new Map(['paired_repricing_mode','paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds'].map(name=>[name,{value:''}]));
  const context={form:{elements:{namedItem:name=>fields.get(name)}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity(){}};
  vm.runInNewContext(source('applyParameters'),context);
  context.applyParameters({execution_delay_seconds:'0.8',commodity_parameters:{btc:{execution_delay_seconds:'0.35'}}});
  assert.equal(fields.get('paired_order_delay_seconds').value,'0.35');
  assert.equal(fields.get('paired_repricing_mode').value,'fixed');
  context.applyParameters({execution_delay_seconds:'0.8',commodity_parameters:'{"btc":{"execution_delay_seconds":"0.35"}}',paired_repricing_mode:'adaptive',paired_order_delay_seconds:'0',paired_observation_delay_seconds:'0.2',paired_decision_delay_seconds:'0.1'});
  assert.equal(fields.get('paired_order_delay_seconds').value,'0');
  assert.equal(fields.get('paired_repricing_mode').value,'adaptive');
  assert.equal(fields.get('paired_observation_delay_seconds').value,'0.2');
  assert.equal(fields.get('paired_decision_delay_seconds').value,'0.1');
  context.applyParameters({execution_delay_seconds:'0.8'});
  assert.equal(fields.get('paired_order_delay_seconds').value,'0.8');
  assert.equal(fields.get('paired_repricing_mode').value,'fixed');
  context.applyParameters({commodity_parameters:'invalid'});
  assert.equal(fields.get('paired_order_delay_seconds').value,'0');
});

test('switching commodity editors cannot copy paired settings into a commodity profile',()=>{
  const names=[...html.matchAll(/\bname="([^"]+)"/g)].map(match=>match[1]);
  const elements=names.map(name=>({name,value:'setting'}));
  elements.namedItem=name=>elements.find(field=>field.name===name);
  const declarations=html.split('\n').filter(line=>line.startsWith('const GLOBAL_FIELDS=')||line.startsWith('const LEG_FIELDS=')).join('\n');
  const context={form:{elements},commodityProfiles:{},activeCommodity:'btc'};
  vm.createContext(context);
  vm.runInContext(declarations+'\n'+source('captureCommodity'),context);
  context.captureCommodity();
  assert.ok('trading_fee_bps' in context.commodityProfiles.btc);
  assert.ok(!('trade_strategy' in context.commodityProfiles.btc));
  assert.ok(!('trade_ordering' in context.commodityProfiles.btc));
  assert.deepEqual(Object.keys(context.commodityProfiles.btc).filter(name=>name.startsWith('paired_')),[]);
});

test('paired mode disables irrelevant allocation controls and serialization preserves them for legacy reloads',()=>{
  const names=['btc_data_source','trade_strategy','min_days','long_score_rate_scale','short_pure_maturity_strength','enable_short_book','trading_fee_bps','execution_delay_seconds','paired_order_delay_seconds'];
  const elements=names.map(name=>({name,value:name==='btc_data_source'?'trade_tape':name==='trade_strategy'?'cost_aware_paired':'3',disabled:false,closest:()=>null}));
  elements.namedItem=name=>elements.find(field=>field.name===name);
  const nodes=Object.fromEntries(['tradeReplayControls','pairedTransferControls','pairedLegacyNotice','previewLongScore','previewShortScore'].map(id=>[id,{}]));
  const context={form:{elements},$:id=>nodes[id],captureCommodity(){},commodityProfiles:{btc:{}},FormData:class{constructor(form){this.form=form}entries(){return this.form.elements.filter(field=>!field.disabled).map(field=>[field.name,field.value])}}};
  vm.runInNewContext(source('updateTradeControls')+'\n'+html.split('\n').find(line=>line.startsWith('function values(')),context);
  context.updateTradeControls();
  assert.equal(elements.namedItem('min_days').disabled,true);
  assert.equal(elements.namedItem('long_score_rate_scale').disabled,true);
  assert.equal(elements.namedItem('trading_fee_bps').disabled,false);
  assert.equal(elements.namedItem('execution_delay_seconds').disabled,true);
  assert.equal(elements.namedItem('paired_order_delay_seconds').disabled,false);
  assert.equal(elements.namedItem('enable_short_book').disabled,false);
  assert.equal(nodes.pairedLegacyNotice.hidden,false);
  assert.equal(nodes.previewLongScore.hidden,true);
  assert.equal(context.values().min_days,'3');
  assert.equal(context.values().execution_delay_seconds,'3');
  assert.equal(context.values().paired_order_delay_seconds,'3');
  elements.namedItem('trade_strategy').value='legacy';context.updateTradeControls();
  assert.equal(elements.namedItem('min_days').disabled,false);
  assert.equal(elements.namedItem('execution_delay_seconds').disabled,false);
  assert.equal(nodes.previewLongScore.hidden,false);
  assert.equal(nodes.pairedLegacyNotice.hidden,true);
});

function validationContext(overrides={},profile={}){
  const values={trade_strategy:'cost_aware_paired',btc_data_source:'trade_tape',weight_btc:'100',weight_silver:'0',weight_gold:'0',weight_sp500:'0',weight_treasury:'0',paired_horizon_days:'1,3,7,14,30',paired_max_horizon_days:'30',paired_repricing_mode:'fixed',paired_observation_delay_seconds:'0',paired_decision_delay_seconds:'0',paired_order_delay_seconds:'0',...overrides};
  const context={form:{elements:{namedItem:name=>({value:values[name]})}},captureCommodity(){},commodityProfiles:{btc:{futures_contract_type:'regular',enable_short_book:'false',...profile}}};
  vm.runInNewContext(source('validatePairedForm'),context);
  return context;
}

test('paired submissions require BTC trade replay and a supported exposure model',()=>{
  assert.doesNotThrow(()=>validationContext().validatePairedForm());
  assert.throws(()=>validationContext({btc_data_source:'minute'}).validatePairedForm(),/require BTC trade replay/);
  assert.throws(()=>validationContext({weight_silver:'1'}).validatePairedForm(),/BTC-only/);
  assert.throws(()=>validationContext({weight_treasury:'1'}).validatePairedForm(),/standalone Treasury/);
  assert.throws(()=>validationContext({}, {futures_contract_type:'inverse'}).validatePairedForm(),/regular\/linear/);
  assert.throws(()=>validationContext({}, {enable_short_book:'true'}).validatePairedForm(),/short book disabled/);
  assert.doesNotThrow(()=>validationContext({trade_strategy:'legacy',btc_data_source:'minute',weight_silver:'100'}).validatePairedForm());
});

test('holding horizons reject malformed and nonfinite forecasts',()=>{
  for(const value of ['', '1,', '1,,3', '0', '-1,3', 'NaN', 'Infinity', '31,60']){
    assert.throws(()=>validationContext({paired_horizon_days:value}).validatePairedForm(),/positive comma-separated/);
  }
  assert.doesNotThrow(()=>validationContext({paired_horizon_days:'0.25, 1, 3'}).validatePairedForm());
});

test('repricing validates its mode and three independent nonnegative delays',()=>{
  assert.doesNotThrow(()=>validationContext({paired_repricing_mode:'adaptive',paired_observation_delay_seconds:'0.2',paired_decision_delay_seconds:'0.1',paired_order_delay_seconds:'0.3'}).validatePairedForm());
  assert.throws(()=>validationContext({paired_repricing_mode:'market'}).validatePairedForm(),/repricing/);
  for(const name of ['paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds']){
    for(const value of ['',' ','-0.1','NaN','Infinity'])assert.throws(()=>validationContext({[name]:value}).validatePairedForm(),/finite, nonnegative/);
  }
});

test('paired preset is bounded and every paired numeric default satisfies browser constraints',()=>{
  const preset=JSON.parse(readFileSync(new URL('../strategies/research-btc-cost-aware-paired.json',import.meta.url),'utf8'));
  assert.equal(preset.parameters.trade_strategy,'cost_aware_paired');
  assert.equal(preset.parameters.btc_data_source,'trade_tape');
  assert.equal(Date.parse(preset.parameters.backtest_end)-Date.parse(preset.parameters.backtest_start),300000);
  const migrationDefaults={paired_observation_delay_seconds:'0',paired_decision_delay_seconds:'0',paired_order_delay_seconds:'0'};
  for(const tag of html.matchAll(/<input\b[^>]*name="paired_[^>]*>/g)){
    const attrs=Object.fromEntries([...tag[0].matchAll(/([\w-]+)="([^"]*)"/g)].map(match=>[match[1],match[2]]));
    assert.equal(String(preset.parameters[attrs.name]??migrationDefaults[attrs.name]),attrs.value,attrs.name+' preset default');
    if(attrs.type!=='number')continue;
    assert.ok(Number.isFinite(Number(attrs.value)),attrs.name);
    assert.ok(Number(attrs.value)>=Number(attrs.min),attrs.name+' minimum');
    if(attrs.max!==undefined)assert.ok(Number(attrs.value)<=Number(attrs.max),attrs.name+' maximum');
  }
});

test('adaptive comparison presets preserve the three-day baseline and isolate latency sensitivity',()=>{
  const read=name=>JSON.parse(readFileSync(new URL('../strategies/'+name,import.meta.url),'utf8')).parameters;
  const baseline=read('research-btc-paired-3day-validation-500ms-fee-10bp.json');
  const comparable=read('research-btc-paired-adaptive-3day-500ms-fee-10bp.json');
  const delayed=read('research-btc-paired-adaptive-3day-500ms-latency-100ms-fee-10bp.json');
  const added={paired_repricing_mode:'adaptive',paired_observation_delay_seconds:'0',paired_decision_delay_seconds:'0',paired_order_delay_seconds:'0'};
  assert.deepEqual(comparable,{...baseline,...added});
  assert.deepEqual(delayed,{...comparable,paired_observation_delay_seconds:'0.1',paired_decision_delay_seconds:'0.1',paired_order_delay_seconds:'0.1'});
  assert.equal(comparable.execution_interval_seconds,0.5);
  assert.equal(comparable.commodity_parameters.btc.trading_fee_bps,'10');
});

test('diagnostics retain the full attempt denominator and distinguish forecasts from realized returns',()=>{
  const context={fmt:(value,digits)=>value.toFixed(digits)};
  vm.runInNewContext(source('pairedTransferSummaryRows'),context);
  const paired={submitted_pairs:10,completed:3,partial:2,cancelled:1,timed_out:2,unresolved:2,max_unpaired_btc:0,
    latest_decision:{accepted:true,reason:'positive_net_gain',horizon_us:1782604800000000,source_symbol:'SPOT',target_symbol:'BTC-25SEP26',keep_btc:0.5,swap_btc:0.501,edge_btc:0.001,required_edge_btc:0.00025}};
  const rows=new Map(context.pairedTransferSummaryRows(paired));
  assert.equal(rows.get('All submitted transfer attempts'),'10');
  assert.equal(rows.get('Completed pairs'),'3');
  assert.equal(rows.get('Unresolved at end'),'2');
  assert.equal(rows.get('Largest unmatched quantity (BTC)'),'0.00000000');
  assert.equal(rows.get('Modeled KEEP wealth (BTC)'),'0.50000000');
  assert.equal(rows.get('Modeled extra gain vs KEEP (BTC)'),'0.00100000');
  assert.equal(rows.get('Required safety surplus (BTC)'),'0.00025000');
  const absent=new Map(context.pairedTransferSummaryRows({submitted_pairs:0,latest_decision:{accepted:false,reason:'stale_quote',horizon_us:null,edge_btc:0}}));
  assert.equal(absent.get('Latest evaluated candidate'),'KEEP / no new transfer');
  assert.ok(!absent.has('Modeled extra gain vs KEEP (BTC)'));
  assert.match(source('drawPairedTransferSummary'),/is not a realized return/);
  assert.match(source('drawPairedTransferSummary'),/not added across overlapping decisions/);
});

test('adaptive diagnostics expose saved latency and achieved lease without treating an unfilled pair as zero lease',()=>{
  const context={fmt:(value,digits)=>value.toFixed(digits)};
  vm.runInNewContext(source('pairedTransferSummaryRows'),context);
  const paired={repricing_mode:'adaptive',replacement_count:17,observation_delay_seconds:0.1,decision_delay_seconds:0.2,order_delay_seconds:0.35,spot_feed_delay_seconds:0.05,futures_feed_delay_seconds:0,response_delay_seconds:0.04,
    latest_pair_result:{pair_id:'pair-3',status:'partial',target_effective_lease:0.1234,executed_effective_lease:0.1214,effective_lease_shortfall:0.002,matched_source_btc:0.008}};
  const rows=new Map(context.pairedTransferSummaryRows(paired));
  assert.equal(rows.get('Limit repricing'),'Adaptive effective lease');
  assert.equal(rows.get('Limit replacements reaching the market'),'17');
  assert.equal(rows.get('Common observation delay (seconds)'),'0.100');
  assert.equal(rows.get('Decision delay (seconds)'),'0.200');
  assert.equal(rows.get('Order-to-market delay (seconds)'),'0.350');
  assert.equal(rows.get('Extra spot feed delay (seconds)'),'0.050');
  assert.equal(rows.get('Latest lease pair'),'pair-3');
  assert.equal(rows.get('Target net entry lease (annualized %)'),'12.3400');
  assert.equal(rows.get('Matched-fill net entry lease (annualized %)'),'12.1400');
  assert.equal(rows.get('Entry lease shortfall (annualized bps)'),'20.0000');
  assert.equal(rows.get('Latest lease pair matched source (BTC)'),'0.00800000');
  const unfilled=new Map(context.pairedTransferSummaryRows({...paired,latest_pair_result:{target_effective_lease:0.1234,executed_effective_lease:null}}));
  assert.equal(unfilled.get('Matched-fill net entry lease (annualized %)'),'Unavailable');
  assert.ok(!unfilled.has('Entry lease shortfall (annualized bps)'));
  assert.ok(!new Map(context.pairedTransferSummaryRows({})).has('Limit replacements reaching the market'));
  assert.match(source('drawPairedTransferSummary'),/entry-basis diagnostic/);
});

test('switching from benchmark export bounds resets the paired period and preserves microsecond endpoints',()=>{
  const nodes=Object.fromEntries(['tradeExportStart','tradeExportEnd','tradeApplyPeriod','tradeFullPeriod','tradeSpreadsheet','tradeCancelExport','tradeExportProgress'].map(id=>[id,{}]));
  nodes.tradeExportStart.value='2026-06-06T00:00:01';nodes.tradeExportEnd.value='2026-06-06T00:00:06';
  let aborted=false;
  const paired={summary:{start:'2026-06-25T00:00:00.106918',end:'2026-06-25T00:00:30.000000'},series:[]};
  const context={$:id=>nodes[id],last:paired,tradePeriodResult:{benchmark:true},tradeChartBounds:['old start','old end'],tradeExportController:{abort(){aborted=true}},downloadTradeSpreadsheet(){},drawTradeReplay(){}};
  vm.createContext(context);vm.runInContext(source('initializeTradePeriod')+'\n'+source('tradePeriod'),context);
  context.initializeTradePeriod();
  assert.equal(aborted,true);assert.equal(context.tradePeriodResult,paired);assert.equal(context.tradeChartBounds,null);
  assert.equal(nodes.tradeExportStart.value,'2026-06-25T00:00:00.106');
  assert.equal(nodes.tradeExportEnd.value,'2026-06-25T00:00:30.000');
  assert.equal(JSON.stringify(context.tradePeriod()),JSON.stringify([paired.summary.start,paired.summary.end]));
});

test('canonical and served HTML match and inline JavaScript compiles',()=>{
  assert.equal(readFileSync(new URL('../public/silver_strategy_gui.html',import.meta.url),'utf8'),html);
  for(const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(script[1]);
});
