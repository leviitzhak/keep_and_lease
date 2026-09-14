from pathlib import Path
import hashlib
root=Path(__file__).resolve().parents[2]
expected={'shared-run-plots.js': 'cfa8e292379211dcb08e55ed8bdd3fcdbcafabbc94d4e640131a3ae57f765a86', 'silver_strategy_gui.html': 'e6b2fcc0245c6a4edb16d91035202e1078028d6ff07eede146878f21681d6762', 'tests/shared-run-plots.test.mjs': '9d0cbfa29502a1ff742b3bfe0a8093a41553b900b5a58bc5b4c4716c9eaa5523', 'scripts/cloud-agent-browser.cjs': '764a109cc3bd7b7a651829ef8e89f7347215ae8ae17c4adba9fafc66377e9eb0', 'docs/SHARED_RUN_PLOTS.md': '91f2d372cecbf6186f6be2330d3301066187fc59e77c56b04bda19fd07d149a9'}
for name,digest in expected.items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest, name
def edit(name,old,new):
 p=root/name;s=p.read_text();assert s.count(old)==1,(name,old[:70]);p.write_text(s.replace(old,new))
edit('shared-run-plots.js','  function render({result,root,sources,accept,lineChart,histogramChart,scatterChart,annotate}) {', '''  function disposeCanvases(container, releaseCanvas) {
    for (const canvas of container.querySelectorAll('canvas')) {
      releaseCanvas?.(canvas);
      canvas.onmousemove=canvas.onclick=canvas.onmouseleave=null;
      canvas.width=canvas.height=0;
    }
  }
  function render({result,root,sources,accept,lineChart,histogramChart,scatterChart,annotate,releaseCanvas}) {''')
edit('shared-run-plots.js',"const m=all[commodity.value],cards=doc.getElementById('sharedPlotCards');cards.replaceChildren();", "const m=all[commodity.value],cards=doc.getElementById('sharedPlotCards');disposeCanvases(cards,releaseCanvas);cards.replaceChildren();")
edit('shared-run-plots.js','models,selectRows,catalog,render};','models,selectRows,catalog,disposeCanvases,render};')
edit('silver_strategy_gui.html',"  lineChart,histogramChart,scatterChart,annotate:","  releaseCanvas:canvas=>{charts.delete(canvas);if(activeTooltipMeta?.canvas===canvas){activeTooltipMeta=null;closeTooltip();}},\n  lineChart,histogramChart,scatterChart,annotate:")
edit('silver_strategy_gui.html'," bindTooltips();\n}\nupdateTradeControls();", " // Each shared renderer binds its own line/scatter/histogram inspection.\n}\nupdateTradeControls();")
edit('silver_strategy_gui.html', "canvas:not(.statistics-chart canvas)", "canvas:not(.statistics-chart canvas):not(#sharedRunPlots canvas)")
style='''<style id="shared-plot-layout">#sharedRunPlots .chart{height:auto;min-height:0;overflow-y:visible}#sharedRunPlots .chart h2{padding-right:0}#sharedRunPlots .statistics-note{position:sticky;left:0;max-width:100%;white-space:normal}#sharedRunPlots button{position:static;width:auto;margin:6px 8px 6px 0}#sharedRunPlots details>input{display:block;width:100%;margin:10px 0}#sharedRunPlots details pre{overflow-wrap:anywhere}</style>'''
edit('silver_strategy_gui.html','</head><body>',style+'</head><body>')
p=root/'tests/shared-run-plots.test.mjs';s=p.read_text();s+='''

test('replacing a plot family releases renderer references and canvas bitmaps',()=>{
  const canvases=Array.from({length:4},()=>({width:8000,height:250,onmousemove:()=>{},onclick:()=>{},onmouseleave:()=>{}}));
  const registry=new Map(canvases.map(c=>[c,{rows:[[1,2]]}]));
  plots.disposeCanvases({querySelectorAll:()=>canvases},canvas=>registry.delete(canvas));
  assert.equal(registry.size,0);
  for(const canvas of canvases){assert.equal(canvas.width,0);assert.equal(canvas.height,0);assert.equal(canvas.onmousemove,null);}
});
'''.replace('plots.disposeCanvases','api.disposeCanvases')
p.write_text(s)
edit('docs/SHARED_RUN_PLOTS.md', 'Only that family is rendered, avoiding dozens of wide canvases in mobile memory.', 'Only that family is rendered. Switching families releases obsolete chart-registry\nentries and canvas bitmaps; the application layout grows to show captions, legends\nand the complete chart rather than clipping it to the legacy fixed height.')
edit('scripts/cloud-agent-browser.cjs', "      console.log('Shared replay adapter verified: books, market data, inspection and mobile.');", "      for (const family of ['overview','execution','activity','market','curves','rates','books','reconciliation']) {\n        await page.selectOption('#sharedPlotGroup',family);\n        const layout = await page.evaluate(() => ({\n          retained: [...charts.keys()].filter(c=>c.id.startsWith('shared-')&&!c.isConnected).length,\n          clipped: [...document.querySelectorAll('#sharedPlotCards canvas')].some(c=>c.offsetTop+c.offsetHeight>c.parentElement.clientHeight+2)\n        }));\n        if (layout.retained || layout.clipped) throw Error('Shared chart lifecycle/layout failure: '+JSON.stringify(layout));\n      }\n      console.log('Shared replay adapter verified: books, market data, inspection, mobile, all families and bounded canvas lifecycle.');")
