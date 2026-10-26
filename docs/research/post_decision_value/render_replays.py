"""Render verified event journals as an offline step-through and scientific plot."""
import base64
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter

ROOT=Path(__file__).parent
bundle=json.loads((ROOT/'replays-v1.json').read_text())
fig,axes=plt.subplots(3,1,figsize=(11,9),layout='constrained')
colors={'BTC-25DEC26':'#2267A5','BTC-26MAR27':'#AD5700'}
for ax,example in zip(axes,bundle['examples']):
    live={};segments=[]
    def close(oid,t):
        if oid in live:
            o,start=live.pop(oid);segments.append((start,t,o))
    for row in example['trace']:
        t=(row['time']-example['start'])/3600000
        if row['event']=='exchange_message':
            action=row['data'][1]
            for oid in action['targets']:close(oid,t)
            for o in action['orders']:live[o['identifier']]=(o,t)
        elif row['event']=='exchange_fill':
            f=row['data']
            ax.scatter(t,f['price'],s=46,color=colors[f['symbol']],marker='o',zorder=4)
            if f['remaining']<1e-9:close(f['order'],t)
    for oid in list(live):close(oid,4)
    for start,end,o in segments:
        ax.plot([start,end],[o['limit']]*2,color=colors[o['symbol']],linewidth=2)
        ax.scatter(start,o['limit'],marker='^' if o['quantity']>0 else 'v',color=colors[o['symbol']],s=45)
    label=example['name'].replace('-s11-d1','')
    date='2026-06-06' if label.startswith('calibration') else '2026-08-17'
    ax.set_title(f'{label} | {date} UTC | {len(example["fills"])} fill fragments',loc='left',fontsize=12)
    if not segments:
        ax.text(.5,.5,'Wait at all four decisions; no orders or fills',ha='center',va='center',transform=ax.transAxes)
        ax.set_yticks([])
    ax.set_xlim(-.05,4.05);ax.set_xlabel('Hours since 00:00 UTC');ax.set_ylabel('Posted limit (USD/BTC)')
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'));ax.grid(alpha=.15)
fig.suptitle('Replayed order lifetimes and fills\nLines: live limits • triangles: order arrival/amendment • circles: fills',fontsize=13)
from matplotlib.lines import Line2D
fig.legend([Line2D([0],[0],color=c,lw=2) for c in colors.values()],list(colors),loc='outside lower center',ncol=2)
fig.savefig(ROOT/'replays-v1.png',dpi=150)

payload=json.dumps(bundle,separators=(',',':')).replace('<','\\u003c')
html='''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Historical order replays</title><style>
:root{color-scheme:light dark;font-family:system-ui,sans-serif}body{max-width:1100px;margin:30px auto;padding:0 20px;line-height:1.5}h1{font-size:1.5rem}select,button,input{font:inherit;padding:8px}label,button{margin-right:12px}input[type=range]{width:min(600px,85%)}table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{padding:9px 5px;text-align:left;border-bottom:1px solid #8886;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}.active{background:#8883}details{margin:18px 0}#status{font-variant-numeric:tabular-nums}img{width:100%}button{cursor:pointer}tr:focus{outline:2px solid currentColor}
</style></head><body><h1>Historical order replays</h1>
<p>Three verified four-hour excerpts. Hypothetical linear orders on native inverse trade data. Holdings remain contractual; these excerpts do not establish terminal returns or realized settlement.</p>
<label for="example">Trajectory</label><select id="example"></select>
<p id="status" aria-live="polite"></p><p><button id="previous">Previous event</button><button id="next">Next event</button></p>
<label for="step">Event</label><input id="step" type="range" min="0" value="0">
<details open><summary id="selected">Selected event</summary><pre id="detail"></pre></details>
<table><thead><tr><th>UTC time</th><th>Event</th><th>Order or decision</th></tr></thead><tbody id="events"></tbody></table>
<p>Exchange fills and received fill reports are separate events. Posted limits are based on the last received trade, not observed bid/ask quotes. Fills require an opposing strict-through print; participation is capped at 10% of converted native print volume, shared across orders.</p>
<img src="replays-v1.png" alt="Order lifetimes and fills in three four-hour historical excerpts">
<script>
const bundle=PAYLOAD;
const select=document.getElementById('example'),slider=document.getElementById('step'),body=document.getElementById('events');
const when=t=>new Date(t).toISOString().slice(11,23);
const order=o=>`${o.quantity>0?'Buy':'Sell'} ${Math.abs(o.quantity).toFixed(4)} ${o.symbol} @ ${o.limit.toLocaleString('en-US',{maximumFractionDigits:2})} (${o.identifier})`;
function describe(r){const d=r.data;if(r.event==='decision')return d.kind+(d.orders.length?' — '+d.orders.map(order).join('; '):'');if(r.event==='exchange_message')return d[1].kind+' arrived — '+d[1].orders.map(order).join('; ');if(r.event==='exchange_fill')return `${d.order}: ${d.quantity>0?'buy':'sell'} ${Math.abs(d.quantity).toFixed(4)} @ ${d.price}; remaining ${d.remaining.toFixed(4)}; source ${d.source_id}`;if(r.event==='received_fill')return `${d.order.identifier}: fill ${d.quantity.toFixed(4)} reported`;return 'Acknowledged '+d.request;}
function render(){const e=bundle.examples[Number(select.value)],index=Number(slider.value),r=e.trace[index];document.getElementById('status').textContent=`${new Date(e.start).toISOString().slice(0,10)} | ${e.fills.length} fill fragments | event ${index+1}/${e.trace.length} | exact decision/fill match verified`;document.getElementById('selected').textContent=when(r.time)+' — '+r.event;document.getElementById('detail').textContent=JSON.stringify(r,null,2);Array.from(body.children).forEach((row,i)=>row.className=i===index?'active':'');document.getElementById('previous').disabled=index===0;document.getElementById('next').disabled=index===e.trace.length-1;}
function load(){const e=bundle.examples[Number(select.value)];slider.max=e.trace.length-1;slider.value=0;body.replaceChildren();e.trace.forEach((r,i)=>{const tr=document.createElement('tr');[when(r.time),r.event.replaceAll('_',' '),describe(r)].forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.appendChild(td)});body.appendChild(tr)});render();}
bundle.examples.forEach((e,i)=>{const o=document.createElement('option');o.value=i;o.textContent=e.name;select.appendChild(o)});select.value=0;select.addEventListener('change',load);slider.addEventListener('input',render);document.getElementById('previous').addEventListener('click',()=>{slider.value=Math.max(0,Number(slider.value)-1);render()});document.getElementById('next').addEventListener('click',()=>{slider.value=Math.min(Number(slider.max),Number(slider.value)+1);render()});load();
</script></body></html>'''.replace('PAYLOAD',payload)
html=html.replace('src="replays-v1.png"','src="data:image/png;base64,'+base64.b64encode((ROOT/'replays-v1.png').read_bytes()).decode()+'"')
(ROOT/'replays-v1.html').write_text(html)
print('Wrote replays-v1.html and replays-v1.png')
