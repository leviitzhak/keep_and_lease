import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html=readFileSync(new URL('../silver_strategy_gui.html',import.meta.url),'utf8');
const empiricalDefaults={paired_execution_confidence:'0.95',paired_execution_min_samples:'100',paired_calibration_days:'10',paired_waiting_seconds:'30',paired_execution_size_grid_btc:'0.0001,0.001,0.01,0.1',paired_study_max_horizon_seconds:'60'};
function source(name){
  const start=html.indexOf('function '+name+'(');
  assert.ok(start>=0,name);
  const end=html.indexOf('\nfunction ',start+1);
  return html.slice(start,end<0?undefined:end);
}

test('old parameter imports reset paired policy and costs while preserving explicit paired imports',()=>{
  const fields=new Map(['trade_strategy','paired_selection_mode','paired_horizon_days','paired_spot_fixed_fee_usd','paired_max_unpaired_btc','paired_repricing_mode','paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds'].map(key=>[key,{value:'prior paired run'}]));
  const context={form:{elements:{namedItem:name=>fields.get(name)}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity(){}};
  vm.runInNewContext(source('applyParameters'),context);
  context.applyParameters({});
  assert.equal(fields.get('trade_strategy').value,'legacy');
  assert.equal(fields.get('paired_selection_mode').value,'amortized_rank');
  assert.equal(fields.get('paired_horizon_days').value,'1,3,7,14,30');
  assert.equal(fields.get('paired_spot_fixed_fee_usd').value,'0');
  assert.equal(fields.get('paired_max_unpaired_btc').value,'0.01');
  assert.equal(fields.get('paired_repricing_mode').value,'fixed');
  for(const name of ['paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds'])assert.equal(fields.get(name).value,'0');
  context.applyParameters({trade_strategy:'cost_aware_paired',paired_spot_fixed_fee_usd:'1.75',paired_horizon_days:'0.25,1,3'});
  assert.equal(fields.get('trade_strategy').value,'cost_aware_paired');
  assert.equal(fields.get('paired_spot_fixed_fee_usd').value,'1.75');
  assert.equal(fields.get('paired_horizon_days').value,'0.25,1,3');
  assert.equal(fields.get('paired_selection_mode').value,'horizon_wealth');
  context.applyParameters({trade_strategy:'cost_aware_paired',paired_selection_mode:'amortized_rank'});
  assert.equal(fields.get('paired_selection_mode').value,'amortized_rank');
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

test('empirical imports preserve study settings and older presets reset them without changing repricing mode',()=>{
  const fields=new Map(['paired_repricing_mode',...Object.keys(empiricalDefaults)].map(name=>[name,{value:''}]));
  const context={form:{elements:{namedItem:name=>fields.get(name)}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity(){}};
  vm.runInNewContext(source('applyParameters'),context);
  context.applyParameters({paired_repricing_mode:'empirical',paired_execution_confidence:'0.9',paired_waiting_seconds:'20'});
  assert.equal(fields.get('paired_repricing_mode').value,'empirical');
  assert.equal(fields.get('paired_execution_confidence').value,'0.9');
  assert.equal(fields.get('paired_waiting_seconds').value,'20');
  context.applyParameters({paired_repricing_mode:'adaptive'});
  assert.equal(fields.get('paired_repricing_mode').value,'adaptive');
  for(const [name,value] of Object.entries(empiricalDefaults))assert.equal(fields.get(name).value,value);
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
  const values={trade_strategy:'cost_aware_paired',btc_data_source:'trade_tape',weight_btc:'100',weight_silver:'0',weight_gold:'0',weight_sp500:'0',weight_treasury:'0',paired_selection_mode:'horizon_wealth',paired_horizon_days:'1,3,7,14,30',paired_max_horizon_days:'30',paired_max_transfer_fraction:'0.25',paired_max_delta_btc:'0.01',paired_min_improvement_bps:'5',paired_conservative_lease_bps:'0',paired_repricing_mode:'fixed',paired_observation_delay_seconds:'0',paired_decision_delay_seconds:'0',paired_order_delay_seconds:'0',...empiricalDefaults,...overrides};
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

test('amortized ranking ignores horizon grids and rejects empirical execution',()=>{
  assert.doesNotThrow(()=>validationContext({paired_selection_mode:'amortized_rank',paired_horizon_days:'not used'}).validatePairedForm());
  assert.throws(()=>validationContext({paired_selection_mode:'amortized_rank',paired_repricing_mode:'empirical'}).validatePairedForm(),/calibrated only/);
  for(const [name,value] of [['paired_max_delta_btc','0'],['paired_min_improvement_bps','-1'],['paired_conservative_lease_bps','NaN']]){
    assert.throws(()=>validationContext({paired_selection_mode:'amortized_rank',[name]:value}).validatePairedForm(),/must be|buffers/);
  }
});

test('rolling worst lease validates its selector, time window and distinct slippage units',()=>{
  const rolling={paired_selection_mode:'amortized_rank',paired_repricing_mode:'rolling_worst',
    paired_lease_window_seconds:'5',paired_lease_execution_delta_bps:'5',paired_expected_hedge_slippage_bps:'1'};
  assert.doesNotThrow(()=>validationContext(rolling).validatePairedForm());
  assert.doesNotThrow(()=>validationContext({...rolling,paired_limit_anchor:'spot'}).validatePairedForm());
  assert.throws(()=>validationContext({...rolling,paired_limit_anchor:'unknown'}).validatePairedForm(),/limit anchor/);
  assert.throws(()=>validationContext({...rolling,paired_selection_mode:'horizon_wealth'}).validatePairedForm(),/requires expiry/);
  for(const override of [{paired_lease_window_seconds:'0'},{paired_lease_execution_delta_bps:'-1'},
    {paired_expected_hedge_slippage_bps:'10000'},{paired_expected_hedge_slippage_bps:'NaN'}]){
    assert.throws(()=>validationContext({...rolling,...override}).validatePairedForm(),/Rolling window/);
  }
});

test('rolling imports preserve explicit values and reset missing settings',()=>{
  const fields=new Map(['paired_repricing_mode','paired_lease_window_seconds','paired_lease_execution_delta_bps','paired_expected_hedge_slippage_bps'].map(name=>[name,{value:''}]));
  const context={form:{elements:{namedItem:name=>fields.get(name)}},LEG_FIELDS:[],COMMODITIES:['btc'],loadCommodity(){}};
  vm.runInNewContext(source('applyParameters'),context);
  context.applyParameters({paired_repricing_mode:'rolling_worst',paired_lease_window_seconds:'15',paired_lease_execution_delta_bps:'25',paired_expected_hedge_slippage_bps:'3'});
  assert.equal(fields.get('paired_lease_window_seconds').value,'15');
  assert.equal(fields.get('paired_lease_execution_delta_bps').value,'25');
  assert.equal(fields.get('paired_expected_hedge_slippage_bps').value,'3');
  context.applyParameters({});
  assert.equal(fields.get('paired_repricing_mode').value,'fixed');
  assert.equal(fields.get('paired_lease_window_seconds').value,'5');
});

test('repricing validates its mode and three independent nonnegative delays',()=>{
  assert.doesNotThrow(()=>validationContext({paired_repricing_mode:'adaptive',paired_observation_delay_seconds:'0.2',paired_decision_delay_seconds:'0.1',paired_order_delay_seconds:'0.3'}).validatePairedForm());
  assert.throws(()=>validationContext({paired_repricing_mode:'market'}).validatePairedForm(),/repricing/);
  for(const name of ['paired_observation_delay_seconds','paired_decision_delay_seconds','paired_order_delay_seconds']){
    for(const value of ['',' ','-0.1','NaN','Infinity'])assert.throws(()=>validationContext({[name]:value}).validatePairedForm(),/finite, nonnegative/);
  }
});

test('empirical controls validate confidence, sample size, a covered deadline and ordered size buckets',()=>{
  const validate=overrides=>validationContext({paired_repricing_mode:'empirical',...overrides}).validatePairedForm();
  assert.doesNotThrow(()=>validate({}));
  assert.doesNotThrow(()=>validate({paired_calibration_days:'0.5',paired_waiting_seconds:'60'}));
  for(const value of ['0','1','NaN','Infinity',''])assert.throws(()=>validate({paired_execution_confidence:value}),/confidence/);
  for(const value of ['0','1.5','NaN','Infinity',''])assert.throws(()=>validate({paired_execution_min_samples:value}),/positive integer/);
  for(const overrides of [{paired_calibration_days:'0'},{paired_waiting_seconds:'0'},{paired_waiting_seconds:'61'},{paired_study_max_horizon_seconds:'NaN'}])assert.throws(()=>validate(overrides),/study wait/);
  for(const value of ['','0,1','0.1,0.01','0.01,0.01','0.1,','0.1,Infinity'])assert.throws(()=>validate({paired_execution_size_grid_btc:value}),/strictly increasing/);
  assert.doesNotThrow(()=>validationContext({paired_repricing_mode:'adaptive',paired_execution_confidence:'invalid unused value'}).validatePairedForm());
});

test('empirical settings appear only for the empirical policy and remain serializable when inactive',()=>{
  const values={btc_data_source:'trade_tape',trade_strategy:'cost_aware_paired',paired_repricing_mode:'empirical',...empiricalDefaults};
  const elements=Object.entries(values).map(([name,value])=>({name,value,disabled:false,closest:()=>null}));
  elements.namedItem=name=>elements.find(field=>field.name===name);
  const nodes=Object.fromEntries(['tradeReplayControls','pairedTransferControls','pairedLegacyNotice','pairedEmpiricalControls','previewLongScore','previewShortScore'].map(id=>[id,{}]));
  const context={form:{elements},$:id=>nodes[id],captureCommodity(){},commodityProfiles:{btc:{}},FormData:class{constructor(form){this.form=form}entries(){return this.form.elements.filter(field=>!field.disabled).map(field=>[field.name,field.value])}}};
  vm.runInNewContext(source('updateTradeControls')+'\n'+html.split('\n').find(line=>line.startsWith('function values(')),context);
  context.updateTradeControls();
  assert.equal(nodes.pairedEmpiricalControls.hidden,false);
  assert.equal(elements.namedItem('paired_execution_confidence').disabled,false);
  elements.namedItem('paired_repricing_mode').value='adaptive';context.updateTradeControls();
  assert.equal(nodes.pairedEmpiricalControls.hidden,true);
  assert.equal(elements.namedItem('paired_execution_confidence').disabled,true);
  assert.equal(context.values().paired_execution_confidence,'0.95');
});

test('paired preset is bounded and every paired numeric default satisfies browser constraints',()=>{
  const preset=JSON.parse(readFileSync(new URL('../strategies/research-btc-cost-aware-paired.json',import.meta.url),'utf8'));
  assert.equal(preset.parameters.trade_strategy,'cost_aware_paired');
  assert.equal(preset.parameters.btc_data_source,'trade_tape');
  assert.equal(Date.parse(preset.parameters.backtest_end)-Date.parse(preset.parameters.backtest_start),300000);
  const migrationDefaults={paired_observation_delay_seconds:'0',paired_decision_delay_seconds:'0',paired_order_delay_seconds:'0',...empiricalDefaults};
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

test('empirical ten-day preset preserves matched adaptive settings and strictly separates calibration from scoring',()=>{
  const read=name=>JSON.parse(readFileSync(new URL('../strategies/'+name,import.meta.url),'utf8'));
  const baseline=read('research-btc-paired-adaptive-10day-500ms-latency-100ms-fee-10bp.json');
  const preset=read('research-btc-paired-empirical-10day-500ms-latency-100ms-fee-10bp.json');
  assert.deepEqual(preset.parameters,{...baseline.parameters,paired_repricing_mode:'empirical',...empiricalDefaults});
  assert.equal(Date.parse(preset.parameters.backtest_start+'Z'),Date.parse('2026-06-16T00:00:00Z'));
  assert.equal(Date.parse(preset.parameters.backtest_end+'Z'),Date.parse('2026-06-26T00:00:00Z'));
  assert.equal(preset.parameters.execution_interval_seconds,0.5);
  assert.equal(preset.parameters.paired_observation_delay_seconds,'0.1');
  assert.match(preset.research_assumptions.execution_study.calibration_period,/2026-06-06T00:00:00, 2026-06-16T00:00:00/);
  assert.match(preset.research_assumptions.execution_study.causality,/No test-period refitting/);
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

test('empirical diagnostics preserve unsuccessful attempts and distinguish forecasts, waits and slippage units',()=>{
  const context={fmt:(value,digits)=>value.toFixed(digits)};
  vm.runInNewContext(source('pairedTransferSummaryRows'),context);
  const paired={repricing_mode:'empirical',empirical_execution:{instructions:5,completed_by_deadline:2,deadline_failed:2,partial_at_deadline:1,unfilled_at_deadline:1,end_window_censored:1,completion_probability:0.5,completion_probability_denominator:4,predicted_completion_probability_mean:0.95,prediction_count:5,wait_seconds:{instruction:{count:2,mean:4,p50:3,p95:5,max:5}},actual_slippage_bps:{count:3,p95:2.5},annualized_slippage_bps:{count:3,p95:365},latest_instruction:{pair_id:'pair-5',status:'end_window_censored',predicted_completion_probability:0.93,actual_slippage_bps:null}},latest_decision:{diagnostics:{execution_model:{model_id:'frozen-1',scope:'maturity_bucket',samples:120},execution_joint_success_probability:0.94,execution_budget_bps:8,expected_edge_btc:0.0003,conservative_budget_edge_btc:0.0001}}};
  const rows=new Map(context.pairedTransferSummaryRows(paired));
  assert.equal(rows.get('Limit repricing'),'Empirical completion deadline');
  assert.equal(rows.get('Empirical execution instructions'),'5');
  assert.equal(rows.get('Missed execution deadline'),'2');
  assert.equal(rows.get('Scored-window censored instructions'),'1');
  assert.equal(rows.get('Actual completion by deadline (%)'),'50.00');
  assert.equal(rows.get('Mean predicted completion by deadline (%)'),'95.00');
  assert.equal(rows.get('Instructions with a completion prediction'),'5');
  assert.equal(rows.get('Instruction elapsed wait sample count'),'2');
  assert.equal(rows.get('Matched price-basis slippage p95 (bps)'),'2.5000');
  assert.equal(rows.get('Matched annualized lease slippage p95 (bps)'),'365.0000');
  assert.equal(rows.get('Latest empirical outcome'),'end window censored');
  assert.ok(!rows.has('Latest actual price-basis slippage (bps)'));
  assert.equal(rows.get('Modeled joint completion probability (%)'),'94.00');
  assert.equal(rows.get('Scenario-weighted extra BTC vs KEEP'),'0.00030000');
});

test('study tables include nonfill counts and select quantity and maturity without inventing missing quantiles',()=>{
  const context={fmt:(value,digits)=>value.toFixed(digits)};
  vm.runInNewContext(source('executionStudySummaryRows')+'\n'+source('executionStudyGroupRows'),context);
  const common={scope:'maturity_bucket',maturity_bucket:'near',quantity_btc:0.01,samples:100,raw_basis_slip_quantiles_bps:{p50:2,p95:10},annualized_slip_quantiles_bps:{p50:73,p95:365}};
  const study={calibration_start_us:1780704000000000,calibration_end_us:1781568000000000,label_cutoff_us:1781568000000000,cohorts_started:101,cohorts_excluded_at_cutoff:1,labels:100,completed_labels:80,partial_labels:10,unfilled_labels:10,group_summaries:[{...common,wait_seconds:30,completion_probability:0.8,joint_budget_quantiles_bps:{p50:4,p75:7,p90:null,p95:null}},{...common,wait_seconds:10,completion_probability:0.5},{...common,quantity_btc:0.1,wait_seconds:30,completion_probability:0.2},{...common,maturity_bucket:'far',wait_seconds:30,completion_probability:0.99}]};
  const summary=new Map(context.executionStudySummaryRows(study));
  assert.equal(summary.get('Completed calibration labels'),'80');
  assert.equal(summary.get('Unfilled calibration labels'),'10');
  assert.equal(summary.get('Cohorts censored at calibration cutoff'),'1');
  const rows=context.executionStudyGroupRows(study,'maturity_bucket|near','0.01');
  assert.equal(rows.length,2);
  assert.equal(rows[0][0],'10.000');
  assert.equal(rows[1][1],'100');
  assert.equal(rows[1][2],'80.00%');
  assert.equal(rows[1][3],'4.0000 / 7.0000 / Unavailable / Unavailable');
  assert.equal(rows[1][4],'2.0000 / Unavailable / Unavailable / 10.0000');
  assert.equal(rows[1][5],'73.0000 / Unavailable / Unavailable / 365.0000');
  assert.equal(context.executionStudyGroupRows(study,'maturity_bucket|near',0.1)[0][2],'20.00%');
  assert.equal(context.executionStudyGroupRows(study,'maturity_bucket|missing',0.01).length,0);
  assert.match(source('drawExecutionStudy'),/original maturity, not its waiting time/);
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
