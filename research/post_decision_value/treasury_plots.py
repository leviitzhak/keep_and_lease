"""Static diagnostics from saved data only. Never trains or selects a model."""
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from .treasury_learning import read
from .treasury_model import load_scalar, DIAGNOSTIC_VERSION


def render(output):
    output=Path(output);plots=output/'plots';plots.mkdir(exist_ok=True)
    plt.rcParams.update({'figure.dpi':130,'axes.spines.top':False,'axes.spines.right':False,
                         'axes.grid':True,'grid.alpha':.18,'font.size':10})
    curve=read(output/'learning-curve.json')
    if curve:
        fig,axs=plt.subplots(1,2,figsize=(11,4),layout='constrained')
        for stage in dict.fromkeys(p['stage'] for p in curve):
            ps=[p for p in curve if p['stage']==stage]
            for split,style in [('train','-'),('validation','--')]:
                axs[0].plot([p['updates'] for p in ps],[p[split]['loss'] for p in ps],style,label=f'{stage} {split}')
                axs[1].plot([p['updates'] for p in ps],[p[split]['mae'] for p in ps],style,label=f'{stage} {split}')
        axs[0].set(yscale='log',xlabel='Cumulative optimizer updates',ylabel='Normalized scalar MSE',title='Training / validation loss')
        axs[1].set(xlabel='Cumulative optimizer updates',ylabel='Utility MAE',title='Error against matching outcome labels')
        axs[0].legend(fontsize=7);fig.suptitle('Frozen campaign • test outcomes excluded from selection')
        fig.savefig(plots/'learning.png');plt.close(fig)
    model,_,_=load_scalar(output/'selected-model.pt')
    paths=sorted(output.glob('validation-*.json.gz'))
    if model.target_version==DIAGNOSTIC_VERSION:
        paths=[]  # Never call diagnostic hold values calibrated max-min values.
    rows=[r for r in read(paths[-1]) if r['done']] if paths else read(output/'diagnosis-validation.json.gz')
    pred=model.predict([r['features'] for r in rows]);ref=np.array([r['target'] for r in rows])
    fig,axs=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    axs[0].scatter(ref,pred,s=15,alpha=.65)
    lo,hi=min(ref.min(),pred.min()),max(ref.max(),pred.max())
    axs[0].plot([lo,hi],[lo,hi],color='black',lw=1)
    axs[0].set(xlabel='Independent audited search target' if paths else 'Independent diagnostic reference',ylabel='Predicted scalar',title='Validation predictions')
    worst=np.argsort(abs(pred-ref))[-10:]
    axs[1].barh(range(len(worst)),(pred-ref)[worst],color='#d97735')
    axs[1].set_yticks(range(len(worst)),[f"{rows[i]['case'].split('-')[-1]} / {rows[i]['horizon_ms']/86400000:.2g} d" for i in worst])
    axs[1].set(xlabel='Prediction − matching reference',title='Largest validation errors')
    fig.savefig(plots/'reference-errors.png');plt.close(fig)
    cases={c['id']:c for cs in read(output/'fixtures.json').values() for c in cs}
    data=read(output/'diagnosis-train.json.gz')
    fig,axs=plt.subplots(1,3,figsize=(13,4),layout='constrained')
    held=[r for r in data if r['kind']=='hold']
    points=axs[0].scatter([cases[r['case']]['price'] for r in held],[r['quantity'] for r in held],
                          c=[r['target'] for r in held],cmap='coolwarm',s=60)
    axs[0].set(xlabel='Posted price / unit (USD)',ylabel='Native quantity',title='Generated hold-through-maturity data')
    fig.colorbar(points,ax=axs[0],label='Utility')
    for ax,kind in zip(axs[1:],('hold','boundary')):
        rs=[r for r in data if r['kind']==kind]
        cs=sorted({r['case'] for r in rs},key=lambda c:cases[c]['price'])
        qs=sorted({r['quantity'] for r in rs})
        z=np.full((len(cs),len(qs)),np.nan)
        for r in rs:z[cs.index(r['case']),qs.index(r['quantity'])]=r['target']
        im=ax.imshow(z,aspect='auto',cmap='coolwarm')
        ax.set_xticks(range(len(qs)),qs);ax.set_yticks(range(len(cs)),[f"{cases[c]['price']:.2f}" for c in cs])
        ax.set(xlabel='Quantity',ylabel='Case price (USD)',title='28-day hold labels' if kind=='hold' else 'H=0 owned-inventory closing labels')
        fig.colorbar(im,ax=ax,label='Utility');ax.grid(False)
    fig.suptitle('Synthetic Treasury • blank cells are inadmissible • no historical price claims')
    fig.savefig(plots/'data-surfaces.png');plt.close(fig)
    collection=output/'train-0.json.gz'
    if collection.exists():
        collected=read(collection)
        branches=[b for r in collected for row in r.get('branches',[]) for b in row]
        if branches:
            longest=max(branches,key=lambda b:len(b['decisions']))
            ds=longest['decisions'][:100]
            if ds:
                fig,axs=plt.subplots(2,1,figsize=(10,6),layout='constrained')
                t0=ds[0]['time'];ts=[(d['time']-t0)/1000 for d in ds]
                axs[0].plot(ts,[d['predicted'] for d in ds],'.-',lw=1)
                axs[0].set(ylabel='Selected predicted utility',title='Saved incomplete rollout: first 100 decisions')
                for kind,level in [('create',1),('cancel',0),('wait',-1)]:
                    xs=[t for t,d in zip(ts,ds) if d['instruction']['kind']==kind]
                    axs[1].scatter(xs,[level]*len(xs),s=20,label=kind)
                axs[1].set_yticks([-1,0,1],['wait','cancel','create'])
                axs[1].set(xlabel='Seconds since first shown decision',ylabel='Instruction')
                fig.suptitle(f"CAPPED • {len(longest['decisions']):,} decisions in this branch • no completed target")
                fig.savefig(plots/'collection-churn.png');plt.close(fig)
        states=list(dict.fromkeys((r['case'],r['origin'],r['state_id']) for r in collected))
        horizons=sorted({r['horizon_ms'] for r in collected})
        mask=np.full((len(states),len(horizons)),np.nan)
        for r in collected:
            i=states.index((r['case'],r['origin'],r['state_id']));j=horizons.index(r['horizon_ms'])
            mask[i,j]=1 if r['done'] else 0 if r.get('reason')=='unsupported_horizon' else -1
        fig,ax=plt.subplots(figsize=(7,6),layout='constrained')
        from matplotlib.colors import ListedColormap
        im=ax.imshow(mask,aspect='auto',vmin=-1,vmax=1,cmap=ListedColormap(['#cf663b','#adb5bd','#3f8c81']))
        ax.set_xticks(range(len(horizons)),[f'{h/86400000:.4g}' for h in horizons]);ax.grid(False)
        ax.set(xlabel='Requested horizon (days)',ylabel='Candidate post-state / outer anchor',title='Saved training labels and support')
        cb=fig.colorbar(im,ax=ax,ticks=[-1,0,1]);cb.ax.set_yticklabels(['Incomplete','Unsupported','Complete'])
        fig.savefig(plots/'horizon-support.png');plt.close(fig)
    test=output/'test-evaluation.json.gz'
    if test.exists():
        evaluation=read(test);cs=evaluation['cases']
        fig,ax=plt.subplots(figsize=(11,4),layout='constrained')
        xs=np.arange(len(cs))
        for offset,key,label in [(-.25,'minimum','Network-only min'),(0,'search_value','Sampled search'),(.25,'oracle','Finite-toy optimum')]:
            ax.bar(xs+offset,[c['toy_optimum']['value'] if key=='oracle' else c[key] for c in cs],width=.24,label=label)
        ax.axhline(0,color='black',lw=1,label='Cash hold')
        ax.set_xticks(xs,[c['category'].replace('_','\n') for c in cs]);ax.set(ylabel='Joint utility',title='One fresh held-out evaluation • matching liquidation convention')
        ax.legend(fontsize=8);fig.savefig(plots/'policy-comparison.png');plt.close(fig)
        for n,c in enumerate(cs[:4]):
            branch=c['policy'][0];events=branch['events'];start=cases[c['case']]['start']
            fig,axs=plt.subplots(3,1,figsize=(11,7),layout='constrained')
            ts=[(e['time']-start)/86400000 for e in events]
            axs[0].step(ts,[e.get('balances_after',e['balances_before'])['USD'] for e in events],where='post',label='Hidden cash')
            decisions=branch['decisions']
            axs[0].scatter([(d['time']-start)/86400000 for d in decisions],[d['observable']['ledger']['balances']['USD'] for d in decisions],s=12,label='Received cash at decisions')
            axs[0].set(ylabel='USD',title=c['category']);axs[0].legend(fontsize=8)
            axs[1].step(ts,[e.get('positions_after',{}).get('BILL',{}).get('quantity',0) for e in events],where='post')
            axs[1].set(ylabel='BILL units')
            kinds=['message','trade','report','observation','asset_cashflow']
            for k,kind in enumerate(kinds):
                ds=[(e['time']-start)/86400000 for e in events if e['kind']==kind]
                axs[2].scatter(ds,[k]*len(ds),s=15,label=kind)
            axs[2].set_yticks(range(len(kinds)),kinds);axs[2].set(xlabel='Days since start',ylabel='Event type')
            for ax in axs:ax.axvline(28,color='#3f8c81',ls='--',lw=1)
            fig.suptitle('Exact replay: hidden arrivals/trades versus received reports; dashed line is maturity')
            fig.savefig(plots/f'trajectory-{n}.png');plt.close(fig)
    return sorted(str(p) for p in plots.glob('*.png'))
