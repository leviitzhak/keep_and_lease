"""Figure for the frozen illustrative 3.75%/2.75% comparison, not a winner."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
 root=Path(__file__).parent/'extended-results'
 runs=json.loads((root/'btc-prd-2026-extension.json').read_text())['runs']
 scenarios=['one_ms_delays','base','two_second_delays'];labels=['1 ms','500 ms','2,000 ms']
 fig,axes=plt.subplots(1,2,figsize=(9.2,3.3))
 for phase,color in [('validation','#37738a'),('test','#ce7131')]:
  series=[]
  for scenario in scenarios:
   rows=[r for r in runs if r['scenario']==scenario and r['phase']==phase and r['high']==.0375 and r['low']==.0275]
   series.append((sum(r['completed_cycles'] for r in rows),sum(r['completed_cycle_realized_net_usd'] for r in rows)))
  for i,ax in enumerate(axes):
   values=[v[i] for v in series];ax.plot(range(3),values,'o-',color=color,label=phase.capitalize(),linewidth=2,markersize=5)
   for j,v in enumerate(values):ax.annotate(str(v) if i==0 else f'${v:.3f}',(j,v),xytext=(0,(9 if phase=='test' else -15) if i==0 or j==0 else (9 if phase=='validation' else -15)),textcoords='offset points',ha='center',fontsize=8,color=color)
 for ax,title in zip(axes,['Completed cycles','Realized net gain from closed cycles']):
  ax.set_title(title,fontsize=11,loc='left',pad=12);ax.set_xticks(range(3),labels);ax.set_xlabel('Delay for each of the two legs',fontsize=9)
  ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.16);ax.margins(x=.14,y=.25);ax.tick_params(labelsize=8)
 axes[0].legend(frameon=False,fontsize=8,loc='upper left');axes[1].set_ylabel('USD; two independent $10-face probes',fontsize=8)
 fig.suptitle('Speed changes fill quality as well as cycle count',x=.08,ha='left',fontsize=13,fontweight='bold',y=1.02)
 fig.tight_layout();fig.savefig(root/'btc-prd-latency.png',dpi=180,bbox_inches='tight');plt.close(fig)
if __name__=='__main__':main()
