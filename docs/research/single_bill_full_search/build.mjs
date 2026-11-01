import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';
process.on('uncaughtException',e=>{console.error(e.message);console.error(e.stack.split('\n').filter(x=>x.includes('build.mjs')).join('\n'));process.exit(1);});

const root=process.env.BILL_DIAG_ROOT;
if(!root)throw new Error('Set BILL_DIAG_ROOT to the directory containing data.json.');
const outputDir=process.env.BILL_DIAG_OUTPUT || path.resolve(root,'../outputs/bill_horizons_20261101');
await fs.mkdir(outputDir,{recursive:true});
const d=JSON.parse(await fs.readFile(path.join(root,'data.json'),'utf8'));
const wb=Workbook.create();
const names=['Trajectory 0-T','Trades','Search t0','Search t1','Search t2','Search t3','All pairs','Training','Network'];
const S=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const C={ink:'#172B4D',header:'#314D74',blue:'#21618C',gray:'#65758B',pale:'#EDF2F7',kept:'#E3F0E9',orange:'#9A6200'};
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s;}
function val(s,a,v){s.getRange(a).values=[[v]];}
function formula(s,a,v){s.getRange(a).formulas=[[v]];}
function row(s,r,values){s.getRange(`A${r}:${col(values.length-1)}${r}`).values=[values];}
function setup(s,lastRow,lastCol=12){
  s.showGridLines=false;
  s.getRange(`A1:${col(lastCol-1)}${lastRow}`).format={font:{name:'Arial',size:10,color:C.ink},verticalAlignment:'center',rowHeight:22,columnWidth:14};
  s.getRange(`A1:${col(lastCol-1)}1`).format.rowHeight=10;
}
function title(s,text,end='L'){val(s,'A2',text);s.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:C.ink};s.getRange(`A2:${end}2`).format.rowHeight=28;}
function note(s,r,text){val(s,`A${r}`,text);s.getRange(`A${r}`).format.font={name:'Arial',size:10,italic:true,color:C.gray};}
function header(s,r,labels){row(s,r,labels);s.getRange(`A${r}:${col(labels.length-1)}${r}`).format={fill:C.header,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'center',rowHeight:45};}
function section(s,r,text,last='L'){val(s,`A${r}`,text);s.getRange(`A${r}:${last}${r}`).format={fill:C.pale,font:{name:'Arial',size:11,bold:true,color:C.ink},rowHeight:26};}
function number(s,rng,fmt='0.000'){s.getRange(rng).setNumberFormat(fmt);s.getRange(rng).format.horizontalAlignment='right';}
const usd='#,##0.000;[Red](#,##0.000);0.000';const pct='0.0000%;[Red](0.0000%);0.0000%';
function uFormula(L){return `MAX(${L}/'Trades'!$B$5-1,0)*'Trades'!$B$14-MAX(1-${L}/'Trades'!$B$5,0)*'Trades'!$B$15`;}
function immediate(cash,q,t){return `${cash}+${q}*('Trades'!$B$6+'Trades'!$B$7*(${t}+'Trades'!$B$23)+'Trades'!$B$8)+'Trades'!$B$7*${q}*(${q}-1)/2`;}
const key=(t,cash,q,end)=>[t,cash,q,end].join('|');
const labelRows=new Map(d.labels.map((r,i)=>[key(r.t,r.cash,r.q,r.end),26+i]));
const netRows=new Map(d.labels.map((r,i)=>[key(r.t,r.cash,r.q,r.end),33+i]));

// Synthetic trade data and the recorded run settings.
const tr=S.Trades;setup(tr,53,12);title(tr,'Generated BILL trades');
note(tr,3,'Synthetic experiment. The same two one-unit prints repeat around a linearly rising midprice.');
const settings=[['Initial USD',1000],['Initial midprice',95],['Price rise / step',.5],['Print / limit offset',.25],['Bill redemption USD',100],['Terminal T',4],['Search depth',5],['Inventory cap',4],['Fees',0],['Positive growth weight',1],['Loss aversion',10],['Maturity time',10],['Network output scale',.01],['Cash feature scale',400],['Quantity feature scale',4],['Time / horizon scale',4],['Network seed',20261101],['Sell-print offset',.25],['Buy-print offset',.75]];
settings.forEach((x,i)=>{tr.getRange(`A${5+i}:B${5+i}`).values=[x];});
tr.getRange('A5:A23').format.columnWidth=27;tr.getRange('B5:B23').format.font.color=C.blue;number(tr,'B5:B23','0.####');
const rules=[
 'Four decisions: t=0,1,2,3. Terminal state: T=4.',
 'Actions: wait, buy 1 bill, sell 1 owned bill. No borrowing or shorting.',
 'Order limit: mid(t)+0.25 for buys; mid(t)-0.25 for sells.',
 'A strictly through-limit opposite-side print triggers a fill at the limit.',
 'Each action fills within its interval. No orders or messages persist.',
 'Closing begins strictly after the requested endpoint, using buy prints.',
 'Closing sells one bill per eligible print at that printed price.',
 'Closing time is ignored. No strategy actions run after the endpoint.',
 'Long-term USD = cash + 100 × owned bills. No redemption is double-counted.',
 'Utility = positive USD growth − 10 × negative USD growth.',
 'Only USD is a commodity in this reduced example; BTC is absent.',
 'The deterministic price law is known to the planner. There is one scenario.',
 'Recorded search paths and training are fixed; rerun simulate.py to change the run.',
 'Cell formulas expose arithmetic. Editing inputs alone does not rerun the tree.',
 'This is a new four-input diagnostic, not the earlier 44-input checkpoint.'
];rules.forEach((x,i)=>{val(tr,`D${5+i}`,x);});
tr.getRange('D5:D19').format.font.color=C.gray;
header(tr,25,['Trade ID','Interval','Event time','Aggressor side','Midprice USD','Trade price USD','Bill size','Region']);
const tradeRows=new Map();
d.trades.forEach((x,i)=>{const r=26+i;tradeRows.set(x.id,r);row(tr,r,[x.id,x.interval,x.time,x.side,null,null,x.size,x.region]);formula(tr,`E${r}`,`=$B$6+$B$7*C${r}`);formula(tr,`F${r}`,`=E${r}+IF(D${r}="buy",$B$8,-$B$8)`);});
number(tr,'C26:C43','0.00');number(tr,'E26:F43',usd);tr.getRange('H25:H43').format.columnWidth=18;tr.freezePanes.freezeRows(2);
note(tr,46,'Provenance: user-requested synthetic tape; generated deterministically by simulate.py, seed 20261101.');
note(tr,47,'Closing convention follows the earlier subsequent-print audit, simplified to one bill and zero delays/fees.');
note(tr,48,'Reference branch: https://github.com/leviitzhak/keep_and_lease/tree/agent/btc-post-decision-value-v1');

// Network weights and fully formula-based forward passes for every training row.
const net=S.Network;setup(net,96,39);title(net,'Initial and trained network');
note(net,3,'4 inputs → 16 tanh units → 1 scalar. 97 trainable parameters; NumPy Adam, seed 20261101.');
note(net,4,'v predicts terminal liquidation USD directly. Utility is calculated from that USD value when ranking paths.');
val(net,'A6','Initial output bias');val(net,'B6',d.initial_network.c[0]);val(net,'I6','Trained output bias');val(net,'J6',d.final_network.c[0]);
header(net,9,['Unit','Cash weight','Qty weight','Time weight','Horizon weight','Hidden bias','Output weight',null,'Unit','Cash weight','Qty weight','Time weight','Horizon weight','Hidden bias','Output weight']);
for(let j=0;j<16;j++){
  row(net,10+j,[j+1,...d.initial_network.W.map(a=>a[j]),d.initial_network.b[j],d.initial_network.w[j],null,j+1,...d.final_network.W.map(a=>a[j]),d.final_network.b[j],d.final_network.w[j]]);
}
number(net,'B10:G25','0.000000');number(net,'J10:O25','0.000000');net.getRange('H1:H96').format.columnWidth=3;
note(net,28,'Features: (cash−1000)/400, bill quantity/4, current time/4, remaining horizon/4. Price is determined by time.');
note(net,29,'Each hidden unit = TANH(input dot weights + bias); v = 1000 × [1 + 0.01 × (hidden dot output weights + output bias)].');
header(net,32,['Label','Cash input','Qty input','Time input','Horizon input',...Array.from({length:16},(_,i)=>`Initial h${i+1}`),'Initial v',...Array.from({length:16},(_,i)=>`Trained h${i+1}`),'Trained v']);
d.labels.forEach((x,i)=>{
  const r=33+i,rr=26+i;val(net,`A${r}`,x.id);
  const ff=[`=('Training'!E${rr}-'Trades'!$B$5)/'Trades'!$B$18`,`='Training'!F${rr}/'Trades'!$B$19`,`='Training'!B${rr}/'Trades'!$B$20`,`='Training'!D${rr}/'Trades'!$B$20`];
  net.getRange(`B${r}:E${r}`).formulas=[ff];
  for(let j=0;j<16;j++){
    const wr=10+j;formula(net,`${col(5+j)}${r}`,`=TANH(SUMPRODUCT($B${r}:$E${r},$B$${wr}:$E$${wr})+$F$${wr})`);
    formula(net,`${col(22+j)}${r}`,`=TANH(SUMPRODUCT($B${r}:$E${r},$J$${wr}:$M$${wr})+$N$${wr})`);
  }
  formula(net,`V${r}`,`='Trades'!$B$5*(1+'Trades'!$B$17*(${Array.from({length:16},(_,j)=>`${col(5+j)}${r}*$G$${10+j}`).join('+')}+$B$6))`);
  formula(net,`AM${r}`,`='Trades'!$B$5*(1+'Trades'!$B$17*(${Array.from({length:16},(_,j)=>`${col(22+j)}${r}*$O$${10+j}`).join('+')}+$J$6))`);
});
number(net,'B33:AM93','0.000000');number(net,'V33:V93',usd);number(net,'AM33:AM93',usd);net.freezePanes.freezeRows(2);net.freezePanes.freezeColumns(1);

// Training corpus: unique reachable states, every valid horizon, equal total weight per horizon.
const train=S.Training;setup(train,104,19);title(train,'Full-search training across horizons');
note(train,3,'61 distinct state–horizon labels from 34 reachable states. Every target comes from full-depth enumeration.');
note(train,4,'All rows are fitted in this diagnostic. Losses are in-sample; no held-out generalization claim is made.');
header(train,6,['Adam update','USD MSE','Balanced USD MSE','USD RMSE','Max utility error']);
d.training_curve.forEach((x,i)=>row(train,7+i,[x.update,x.mse,x.balanced_mse,x.rmse_usd,x.max_abs_utility]));
number(train,'B7:C19','0.00E+00');number(train,'D7:D19',usd);number(train,'E7:E19',pct);
const chart=train.charts.add('line',[train.getRange('A6:A19'),train.getRange('B6:B19'),train.getRange('C6:C19')]);
chart.title='USD squared error during training';chart.setPosition('G6','N20');chart.titleTextStyle.typeface='Arial';chart.titleTextStyle.fontSize=12;
chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:10}};
chart.yAxis={numberFormatCode:'0.0E+00',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:10}};
chart.legend={position:'top',textStyle:{typeface:'Arial',fontSize:10}};
chart.series.items.forEach((s,i)=>{s.line={fill:i?'#C48229':'#314D74',width:2,style:'solid'};});
note(train,22,'Weight per row = 1 / (5 × rows at that horizon). Adam optimizes balanced USD MSE / 10².');
note(train,23,'h=0 uses immediate subsequent-print liquidation. Explored paths use a fresh best-continuation target at their states.');
header(train,25,['Label','Time t','Endpoint t2','Horizon h','Cash USD','Bills','Midprice USD','Target liquidation USD','Target utility','Initial v USD','Trained v USD','Initial sq. error','Trained sq. error','Sample weight','Weighted error','Best continuation','Paths searched','Initial utility','Trained utility']);
d.labels.forEach((x,i)=>{
  const r=26+i,n=33+i;row(train,r,[x.id,x.t,x.end,x.h,x.cash,x.q,null,x.target_liquidation,null,null,null,null,null,x.sample_weight,null,x.best_path||'boundary',x.paths_searched,null,null]);
  formula(train,`G${r}`,`='Trades'!$B$6+'Trades'!$B$7*B${r}`);formula(train,`I${r}`,`=${uFormula(`H${r}`)}`);
  formula(train,`J${r}`,`='Network'!V${n}`);formula(train,`K${r}`,`='Network'!AM${n}`);
  formula(train,`L${r}`,`=(J${r}-H${r})^2`);formula(train,`M${r}`,`=(K${r}-H${r})^2`);formula(train,`O${r}`,`=N${r}*M${r}`);
  for(const [dst,src] of [['R','J'],['S','K']])formula(train,`${dst}${r}`,`=${uFormula(`${src}${r}`)}`);
});
number(train,'E26:H86',usd);number(train,'I26:I86',pct);number(train,'J26:K86',usd);number(train,'L26:O86','0.000E+00');number(train,'R26:S86',pct);train.getRange('P25:P86').format.columnWidth=34;
section(train,89,'Recalculated final losses','H');row(train,90,['Initial MSE',null,'Final MSE',null,'Balanced final MSE',null]);
formula(train,'B90','=AVERAGE(L26:L86)');formula(train,'D90','=AVERAGE(M26:M86)');formula(train,'F90','=SUM(O26:O86)');number(train,'B90:F90','0.000E+00');
note(train,93,'Search labels were independently checked by a backward Bellman calculation; 34 closing values match a separate formula.');
note(train,94,'The four-parameter-group analytic gradient agrees with finite differences to 5.1e-11 in this run.');
train.freezePanes.freezeRows(2);train.freezePanes.freezeColumns(1);

// Search tabs: every full-depth candidate, each strategic step, and each closing print.
const searchIndex=[];
d.searches.forEach(search=>{
  const s=S[`Search t${search.t}`],n=search.candidates.length,summaryStart=11,summaryEnd=10+n;
  let detailHeader=summaryEnd+4;let detailStart=detailHeader+1;
  let closeHeader=detailStart+search.candidates.reduce((a,p)=>a+p.steps.length,0)+3;
  let closeStart=closeHeader+1;
  const closeCount=search.candidates.reduce((a,p)=>a+p.trace.length,0);
  setup(s,closeStart+closeCount+3,23);title(s,`Full-depth search from t=${search.t} to T=4`,'M');
  note(s,3,'Greedy = initial-network argmax of the next state; exploration = another enumerated action. No random epsilon sampling.');
  note(s,4,'Every legal continuation is evaluated. The kept path maximizes terminal utility; only its first action is executed.');
  row(s,6,['Start cash USD','Start bills','Candidates','End time','Depth limit',null,'Kept candidate',null,'First action',null,'Target USD']);
  row(s,7,[null,null,n,4,5]);
  formula(s,'A7',`='Trajectory 0-T'!C${8+search.t}`);formula(s,'B7',`='Trajectory 0-T'!D${8+search.t}`);
  val(s,'G7',search.kept);val(s,'I7',search.candidates.find(p=>p.kept).steps[0].action);
  formula(s,'K7',`=I${11+search.candidates.findIndex(p=>p.kept)}`);
  number(s,'A7',usd);number(s,'K7',usd);
  note(s,8,'Tie-break: first maximum in wait / buy / sell depth-first order. Branch tags remain the recorded initial-network tags.');
  header(s,10,['Candidate ID','Selection','Actions to T','Step types','Terminal cash USD','Terminal bills','Long-term USD','Closing proceeds USD','Liquidation USD','Terminal utility','Close time']);
  s.getRange(`C10:C${summaryEnd}`).format.columnWidth=33;s.getRange(`D10:D${summaryEnd}`).format.columnWidth=33;
  header(s,detailHeader,['Candidate ID','Step','Time','Action','Step type','Network greedy action','Cash before USD','Bills before','Signed fill','Limit USD','Trade ID','Print USD','Fill USD','Cash after USD','Bills after','Long-term USD','Next-state v0 USD','Terminal liquidation USD','Terminal utility','Selection','Wait score USD','Buy score USD','Sell score USD']);
  s.getRange(`A${detailHeader}:T${detailHeader}`).format.rowHeight=58;
  header(s,closeHeader,['Candidate ID','Closing print','Time','Bills sold','Price USD','Proceeds USD','Cash after USD']);
  let dr=detailStart,cr=closeStart;
  const indexes=[];
  search.candidates.forEach((p,i)=>{
    const r=summaryStart+i,first=dr,term=dr+p.steps.length-1;
    row(s,r,[p.id,null,p.path,p.steps.map(x=>x.step_type==='greedy'?'G':'E').join(' / '),null,null,null,null,null,null,p.close_time]);
    formula(s,`B${r}`,`=IF(ROW()=MATCH(MAX($J$${summaryStart}:$J$${summaryEnd}),$J$${summaryStart}:$J$${summaryEnd},0)+${summaryStart-1},"KEPT","")`);
    formula(s,`E${r}`,`=N${term}`);formula(s,`F${r}`,`=O${term}`);formula(s,`G${r}`,`=E${r}+F${r}*'Trades'!$B$9`);
    formula(s,`H${r}`,closeCount?`=SUMIFS($F$${closeStart}:$F$${closeStart+closeCount-1},$A$${closeStart}:$A$${closeStart+closeCount-1},A${r})`:'=0');
    formula(s,`I${r}`,`=E${r}+H${r}`);formula(s,`J${r}`,`=${uFormula(`I${r}`)}`);
    p.steps.forEach((x,j)=>{
      const z=dr++,nr=netRows.get(key(x.after.t,x.after.cash,x.after.q,4));
      row(s,z,[p.id,j+1,x.before.t,x.action,x.step_type,x.greedy_action,null,null,x.signed_quantity,null,x.trade_id,null,null,null,null,null,null,null,null,null]);
      formula(s,`G${z}`,j?`=N${z-1}`:'=$A$7');formula(s,`H${z}`,j?`=O${z-1}`:'=$B$7');
      for(const [c,a] of [['U','wait'],['V','buy'],['W','sell']])val(s,`${c}${z}`,x.candidate_scores[a]??'inadmissible');
      if(x.signed_quantity){
        formula(s,`J${z}`,`='Trades'!$B$6+'Trades'!$B$7*C${z}+I${z}*'Trades'!$B$8`);
        formula(s,`L${z}`,`='Trades'!F${tradeRows.get(x.trade_id)}`);formula(s,`M${z}`,`=J${z}`);
      }else{val(s,`J${z}`,0);val(s,`L${z}`,0);val(s,`M${z}`,0);}
      formula(s,`N${z}`,`=G${z}-I${z}*M${z}`);formula(s,`O${z}`,`=H${z}+I${z}`);formula(s,`P${z}`,`=N${z}+O${z}*'Trades'!$B$9`);
      formula(s,`Q${z}`,`='Network'!V${nr}`);formula(s,`R${z}`,`=I${r}`);formula(s,`S${z}`,`=J${r}`);formula(s,`T${z}`,`=B${r}`);
    });
    let before=null;
    p.trace.forEach(x=>{
      const z=cr++;row(s,z,[p.id,x.trade_id,x.time,x.quantity,null,null,null]);
      formula(s,`E${z}`,`='Trades'!F${tradeRows.get(x.trade_id)}`);formula(s,`F${z}`,`=D${z}*E${z}`);formula(s,`G${z}`,`=${before?`G${before}`:`E${r}`}+F${z}`);before=z;
    });
    indexes.push({summary:r,first,terminal:term,id:p.id,kept:p.kept});
  });
  number(s,`E11:I${summaryEnd}`,usd);number(s,`J11:J${summaryEnd}`,pct);number(s,`K11:K${summaryEnd}`,'0.00');
  number(s,`G${detailStart}:P${closeHeader-4}`,usd);number(s,`Q${detailStart}:Q${closeHeader-4}`,usd);number(s,`R${detailStart}:R${closeHeader-4}`,usd);number(s,`S${detailStart}:S${closeHeader-4}`,pct);
  number(s,`U${detailStart}:W${closeHeader-4}`,usd);number(s,`F11:F${summaryEnd}`,'0');number(s,`H${detailStart}:I${closeHeader-4}`,'0');number(s,`O${detailStart}:O${closeHeader-4}`,'0');
  number(s,`E${closeStart}:G${closeStart+Math.max(closeCount,1)-1}`,usd);
  s.getRange(`A11:K${summaryEnd}`).conditionalFormats.addCustom('$B11="KEPT"',{fill:C.kept,font:{bold:true}});
  s.getRange(`E${detailStart}:E${closeHeader-4}`).conditionalFormats.add('containsText',{text:'exploration',format:{font:{color:C.orange}}});
  s.getRange(`A${detailStart}:A${closeHeader-4}`).format.columnWidth=17;s.getRange('F1:F6').format.columnWidth=17;s.getRange(`F${detailHeader}:F${closeHeader-4}`).format.columnWidth=19;
  s.freezePanes.freezeRows(10);s.freezePanes.freezeColumns(2);
  searchIndex.push({name:s.name,summaryStart,summaryEnd,detailHeader,closeHeader,indexes,kept:indexes.find(x=>x.kept)});
});

// First realized trajectory. Its state rolls forward from the selected search actions.
const main=S['Trajectory 0-T'];setup(main,43,20);title(main,'First trajectory with the initial network','N');main.tabColor=C.header;
note(main,3,'Four decision steps, then T=4. Full-depth search selects actions using exact terminal liquidation.');
note(main,4,'The initial network stays frozen during this audit. One chosen continuation supplies the common target for its earlier states.');
header(main,7,['Midprice USD','Time t','Cash USD','Owned bills','Pending requests','Live orders','Horizon T−t','Initial v(t,T) USD','Target utility','Target liquidation USD','Long-term USD','Liquidate now USD','Final liquidation USD','Final utility','Chosen action','Kept path','Trained v(t,T) USD','Initial sq. error','Trained sq. error','Liquidate now utility']);
main.getRange('A7:T7').format.rowHeight=65;
d.trajectory.forEach((x,i)=>{
  const r=8+i,lr=labelRows.get(key(x.t,x.cash,x.q,4));
  row(main,r,[null,x.t,null,null,0,0,null,null,null,null,null,null,null,null,x.action,x.kept,null,null,null,null]);
  formula(main,`A${r}`,`='Trades'!$B$6+'Trades'!$B$7*B${r}`);
  formula(main,`C${r}`,i?`='Search t${i-1}'!N${searchIndex[i-1].kept.first}`:"='Trades'!$B$5");
  formula(main,`D${r}`,i?`='Search t${i-1}'!O${searchIndex[i-1].kept.first}`:'=0');
  formula(main,`G${r}`,`='Trades'!$B$10-B${r}`);formula(main,`H${r}`,`='Training'!J${lr}`);formula(main,`Q${r}`,`='Training'!K${lr}`);
  formula(main,`I${r}`,i<4?`='Search t${i}'!J${searchIndex[i].kept.summary}`:`=N${r}`);
  formula(main,`J${r}`,i<4?`='Search t${i}'!I${searchIndex[i].kept.summary}`:`=M${r}`);
  formula(main,`K${r}`,`=C${r}+D${r}*'Trades'!$B$9`);formula(main,`L${r}`,`=${immediate(`C${r}`,`D${r}`,`B${r}`)}`);
  formula(main,`M${r}`,'=$L$12');formula(main,`N${r}`,`=${uFormula(`M${r}`)}`);
  formula(main,`R${r}`,`=(H${r}-J${r})^2`);formula(main,`S${r}`,`=(Q${r}-J${r})^2`);formula(main,`T${r}`,`=${uFormula(`L${r}`)}`);
});
number(main,'A8:A12',usd);number(main,'C8:C12',usd);number(main,'H8:H12',usd);number(main,'I8:I12',pct);number(main,'J8:M12',usd);number(main,'N8:N12',pct);number(main,'Q8:Q12',usd);number(main,'R8:S12','0.000E+00');number(main,'T8:T12',pct);
main.getRange('O7:P12').format.columnWidth=17;main.getRange('A12:T12').format.fill=C.kept;
section(main,15,'Terminal liquidation through subsequent trades','J');
header(main,16,['Closing print','Event time','Bills sold','Price USD','Proceeds USD','Cash after USD','Bills remaining']);
d.trajectory[4].current_close.trace.forEach((x,i)=>{
  const r=17+i;row(main,r,[x.trade_id,x.time,x.quantity,null,null,null,null]);formula(main,`D${r}`,`='Trades'!F${tradeRows.get(x.trade_id)}`);formula(main,`E${r}`,`=C${r}*D${r}`);
  formula(main,`F${r}`,`=${i?`F${r-1}`:'$C$12'}+E${r}`);formula(main,`G${r}`,`=${i?`G${r-1}`:'$D$12'}-C${r}`);
});number(main,'B17:B20','0.00');number(main,'D17:F20',usd);
section(main,23,'How to read the targets','K');
const explanations=[
 'The bill is a claim on USD. Its face value contributes to long-term USD holdings; its sale price determines liquidation USD.',
 'v(t,T) predicts terminal liquidation USD directly. The separate utility applies the declared growth/loss objective.',
 'For the retained optimal 0→4 path, each earlier state has target 1009.50 USD, or 0.95% utility.',
 'Liquidate-now values are separate zero-horizon labels. They do not replace targets for a longer requested horizon.',
 'Search cutoff at state time t is min(t2, t+depth_search). Here depth_search=5, so every search reaches its endpoint.',
 'A finite rollout target equals that rollout’s terminal outcome. For an optimal value function, exploratory states are re-searched.',
 'An exploratory path’s poorer terminal outcome is recorded on its search sheet, not used as an optimal label for every shared state.',
 'G and E mean greedy or exploration relative to the initial network. Search selection itself is greedy in exact terminal utility.',
 'With one deterministic market law there is no scenario minimum. These results are exact only for this finite action menu.',
 'Training covers all horizons 0..4 where valid. It fits this example; this alone does not establish out-of-sample generalization.',
 'All pairs includes the ten (t1,t2) trajectories, anchored at the state reached at t1 on this first trajectory.',
 'Training also includes off-path reachable states. A repeated (state,horizon) is fitted once, so long paths do not overcount it.'
];explanations.forEach((x,i)=>note(main,25+i,x));main.freezePanes.freezeRows(7);main.freezePanes.freezeColumns(2);

// Every pair's selected trajectory, with a common endpoint outcome on all rows.
const pairs=S['All pairs'];setup(pairs,39,18);title(pairs,'All ten start–end pairs');
note(pairs,3,'Each start uses the state on the first 0→4 trajectory. Every pair has its own exhaustive search to its endpoint.');
note(pairs,4,'The same terminal liquidation target is attached to every state along the retained continuation, including its h=0 boundary.');
header(pairs,7,['Pair','Start t1','End t2','State time','Horizon','Cash USD','Bills','Midprice USD','Next action','Step type','Initial v','Trained v','Target liquidation USD','Target utility','Long-term USD','Liquidate now USD','Initial sq. error','Trained sq. error']);
let pr=8;
d.pairs.forEach(p=>{
  const first=pr,last=pr+p.states.length-1;
  p.states.forEach((x,i)=>{
    const r=pr++,lr=labelRows.get(key(x.t,x.cash,x.q,p.t2));row(pairs,r,[p.id,p.t1,p.t2,x.t,x.h,x.cash,x.q,null,p.steps[i]?.action||'terminal',p.steps[i]?.step_type||'boundary',null,null,null,null,null,null,null,null]);
    formula(pairs,`H${r}`,`='Trades'!$B$6+'Trades'!$B$7*D${r}`);formula(pairs,`K${r}`,`='Training'!J${lr}`);formula(pairs,`L${r}`,`='Training'!K${lr}`);
    formula(pairs,`M${r}`,`=$P$${last}`);formula(pairs,`N${r}`,`=${uFormula(`M${r}`)}`);formula(pairs,`O${r}`,`=F${r}+G${r}*'Trades'!$B$9`);
    formula(pairs,`P${r}`,`=${immediate(`F${r}`,`G${r}`,`D${r}`)}`);formula(pairs,`Q${r}`,`=(K${r}-M${r})^2`);formula(pairs,`R${r}`,`=(L${r}-M${r})^2`);
  });pairs.getRange(`A${first}:R${first}`).format.borders={top:{style:'thin',color:'#B5C2D4'}};
});
number(pairs,`F8:H${pr-1}`,usd);number(pairs,`K8:L${pr-1}`,usd);number(pairs,`M8:M${pr-1}`,usd);number(pairs,`N8:N${pr-1}`,pct);number(pairs,`O8:P${pr-1}`,usd);number(pairs,`Q8:R${pr-1}`,'0.000E+00');pairs.getRange(`J7:J${pr-1}`).format.columnWidth=17;pairs.freezePanes.freezeRows(7);pairs.freezePanes.freezeColumns(1);
number(pairs,`G8:G${pr-1}`,'0');number(train,'F26:F86','0');

// Calculation, numerical comparison, then visual inspection artifacts.
wb.recalculate();
const checks=[];
function near(sheet,address,expected,tol=1e-9){const v=S[sheet].getRange(address).values[0][0];if(typeof v!=='number'||Math.abs(v-expected)>tol)throw new Error(`${sheet}!${address}: ${v} != ${expected}`);checks.push({sheet,address,value:v,expected});}
d.labels.forEach((r,i)=>{near('Network',`V${33+i}`,r.initial_prediction);near('Network',`AM${33+i}`,r.final_prediction);});
d.searches.forEach((s,i)=>s.candidates.forEach((p,j)=>{near(`Search t${i}`,`I${11+j}`,p.liquidation);near(`Search t${i}`,`J${11+j}`,p.utility);}));
d.trajectory.forEach((r,i)=>{near('Trajectory 0-T',`C${8+i}`,r.cash);near('Trajectory 0-T',`D${8+i}`,r.q);near('Trajectory 0-T',`K${8+i}`,r.economic_usd);near('Trajectory 0-T',`L${8+i}`,r.current_close.liquidation);});
near('Trajectory 0-T','F20',1009.5);near('Trajectory 0-T','M12',1009.5);near('Training','D90',d.checks.final_loss.mse);near('Training','F90',d.checks.final_loss.balanced_mse);
// A reversible weight perturbation verifies the formula chain, then restores it.
const oldBias=net.getRange('B6').values[0][0],oldV=net.getRange('V33').values[0][0];
val(net,'B6',oldBias+.1);wb.recalculate();near('Network','V33',oldV+1);
val(net,'B6',oldBias);wb.recalculate();near('Network','V33',oldV);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Formula error scan',maxChars:3000})).ndjson);
console.log((await wb.inspect({kind:'table',range:'Trajectory 0-T!H7:N12',include:'values,formulas',tableMaxRows:6,tableMaxCols:7,maxChars:2500})).ndjson);
const renderSpecs=[['Trajectory 0-T','A1:J13','trajectory_left'],['Trajectory 0-T','K7:T13','trajectory_right'],['Trajectory 0-T','A15:J21','closing'],['Trades','A25:H43','trades'],['All pairs','A1:J17','pairs'],['Training','A1:N20','training'],['Network','A1:G25','network']];
for(const i of searchIndex){renderSpecs.push([i.name,'A1:K16',`search${i.name.at(-1)}`]);renderSpecs.push([i.name,`A${i.detailHeader}:J${i.detailHeader+6}`,`steps${i.name.at(-1)}`]);}
for(const [sheetName,range,file] of renderSpecs){const img=await wb.render({sheetName,range,scale:1.3,format:'png'});await fs.writeFile(path.join(outputDir,`${file}.png`),new Uint8Array(await img.arrayBuffer()));}
await fs.writeFile(path.join(root,'workbook_validation.json'),JSON.stringify({numerical_checks:checks.length,all_passed:true,checks,searchIndex},null,2));
const output=await SpreadsheetFile.exportXlsx(wb);await output.save(path.join(outputDir,'Single_Bill_Full_Search_Horizons.xlsx'));
console.log(JSON.stringify({outputDir,numericalChecks:checks.length,sheets:names.length}));
