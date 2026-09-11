/* Read-only plot adapters. Sampling never changes the execution clock or accounting. */
(function (global) {
  'use strict';
  const finite = v => v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v);
  const add = (...xs) => xs.every(x => x !== null) ? xs.reduce((a,b)=>a+b,0) : null;
  const divide = (a,b) => a !== null && b !== null && b !== 0 ? a/b : null;
  const percent = (a,b) => {const v=divide(a,b);return v===null?null:100*(v-1);};
  const getter = fields => {const indexes=new Map(fields.map((f,i)=>[f,i]));return (r,k)=>indexes.has(k)?finite(r[indexes.get(k)]):null;};
  const raw = (fields,r,k) => fields.includes(k)?r[fields.indexOf(k)]:null;
  const product = (a,b) => a===null||b===null?null:a*b;
  const colors=['#16a34a','#2563eb','#64748b','#dc2626','#d97706','#7c3aed'];

  function replayModel(result) {
    const fields=result.fields||[],g=getter(fields),capital=finite(result.trade_replay?.capital_usd);
    if(!(capital>0))return {name:'BTC replay',rows:[],reason:'Configured initial capital is missing.'};
    const rows=(result.series||[]).map(r=>{
      const nav=g(r,'nav'),direct=g(r,'direct_nav'),cash=g(r,'cash_usd'),spot=g(r,'spot_value_usd');
      const long=g(r,'futures_notional_usd'),gross=long===null?null:Math.abs(long),pnl=g(r,'market_pnl_usd');
      const interest=g(r,'treasury_interest_usd'),fees=g(r,'fees_usd');
      const error=g(r,'reconstruction_error_usd');
      const balance=add(cash,spot),underlying=divide(nav,direct);
      return {date:r[0],start:r[0],sourceDate:r[0],nav,direct,cash,spot,long,short:null,
        target:g(r,'target_futures_notional_usd'),gross,
        free:g(r,'free_collateral_usd')??(cash!==null&&gross!==null?cash-gross:null),
        ratio:g(r,'collateralization_ratio')??divide(cash,gross),turnover:g(r,'turnover_usd'),fees,
        age:g(r,'max_mark_age_seconds'),price:g(r,'spot_price'),future:g(r,'long_weighted_future_price'),
        premium:g(r,'long_weighted_forward_premium_pct'),leaseRate:g(r,'long_weighted_lease_rate_pct'),
        maturity:g(r,'long_weighted_maturity_days'),yield:g(r,'treasury_yield_pct'),
        treasuryIndex:g(r,'treasury_accrual_index'),
        underlyingPrice:direct,leaseValue:underlying,keepValue:null,totalUnderlying:underlying,
        directUnderlying:divide(spot,product(capital,direct)),futureUnderlying:divide(cash,product(capital,direct)),
        reconstructed:error!==null&&nav!==null?nav-error/capital:null,
        balanceNav:divide(balance,capital),error:error===null?null:error/capital,
        marketPnl:pnl,spotPnl:g(r,'spot_pnl_usd'),futurePnl:g(r,'futures_pnl_usd'),interest,
        holdings:raw(fields,r,'held_futures')||[],
      };
    });
    return finish({name:'Bitcoin',kind:'replay',rows,capital,money:'USD',
      turnoverLabel:'All actual simulated fills',sampling:result.trade_replay?.plot_sample_every||1,
      note:'USD values use configured capital. Futures are exposure, not an extra cash asset. The long-only replay has no keep/short book. Historical snapshots may lack newer diagnostics.'});
  }

  function dailyModel(sleeve, key) {
    const fields=sleeve.fields||[],g=getter(fields),held=sleeve.held_futures_diagnostics||[];
    const observed=sleeve.execution?.model==='observed';
    const rows=(sleeve.series||[]).map((r,i)=>{
      const end=g(r,'compounded_return_pct'),nav=end===null?null:1+end/100,ret=g(r,'interval_return_pct');
      const startNav=divide(nav,ret===null?null:1+ret/100);
      const value=k=>product(startNav,divide(g(r,k),100));
      const cash=g(r,'plot_cash_start')??value('treasury_weight_pct'),spot=g(r,'plot_spot_start')??value('slv_weight_pct');
      const long=g(r,'plot_long_start')??value('long_futures_notional_pct');
      const short=g(r,'plot_short_start')??value('short_futures_notional_pct');
      const gross=add(long===null?null:Math.abs(long),short===null?null:Math.abs(short));
      const direct=g(r,'slv_compounded_return_pct');
      return {date:raw(fields,r,'exit_date')||r[0],start:r[0],sourceDate:r[0],nav,
        direct:direct===null?null:1+direct/100,returnPct:ret,cash,spot,long,short,gross,
        target:g(r,'plot_target_start')??(!observed?gross:null),free:cash!==null&&gross!==null?cash-gross:null,ratio:divide(cash,gross),
        turnover:g(r,'plot_turnover_total'),fees:g(r,'plot_cost_total'),age:g(r,'plot_mark_age_seconds'),
        price:g(r,'slv_price'),future:g(r,'long_weighted_future_price'),shortFuture:g(r,'short_weighted_future_price'),
        premium:g(r,'long_weighted_forward_premium_pct'),shortPremium:g(r,'short_weighted_forward_premium_pct'),
        leaseRate:g(r,'long_weighted_lease_rate_pct'),shortLeaseRate:g(r,'short_weighted_lease_rate_pct'),
        maturity:g(r,'long_weighted_maturity_days'),shortMaturity:g(r,'short_weighted_maturity_days'),
        yield:g(r,'long_matched_usd_rate_pct'),treasuryIndex:divide(g(r,'treasury_position_price_index'),100),
        underlyingPrice:g(r,'underlying_price_index'),leaseValue:g(r,'lease_book_underlying_value'),keepValue:g(r,'keep_book_underlying_value'),
        directUnderlying:g(r,'replicating_leg_underlying_value'),futureUnderlying:g(r,'futures_treasury_underlying_value'),
        totalUnderlying:add(g(r,'lease_book_underlying_value'),g(r,'keep_book_underlying_value')),
        leaseReturn:g(r,'lease_book_underlying_daily_return_pct'),keepReturn:g(r,'keep_book_underlying_daily_return_pct'),
        leaseIndex:g(r,'lease_book_underlying_compounded_index'),keepIndex:g(r,'keep_book_underlying_compounded_index'),
        combinedIndex:g(r,'combined_books_underlying_compounded_index'),
        reconstructed:g(r,'reconstructed_nav'),error:g(r,'nav_reconstruction_difference'),
        directReturn:g(r,'slv_daily_return_pct'),longReturn:g(r,'long_futures_daily_return_pct'),
        shortReturn:g(r,'short_futures_daily_return_pct'),treasuryReturn:g(r,'treasury_daily_return_pct'),
        holdings:held[i]||[]};
    });
    const first=sleeve.series?.[0],initial=first?{date:first[0],start:first[0],sourceDate:first[0],nav:1,direct:1,drawdown:0,directDrawdown:0,
      underlyingPrice:1,leaseValue:1,keepValue:null,totalUnderlying:1,leaseIndex:1,keepIndex:null,combinedIndex:1,reconstructed:1,error:0,
      directUnderlying:g(first,'initial_replicating_leg_value'),futureUnderlying:g(first,'initial_futures_treasury_value')}:null;
    return finish({name:sleeve.product_label||key,kind:'daily',rows,initial,capital:1,money:'value per initial 1',
      turnoverLabel:observed?'All simulated candle fills':'Modelled futures trades only',
      sampling:sleeve.plot_sample_every||((sleeve.summary?.observations||rows.length)>rows.length?2:1),
      distributions:sleeve.book_return_distributions||[],
      note:'Daily/candle values are per initial sleeve capital of 1. Exposures, costs and turnover are dated at interval start; NAV and returns at interval end. The gross collateral ratio is descriptive, not a margin requirement. Legacy-close turnover covers modelled futures trades, not observed market fills.'});
  }

  function finish(model) {
    model.hasShort=model.rows.some(r=>r.short!==null&&Math.abs(r.short)>1e-12);
    if(!model.hasShort)for(const r of model.rows)for(const key of ['short','shortReturn','shortFuture','shortPremium','shortLeaseRate','shortMaturity','keepValue','keepReturn','keepIndex'])r[key]=null;
    let peak=1,directPeak=1,previous=null;
    for(const r of model.rows){
      if(r.nav!==null){peak=Math.max(peak,r.nav);r.drawdown=percent(r.nav,peak);}
      if(r.direct!==null){directPeak=Math.max(directPeak,r.direct);r.directDrawdown=percent(r.direct,directPeak);}
      if(model.kind==='replay'){
        r.returnPct=previous?percent(r.nav,previous.nav):null;
        r.leaseReturn=previous?percent(r.totalUnderlying,previous.totalUnderlying):null;
        r.leaseIndex=r.totalUnderlying;r.combinedIndex=r.totalUnderlying;
        for(const [dest,source] of [['directReturn','spotPnl'],['longReturn','futurePnl'],['treasuryReturn','interest']]){
          const a=r[source],b=previous?.[source];
          r[dest]=previous&&a!==null&&b!==null?divide(100*(a-b),product(previous.nav,model.capital)):null;
        }
      }
      // Difference full cumulative counters BEFORE applying the chart period.
      r.volume=r.turnover!==null?(previous?(previous.turnover!==null?r.turnover-previous.turnover:null):r.turnover):null;
      r.cost=r.fees!==null?(previous?(previous.fees!==null?r.fees-previous.fees:null):r.fees):null;
      if(r.volume!==null&&r.volume<0)r.volume=null;
      previous=r;
    }
    return model;
  }

  // A common catalog, not a separate set of hard-coded replay row indexes.
  const catalog=[
    {id:'nav',group:'overview',title:'Strategy versus direct holding',unit:'NAV (initial = 1)',series:[['nav','Strategy'],['direct','Direct holding']]},
    {id:'drawdown',group:'overview',title:'Drawdowns from full-run high-water marks',unit:'%',series:[['drawdown','Strategy'],['directDrawdown','Direct holding']]},
    {id:'returns',group:'overview',title:'Strategy returns',unit:'%',series:[['returnPct','Strategy return']]},
    {id:'distribution',group:'overview',title:'Strategy return distribution',hist:'returnPct'},
    {id:'holdings',group:'execution',title:'Direct holding, cash/Treasuries and futures exposure',money:true,start:true,series:[['spot','Direct holding'],['cash','Cash / Treasuries'],['long','Long futures'],['short','Short futures']]},
    {id:'target',group:'execution',title:'Futures target versus actual gross exposure',money:true,start:true,series:[['target','Target gross futures'],['gross','Actual gross futures']]},
    {id:'free-collateral',group:'execution',title:'Free collateral: cash/Treasuries minus gross futures',money:true,start:true,series:[['free','Free collateral']]},
    {id:'collateral-ratio',group:'execution',title:'Cash/Treasuries to gross futures ratio',unit:'ratio',start:true,series:[['ratio','Collateral ratio']]},
    {id:'volume',group:'activity',title:'Traded volume between displayed observations',money:true,start:true,series:[['volume','Traded notional']]},
    {id:'turnover',group:'activity',title:'Cumulative traded notional',money:true,start:true,series:[['turnover','Cumulative traded notional']]},
    {id:'fees',group:'activity',title:'Cumulative recorded trading costs',money:true,start:true,series:[['fees','Trading costs']]},
    {id:'mark-age',group:'activity',title:'Oldest held valuation mark',unit:'seconds',start:true,series:[['age','Oldest held mark age']]},
    {id:'prices',group:'market',title:'Spot and held futures prices',unit:'price',start:true,series:[['price','Spot'],['future','Held long weighted'],['shortFuture','Held short weighted']]},
    {id:'premiums',group:'market',title:'Held futures premiums',unit:'%',start:true,series:[['premium','Long'],['shortPremium','Short']]},
    {id:'lease-rates',group:'market',title:'Held futures implied lease rates',unit:'% annualized',start:true,series:[['leaseRate','Long'],['shortLeaseRate','Short']]},
    {id:'maturities',group:'market',title:'Held futures weighted maturities',unit:'days',start:true,series:[['maturity','Long'],['shortMaturity','Short']]},
    {id:'lease-scatter',group:'curves',title:'Held lease rates versus maturity',scatter:'lease_pct',unit:'% annualized'},
    {id:'premium-scatter',group:'curves',title:'Held premiums versus maturity',scatter:'premium_pct',unit:'%'},
    {id:'yield',group:'rates',title:'Observable Treasury yield',unit:'% annualized',start:true,series:[['yield','Treasury yield']]},
    {id:'treasury-index',group:'rates',title:'Treasury return / accrual index',unit:'index (initial = 1)',series:[['treasuryIndex','Treasury index']]},
    {id:'underlying',group:'rates',title:'Underlying price evolution',unit:'price index',series:[['underlyingPrice','Underlying price']]},
    {id:'legs',group:'rates',title:'Returns by leg',unit:'%',series:[['directReturn','Direct holding'],['longReturn','Long futures'],['shortReturn','Short futures'],['treasuryReturn','Treasury']]},
    {id:'lease-values',group:'books',title:'Unextended lease book in underlying equivalents',unit:'initial-commodity equivalents',series:[['directUnderlying','Direct holding'],['futureUnderlying','Futures + Treasuries'],['leaseValue','Lease total']]},
    {id:'keep-value',group:'books',title:'Keep book in underlying equivalents',unit:'initial-commodity equivalents',series:[['keepValue','Keep book']]},
    {id:'book-returns',group:'books',title:'Commodity-quoted book return contributions',unit:'%',series:[['leaseReturn','Lease'],['keepReturn','Keep']]},
    {id:'book-indexes',group:'books',title:'Compounded commodity-quoted book indexes',unit:'index (initial = 1)',series:[['leaseIndex','Lease'],['keepIndex','Keep'],['combinedIndex','Combined']]},
    {id:'lease-distribution',group:'reconciliation',title:'Lease return distribution',hist:'leaseReturn'},
    {id:'keep-distribution',group:'reconciliation',title:'Keep return distribution',hist:'keepReturn'},
    {id:'reconstruction',group:'reconciliation',title:'NAV reconstruction check',unit:'NAV (initial = 1)',series:[['nav','Strategy NAV'],['reconstructed','Accounting reconstruction'],['balanceNav','Cash + spot identity']]},
    {id:'reconstruction-error',group:'reconciliation',title:'Accounting reconstruction difference',unit:'per initial capital',series:[['error','Reconstruction difference']]},
  ];
  const groups={overview:'Performance',execution:'Holdings and collateral',activity:'Volume, costs and quote age',market:'Prices, premiums, lease rates and maturities',rates:'Rates and returns by leg',curves:'Held-contract maturity scatters',books:'Lease / keep book decomposition',reconciliation:'Distributions and reconstruction'};

  function models(result, sources) {
    if(result?.result_kind==='btc_trade_replay')return {btc:replayModel(result)};
    return Object.fromEntries(Object.entries(result?.commodity_sleeves||{}).map(([key,s])=>{
      const original=sources?.[key];return [key,dailyModel(original?{...s,series:original.series,held_futures_diagnostics:original.heldFuturesDiagnostics||s.held_futures_diagnostics,book_return_distributions:original.returnDistributions||s.book_return_distributions}:s,key)];
    }));
  }
  function selectRows(model, accept=()=>true) {return model.rows.filter(r=>accept(r.sourceDate));}
  function absent(model,def) {
    if(!model.hasShort&&['keep-value','keep-distribution'].includes(def.id))return 'Not applicable: no keep/short book is active in this run.';
    if(model.kind==='daily'&&def.id==='mark-age')return 'Not recorded by this daily/legacy execution model; quote timing cannot be inferred from dates alone.';
    return 'Unavailable in this saved result. New runs record additional plot diagnostics; historical data are not invented or backfilled.';
  }
  function disposeCanvases(container, releaseCanvas) {
    for (const canvas of container.querySelectorAll('canvas')) {
      releaseCanvas?.(canvas);
      canvas.onmousemove=canvas.onclick=canvas.onmouseleave=null;
      canvas.width=canvas.height=0;
    }
  }
  function render({result,root,sources,accept,lineChart,histogramChart,scatterChart,annotate,releaseCanvas}) {
    if(!root||!result)return;
    const doc=root.ownerDocument;
    let panel=doc.getElementById('sharedRunPlots');
    if(!panel){
      panel=doc.createElement('section');panel.id='sharedRunPlots';panel.className='statistics-panel';
      const h=doc.createElement('h2');h.textContent='Shared daily / trade-replay plots';panel.append(h);
      const controls=doc.createElement('div');controls.className='plot-range';
      for(const [id,text] of [['sharedPlotCommodity','Commodity'],['sharedPlotGroup','Plot family']]){
        const label=doc.createElement('label');label.textContent=text+' ';const input=doc.createElement('select');input.id=id;label.append(input);controls.append(label);
      }
      panel.append(controls);
      for(const [id,tag] of [['sharedPlotNote','p'],['sharedPlotStats','p'],['sharedPlotCards','div']]){
        const el=doc.createElement(tag);el.id=id;if(tag==='p')el.className='statistics-note';panel.append(el);
      }
      root.append(panel);
    }
    panel.hidden=false;
    const all=models(result,sources),commodity=doc.getElementById('sharedPlotCommodity'),group=doc.getElementById('sharedPlotGroup');
    const chosen=commodity.value,selectedGroup=group.value;
    commodity.replaceChildren();for(const [key,m] of Object.entries(all)){const option=doc.createElement('option');option.value=key;option.textContent=m.name;commodity.append(option);}
    if(all[chosen])commodity.value=chosen;
    if(!group.options.length)for(const [key,title] of Object.entries(groups)){const option=doc.createElement('option');option.value=key;option.textContent=title;group.append(option);}
    group.value=selectedGroup|| (result.result_kind==='btc_trade_replay'?'books':'execution');
    function draw(){
      const m=all[commodity.value],cards=doc.getElementById('sharedPlotCards');disposeCanvases(cards,releaseCanvas);cards.replaceChildren();
      if(!m){doc.getElementById('sharedPlotNote').textContent='No commodity sleeve in this run. The portfolio charts remain available above.';doc.getElementById('sharedPlotStats').textContent='';return;}
      const rows=selectRows(m,accept),sampled=m.sampling>1,interval=m.kind==='replay'?'between displayed valuations':'for each recorded execution interval';
      doc.getElementById('sharedPlotNote').textContent=m.note+' Returns are '+interval+(sampled?'; chart sampling is active, not a change in execution frequency.':' .')+' All panels follow the existing chart-period controls. Volume uses cumulative-counter differences before period filtering. '+m.turnoverLabel+'.';
      const values=rows.map(r=>r.returnPct).filter(v=>v!==null),mean=values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
      let low=null,high=null;for(const v of values){low=low===null?v:Math.min(low,v);high=high===null?v:Math.max(high,v);}
      doc.getElementById('sharedPlotStats').textContent=rows.length+' displayed observations · '+values.length+' return observations'+(mean===null?'':` · mean ${mean.toFixed(6)}% · min ${low.toFixed(6)}% · max ${high.toFixed(6)}%`)+(sampled?' (displayed intervals only; not full-frequency risk statistics)':'');
      for(const def of catalog.filter(d=>d.group===group.value)){
        const card=doc.createElement('section');card.className='chart';card.dataset.plot=def.id;
        const h=doc.createElement('h2');h.textContent=m.name+' — '+def.title;card.append(h);
        const note=doc.createElement('p');note.className='statistics-note';card.append(note);cards.append(card);
        let data=rows;
        if(m.initial&&(!accept||accept(m.initial.sourceDate))&&['nav','drawdown','underlying','lease-values','book-indexes','reconstruction'].includes(def.id))data=[m.initial,...rows];
        if(def.scatter){
          const points=rows.flatMap(r=>(r.holdings||[]).map(h=>({...h,date:r.start,days:finite(h.maturity_days),annualized_lease_pct:finite(h.lease_pct),forward_premium_pct:finite(h.premium_pct),actual_lease_pct:null})))
            .filter(p=>p.days!==null&&finite(p[def.scatter])!==null);
          if(!points.length||!scatterChart){note.textContent=absent(m,def);card.dataset.available='false';continue;}
          card.dataset.available='true';note.textContent='Held instruments at displayed observations only; not all market quotes. Inspect a point to see its contract, date and maturity.';
          const canvas=doc.createElement('canvas');canvas.id='shared-'+def.id;card.append(canvas);
          scatterChart(canvas,points,def.scatter,def.unit,colors[0]);continue;
        }
        let histogram=null;
        if(def.hist){histogram=rows.map(r=>r[def.hist]);if(m.kind==='daily'&&m.distributions?.length&&(def.hist==='leaseReturn'||(def.hist==='keepReturn'&&m.hasShort))){
          histogram=m.distributions.filter(r=>!accept||accept(r[0])).map(r=>finite(r[def.hist==='leaseReturn'?1:2]));
          note.textContent='All stored execution-interval returns in the selected period (not chart-downsampled).';
        }else note.textContent='Returns '+interval+(sampled?' — sampled intervals only.':'.');}
        const specs=(def.series||[]).filter(([key])=>data.some(r=>finite(r[key])!==null));
        if((histogram&&!histogram.some(v=>finite(v)!==null))||(!histogram&&!specs.length)){
          note.textContent=rows.length?absent(m,def):'No observations in the selected chart period.';card.dataset.available='false';continue;
        }
        card.dataset.available='true';
        const missing=(def.series||[]).filter(([key])=>!specs.some(([k])=>k===key)).map(([,label])=>label);
        if(missing.length)note.textContent+=' Not recorded or inactive: '+missing.join(', ')+'.';
        if(def.id==='legs')note.textContent+=m.kind==='replay'?' Contributions use cumulative leg P&L differences / previous displayed NAV; costs are separate.':' Leg returns use the engine’s own per-leg denominators; these are not additive portfolio contributions.';
        if(def.id==='yield'&&m.kind==='daily')note.textContent+=' Maturity-matched long-side yield (not necessarily the cash yield).';
        const canvas=doc.createElement('canvas');canvas.id='shared-'+def.id;card.append(canvas);
        if(histogram){histogramChart(canvas,histogram,colors[0],m.kind==='replay'?'return between displayed observations (%)':'execution-interval return (%)');continue;}
        const chartRows=data.map(r=>[def.start?r.start:r.date,...specs.map(([key])=>finite(r[key]))]);
        lineChart(canvas,chartRows,specs.map(([,label],i)=>({i:i+1,label,c:colors[i%colors.length]})),def.money?m.money:def.unit,{zero:false});
        if(def.group==='market')annotate?.(canvas,data);
      }
      const details=doc.createElement('details'),title=doc.createElement('summary');title.textContent='Inspect instruments held at a displayed observation';details.append(title);
      const slider=doc.createElement('input');slider.type='range';slider.min=0;slider.max=Math.max(0,rows.length-1);slider.step=1;slider.value=slider.max;slider.setAttribute('aria-label','Displayed observation');
      const text=doc.createElement('pre');text.style.whiteSpace='pre-wrap';
      const inspect=()=>{const row=rows[Number(slider.value)];text.textContent=row?(row.start+' · '+JSON.stringify(row.holdings||[],null,2)):'No observation.';};
      for(const [label,step] of [['Previous observation',-1],['Next observation',1]]){const button=doc.createElement('button');button.type='button';button.textContent=label;button.onclick=()=>{slider.value=Math.max(0,Math.min(rows.length-1,Number(slider.value)+step));inspect();};details.append(button);}
      slider.oninput=inspect;details.append(slider,text);inspect();cards.append(details);
    }
    commodity.onchange=draw;group.onchange=draw;draw();
  }
  global.KeepLeasePlots={finite,replayModel,dailyModel,models,selectRows,catalog,disposeCanvases,render};
})(typeof window==='undefined'?globalThis:window);
