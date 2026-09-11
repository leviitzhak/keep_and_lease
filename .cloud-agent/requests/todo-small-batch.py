"""Apply the reviewed small batch to exact known source bytes, before CI/deploy."""
from pathlib import Path
import hashlib
root=Path(__file__).resolve().parents[2]
expected={
 'silver_strategy_gui.html':'9880e5ea82228257e33e7c1ad945f9175d5669f8e2c2254e7f9ca0c895019444',
 'backtest-runs.js':'151c7af1ce2406d71a6131fc8bf161e51904ee164873349a8ee7ee8859ab9999',
 'server/app.py':'694562916bd7fc02d7a2f834e7a7d818a3b84be69d302406f5ce368362f62d45',
}
for name, digest in expected.items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, 'Unexpected source revision: '+name

def edit(path, old, new):
 p=root/path;s=p.read_text();n=s.count(old)
 assert n==1,(path,n,old[:80])
 p.write_text(s.replace(old,new))
html='silver_strategy_gui.html'
edit(html,'name="trade_initial_capital_usd" type="number" value="1"','name="trade_initial_capital_usd" type="number" value="100000"')
edit(html,"trade_initial_capital_usd:'1',backtest_start:","trade_initial_capital_usd:'100000',backtest_start:")
p=root/html
s=p.read_text();old=s.split('Volume is applied to a normalized initial portfolio of $1,')[1].split('</p>')[0]
edit(html,'Volume is applied to a normalized initial portfolio of $1,'+old,'Trade replay applies participation to the configured Initial capital (USD); candle execution still uses a normalized $1 portfolio. Neither model is a capacity estimate for a large funded account.')
edit('backtest-runs.js',"    const capital=form?.elements?.namedItem?.('trade_initial_capital_usd');\n    if (capital && capital.value === '1' && !capital.dataset.userEdited) capital.value='100000';\n    capital?.addEventListener?.('input',()=>{capital.dataset.userEdited='true';});\n\n",'')
edit(html,'const bins=Math.min(80,Math.max(30,Math.ceil(Math.sqrt(data.length))))','const bins=Math.min(160,Math.max(60,Math.ceil(2*Math.sqrt(data.length))))')
edit('backtest-runs.js','const bins = Math.min(80, Math.max(30, Math.ceil(Math.sqrt(data.length))))','const bins = Math.min(160, Math.max(60, Math.ceil(2*Math.sqrt(data.length))))')
edit('backtest-runs.js',"const data = (values || []).map(Number).filter(Number.isFinite); if (!canvas || !data.length) return;\n      let low = Math.min(...data), high = Math.max(...data); if (low === high) {low -= .5; high += .5;}","const data = (values || []).map(value => value == null || value === '' ? NaN : Number(value)).filter(Number.isFinite);\n      if (!canvas) return;\n      canvas.title = ''; canvas.onmousemove = null;\n      if (!data.length) return;\n      let low = Infinity, high = -Infinity;\n      for (const value of data) {low = Math.min(low, value); high = Math.max(high, value);}\n      if (low === high) {low -= .5; high += .5;}")
edit('server/app.py','"fees_usd", "return_fraction", "reconstruction_error_usd", "units", "targets", "mark_us", "mark_ids"]','"fees_usd", "return_fraction", "reconstruction_error_usd", "units", "targets", "mark_us", "mark_ids",\n                  "target_futures_notional_usd", "free_collateral_usd", "collateralization_ratio", "turnover_usd"]')
edit('server/app.py','                for row in read_chunk(store, entry):\n                    buffer.seek(0)','''                for stored_row in read_chunk(store, entry):
                    # Enrich the export, never mutate immutable audit records. Older
                    # runs cannot reconstruct targets/turnover without extra data.
                    row = dict(stored_row)
                    cash, notional = row.get("cash_usd"), row.get("futures_notional_usd")
                    if cash is not None and notional is not None:
                        gross = abs(notional)
                        if row.get("free_collateral_usd") is None:
                            row["free_collateral_usd"] = cash - gross
                        if row.get("collateralization_ratio") is None and gross > 1e-14:
                            row["collateralization_ratio"] = cash / gross
                    buffer.seek(0)''')
edit(html,'let auditAbort = null;', 'let auditAbort = null, auditDownloadAbort = null;')
p=root/html;s=p.read_text();start=s.index('async function loadAuditDetails(){');end=s.index('async function downloadChunkedSpreadsheet(){',start)
s=s[:start]+'''function auditProgress(id, label){
 let progress=$(id);
 if(!progress){progress=document.createElement('progress');progress.id=id;progress.setAttribute('aria-label',label);$('auditStatus').before(progress)}
 progress.hidden=false;progress.removeAttribute('value');return progress;
}
async function loadAuditDetails(){
 if(auditAbort){auditAbort.abort();return}
 const result=plotRangeSource?.result,audit=result?.audit,period=spreadsheetPeriod();if(!audit||!period)return;
 const work=Object.entries(audit.datasets).filter(([product])=>product!=='portfolio'&&plotRangeSource.sleeves?.[product])
  .map(([product,dataset])=>[product,auditEntries(dataset,period)]);
 const total=work.reduce((sum,[,entries])=>sum+entries.length,0);
 if(!total){$('auditStatus').textContent='No detailed-plot chunks are available for the selected period.';return}
 const controller=auditAbort=new AbortController(),button=$('loadAuditDetails'),progress=auditProgress('detailProgress','Detailed plots: chunks received');
 button.textContent='Cancel detail loading';progress.max=total;progress.value=0;
 $('auditStatus').textContent='Loading detailed plots: 0 / '+total+' chunks received.';
 try{const loaded={};let count=0;
  for(const [product,entries] of work){loaded[product]=[];
   for(const entry of entries){const points=await fetchAuditChunk(audit,product,entry,'rate_change',controller.signal);
    if(controller.signal.aborted||plotRangeSource.result!==result)return;
    for(const point of points)if(point.date>=period.start&&point.date<=period.end)loaded[product].push(point);
    progress.value=++count;$('auditStatus').textContent='Loading detailed plots: '+count+' / '+total+' chunks received.';}
  }
  for(const [product,points] of Object.entries(loaded))plotRangeSource.sleeves[product].rateChangePoints=points;
  applyPlotRange();$('auditStatus').textContent='Detailed plots loaded: '+count+' / '+total+' chunks for '+period.start+' to '+period.end+'.';
 }catch(error){if(plotRangeSource.result===result)$('auditStatus').textContent=error.name==='AbortError'?'Detail loading cancelled.':error.message}
 finally{auditAbort=null;button.textContent='Load detailed plots';progress.hidden=true}
}
async function readAuditDownload(response,onProgress){
 const advertised=Number(response.headers.get('Content-Length'));
 const total=!response.headers.get('Content-Encoding')&&advertised>0?advertised:null;
 onProgress(0,total);
 if(!response.body?.getReader){const blob=await response.blob();onProgress(blob.size,blob.size);return blob}
 const reader=response.body.getReader(),parts=[];let received=0;
 try{for(;;){const {done,value}=await reader.read();if(done)break;parts.push(value);received+=value.byteLength;onProgress(received,total)}}
 finally{reader.releaseLock()}
 return new Blob(parts,{type:response.headers.get('Content-Type')||'application/zip'});
}
async function downloadRawAudit(){
 if(auditDownloadAbort){auditDownloadAbort.abort();return}
 const result=plotRangeSource?.result,audit=result?.audit;if(!audit)return;
 const controller=auditDownloadAbort=new AbortController(),button=$('downloadRawAudit'),progress=auditProgress('auditDownloadProgress','Full audit: downloaded bytes');
 button.textContent='Cancel audit download';$('auditStatus').textContent='Preparing full audit archive…';
 try{const response=await fetch(audit.base_url.replace(/\\/audit$/,'/audit-download'),{credentials:'same-origin',signal:controller.signal});
  if(!response.ok)throw Error('Full audit download failed ('+response.status+').');
  const blob=await readAuditDownload(response,(received,total)=>{
   if(total&&received<=total){progress.max=total;progress.value=received}else progress.removeAttribute('value');
   if(plotRangeSource.result===result)$('auditStatus').textContent='Downloading full audit: '+received.toLocaleString()+(total?' / '+total.toLocaleString():'')+' bytes received.';
  });
  if(controller.signal.aborted)return;
  saveDownload(blob,'keep-and-lease-full-audit.zip');
  if(plotRangeSource.result===result)$('auditStatus').textContent='Full audit downloaded: '+blob.size.toLocaleString()+' bytes.';
 }catch(error){if(plotRangeSource.result===result)$('auditStatus').textContent=error.name==='AbortError'?'Full audit download cancelled.':error.message}
 finally{auditDownloadAbort=null;button.textContent='Download full audit';progress.hidden=true}
}
''' +s[end:];p.write_text(s)

p=root/'docs/TODO.md';s=p.read_text()
for text in ['- [ ] Add progress when loading detailed plots.', '- [ ] Add progress for full-audit generation/download.', '- [ ] Use thinner bins in displayed return-distribution histograms.', '- [ ] Extend streamed `trade-valuations.csv` output with target futures notional,', '- [ ] Make the HTML source default for `trade_initial_capital_usd` $100,000 and']:
 assert s.count(text)==1,text
 s=s.replace(text,text.replace('[ ]','[x]'))
s=s.replace('- [x] Add progress when loading detailed plots.','- [x] Add progress when loading detailed plots (selected chunks received/total,\n  with cancellation and no partial replacement of existing charts).')
s=s.replace('- [x] Add progress for full-audit generation/download.','- [x] Add progress for full-audit generation/download (preparation status,\n  measured received bytes, cancellation; percentage only with a known length).')
s=s.replace('- [x] Use thinner bins in displayed return-distribution histograms.','- [x] Use thinner bins in displayed return-distribution histograms (60–160 bins,\n  shared drawing/hover rules; missing values excluded).')
p.write_text(s)
p=root/'docs/CHANGELOG.md';s=p.read_text();s=s.replace('# Changelog\n','# Changelog\n\n## 2026-09-11 — Bounded TODO usability batch\n\n- Default new replay capital to $100,000 in the HTML and parameter loader;\n  preserve explicitly saved $1 strategies without runtime upgrades. Clarify\n  funded replay versus normalized candle participation.\n- Append target futures notional, free collateral, collateralization ratio and\n  cumulative filled turnover to streamed replay CSVs. Preserve legacy columns,\n  derive collateral only from available cash/notional, and leave unsupported\n  historical targets/turnover blank. Immutable audit rows are unchanged.\n- Show selected-chunk progress for detailed plots and received-byte progress\n  for full audit archives, with cancellation/error recovery. No invented ETA\n  or percentage is shown for unknown-length streams.\n- Use thinner 60–160 return-distribution bins; keep hover and drawing aligned,\n  exclude missing values and avoid large-array argument overflow.\n- Keep engine/accounting changes, full-period acceptance and deferred work\n  outside this limited batch. Deployment evidence is recorded separately.\n',1);p.write_text(s)
p=root/'docs/BTC_SUBSECOND_GUI.md';s=p.read_text().replace('- Initial capital is configurable; volume participation therefore applies to\n  actual funded quantities.', '- Initial capital defaults to $100,000 in the GUI and when an older preset\n  omits it. An explicitly saved $1 value remains $1. Volume participation\n  applies to the configured funded quantities, not a silent runtime upgrade.')
s=s.replace('reconciliation. The existing candle XLSX and book-decomposition charts apply','reconciliation. Four appended columns expose `target_futures_notional_usd`,\n`free_collateral_usd`, `collateralization_ratio` and `turnover_usd`. Older\naudit rows retain blank target/turnover cells when absent. Free collateral\nand the ratio are derived only when both cash and actual notional exist;\nzero futures notional has a blank ratio. This export never rewrites the\nimmutable source audit. The existing candle XLSX and book-decomposition charts apply')
p.write_text(s)
p=root/'docs/CURRENT_WORK.md';s=p.read_text();old='## Active change set\n';assert old in s;s=s.replace(old,old+'''
### September 11 — limited TODO completion

Active branch: `agent/todo-batch-completion`, based on
`agent/current-running-completion` at
`fbf6bc95dcad8b7e7d690f8210896e993590d683`.

This batch implements five bounded items: replay capital defaults/preservation,
CSV collateral fields with historical compatibility, thinner distribution bins,
detailed-plot chunk progress, and cancellable full-audit byte progress.
No trading-engine changes or full-period benchmark reruns are included. Issues
#42–#44 remain open for their broader unimplemented scopes.

Local focused validation: 19 JavaScript tests and 10 Python tests passed.
Combined build and private preview acceptance have not yet been recorded for
this batch. Earlier acceptance entries below refer to earlier revisions.

### Earlier milestones
''',1);p.write_text(s)
verified={
 'silver_strategy_gui.html':'6e0fe2cc678fe85e4a54ac5c6d07a3b86be13836c22c19736dce9e302cae5417',
 'backtest-runs.js':'f49ba43ede052caadd8943a11a0cff0fa22a010c99c1031e912d86b1a88bf368',
 'server/app.py':'8ce73206b1a9153b1d16af7d90d7a5219cb3d6f367f70f5a454f883716b5c08b',
 'docs/TODO.md':'10f3c736fef52a87c4eb546cc0e0e8a69c934746126ac8a0d06266397fff41f3',
 'docs/CHANGELOG.md':'facdd46f52ddf4bfe18d1ad246e7d9108e2d852d6018641fa52ec61060e260da',
 'docs/BTC_SUBSECOND_GUI.md':'201aad4632ce2f8f02ba00495081379b32dbffdb4096c4e818e7aac82219d4f4',
 'docs/CURRENT_WORK.md':'59f5d3fc08fb24e0d777a0efd258356a5512ef823e971b3eba42d0641a3f05f0',
}
for name,digest in verified.items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, 'Patched source differs from reviewed version: '+name
print('Verified all seven patched canonical source/document files; prepare-assets generates public mirrors.')
