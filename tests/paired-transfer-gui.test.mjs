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
  const fields=new Map(['trade_strategy','paired_horizon_days','paired_spot_fixed_fee_usd','paired_max_unpaired_btc'].map(key=>[key,{value:'prior paired run'}]));
  const context={form:{elements:{namedItem:name=>fields.get(name)}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity(){}};
  vm.runInNewContext(source('applyParameters'),context);
  context.applyParameters({});
  assert.equal(fields.get('trade_strategy').value,'legacy');
  assert.equal(fields.get('paired_horizon_days').value,'1,3,7,14,30');
  assert.equal(fields.get('paired_spot_fixed_fee_usd').value,'0');
  assert.equal(fields.get('paired_max_unpaired_btc').value,'0.01');
  context.applyParameters({trade_strategy:'cost_aware_paired',paired_spot_fixed_fee_usd:'1.75',paired_horizon_days:'0.25,1,3'});
  assert.equal(fields.get('trade_strategy').value,'cost_aware_paired');
  assert.equal(fields.get('paired_spot_fixed_fee_usd').value,'1.75');
  assert.equal(fields.get('paired_horizon_days').value,'0.25,1,3');
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
  const names=['btc_data_source','trade_strategy','min_days','long_score_rate_scale','short_pure_maturity_strength','enable_short_book','trading_fee_bps','execution_delay_seconds'];
  const elements=names.map(name=>({name,value:name==='btc_data_source'?'trade_tape':name==='trade_strategy'?'cost_aware_paired':'3',disabled:false,closest:()=>null}));
  elements.namedItem=name=>elements.find(field=>field.name===name);
  const nodes=Object.fromEntries(['tradeReplayControls','pairedTransferControls','pairedLegacyNotice','previewLongScore','previewShortScore'].map(id=>[id,{}]));
  const context={form:{elements},$:id=>nodes[id],captureCommodity(){},commodityProfiles:{btc:{}},FormData:class{constructor(form){this.form=form}entries(){return this.form.elements.filter(field=>!field.disabled).map(field=>[field.name,field.value])}}};
  vm.runInNewContext(source('updateTradeControls')+'\n'+html.split('\n').find(line=>line.startsWith('function values(')),context);
  context.updateTradeControls();
  assert.equal(elements.namedItem('min_days').disabled,true);
  assert.equal(elements.namedItem('long_score_rate_scale').disabled,true);
  assert.equal(elements.namedItem('trading_fee_bps').disabled,false);
  assert.equal(elements.namedItem('execution_delay_seconds').disabled,false);
  assert.equal(elements.namedItem('enable_short_book').disabled,false);
  assert.equal(nodes.pairedLegacyNotice.hidden,false);
  assert.equal(nodes.previewLongScore.hidden,true);
  assert.equal(context.values().min_days,'3');
  elements.namedItem('trade_strategy').value='legacy';context.updateTradeControls();
  assert.equal(elements.namedItem('min_days').disabled,false);
  assert.equal(nodes.previewLongScore.hidden,false);
  assert.equal(nodes.pairedLegacyNotice.hidden,true);
});

function validationContext(overrides={},profile={}){
  const values={trade_strategy:'cost_aware_paired',btc_data_source:'trade_tape',weight_btc:'100',weight_silver:'0',weight_gold:'0',weight_sp500:'0',weight_treasury:'0',paired_horizon_days:'1,3,7,14,30',paired_max_horizon_days:'30',...overrides};
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

test('paired preset is bounded and every paired numeric default satisfies browser constraints',()=>{
  const preset=JSON.parse(readFileSync(new URL('../strategies/research-btc-cost-aware-paired.json',import.meta.url),'utf8'));
  assert.equal(preset.parameters.trade_strategy,'cost_aware_paired');
  assert.equal(preset.parameters.btc_data_source,'trade_tape');
  assert.equal(Date.parse(preset.parameters.backtest_end)-Date.parse(preset.parameters.backtest_start),300000);
  for(const tag of html.matchAll(/<input\b[^>]*name="paired_[^>]*>/g)){
    const attrs=Object.fromEntries([...tag[0].matchAll(/([\w-]+)="([^"]*)"/g)].map(match=>[match[1],match[2]]));
    assert.equal(String(preset.parameters[attrs.name]),attrs.value,attrs.name+' preset default');
    if(attrs.type!=='number')continue;
    assert.ok(Number.isFinite(Number(attrs.value)),attrs.name);
    assert.ok(Number(attrs.value)>=Number(attrs.min),attrs.name+' minimum');
    if(attrs.max!==undefined)assert.ok(Number(attrs.value)<=Number(attrs.max),attrs.name+' maximum');
  }
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

test('canonical and served HTML match and inline JavaScript compiles',()=>{
  assert.equal(readFileSync(new URL('../public/silver_strategy_gui.html',import.meta.url),'utf8'),html);
  for(const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g))new vm.Script(script[1]);
});
