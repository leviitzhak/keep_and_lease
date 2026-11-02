"""Create the research report and standard matplotlib figures from saved runs."""
from pathlib import Path
import json
import platform
import statistics
import sys
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).resolve().parent;OUT=HERE/'longer_results'
def read(name):return json.loads((OUT/name).read_text())

def main():
    study=read('study.json');follow=read('followup.json');refine=read('refinement.json')
    assert study['status']=='completed' and len(study['runs'])==48
    assert len(follow['runs'])==4 and len(refine['runs'])==6
    threshold=study['protocol']['convergence_rmse_usd']
    long_runs=[dict(r,trajectories=256) for r in follow['runs']]+refine['runs']
    selected={}
    for T in [8,16,32,64]:
        successful=sorted([r for r in long_runs if r['T']==T and r['confirmed']],key=lambda r:r['trajectories'])
        selected[T]=successful[0] if successful else None
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True,sharey=True,layout='constrained')
    for ax,T in zip(axes.flat,[8,16,32,64]):
        budgets=[4,16,64,256];means=[];low=[];high=[]
        for n in budgets:
            vals=[r['test']['rmse_usd'] for r in study['runs'] if r['T']==T and r['trajectories']==n]
            means.append(statistics.mean(vals));low.append(min(vals));high.append(max(vals))
        ax.fill_between(budgets,low,high,color='#345A84',alpha=.12,label='12k seed range')
        ax.plot(budgets,means,'o-',color='#345A84',label='12k updates, mean of 3 seeds')
        rr=sorted([r for r in long_runs if r['T']==T],key=lambda r:r['trajectories'])
        ax.plot([r['trajectories'] for r in rr],[r['test']['rmse_usd'] for r in rr],'s--',color='#AD6C22',label='60k updates, seed 20261101')
        ax.axhline(threshold,color='#555555',linestyle=':',label='Four-step RMSE benchmark')
        ax.set_title(f'{T} decision steps');ax.set_xscale('log',base=4);ax.set_xticks(budgets,[str(x) for x in budgets]);ax.set_ylim(0,1.15);ax.grid(alpha=.18)
        ax.set_xlabel('Completed training trajectories');ax.set_ylabel('Held-out liquidation RMSE (USD)')
    handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=2,frameon=False)
    fig.suptitle('More simulations alone did not remove the value error',fontsize=15)
    fig.savefig(OUT/'simulation_budget.png',dpi=160);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,8),sharex=True,sharey=True,layout='constrained')
    for ax,r in zip(axes.flat,follow['runs']):
        curve=r['curve'];xs=[x['update'] for x in curve]
        ax.plot(xs,[x['train']['rmse_usd'] for x in curve],color='#345A84',label='Train')
        ax.plot(xs,[x['validation']['rmse_usd'] for x in curve],color='#AD6C22',label='Validation')
        ax.scatter([r['best_update']],[r['test']['rmse_usd']],marker='D',color='#2F7859',label='Test at selected update',zorder=4)
        ax.axhline(threshold,color='#555555',linestyle=':');ax.axvline(12000,color='#999999',linestyle='--',linewidth=1)
        ax.set_title(f"{r['T']} steps, identical 256 trajectories");ax.set_ylim(0,1.2);ax.set_xlim(0,60000);ax.grid(alpha=.18)
        ax.set_xlabel('Adam updates');ax.set_ylabel('Liquidation-value RMSE (USD)')
    handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=3,frameon=False)
    fig.suptitle('Same simulation data, more training — zoom to RMSE ≤ $1.20',fontsize=15)
    fig.savefig(OUT/'training_convergence.png',dpi=160);plt.close(fig)

    lines=['# Longer single-bill timelines: convergence and simulation counts','',
      'Measured on 1 November 2026. The original four-step example is preserved beside this report.','',
      'Follow-up, 2 November: the [1,024-step study](TIMELINE_1024.md) audits a comparison '
      'limitation here. The old test-set horizon weights change with T (h=0–3 account '
      'for 90.5% of eight-step rows but 7.04% of 64-step rows). The results below remain '
      'valid for their own datasets; across-T RMSE is not a common-distribution '
      'comparison. The new study also distinguishes value accuracy from greedy policy quality.','',
      '**The 32- and 64-step value functions reached the four-step error benchmark after longer optimization.** '
      'Adding trajectories without extending optimization did not achieve that benchmark. The smaller 8- and 16-step cases '
      'still missed it after 60,000 updates on the tested 256-trajectory datasets.','',
      'The same 97-parameter network was used throughout. The benchmark is RMSE ≤ **USD 0.3531**, '
      'the previous four-step in-sample error rounded to four decimals. Here the criterion is stronger: '
      'three consecutive validation checkpoints (500 updates apart) below the benchmark, plus the selected checkpoint’s '
      'test error below it. This is a numerical tolerance, not an assertion of exact or asymptotic convergence.','',
      '## How many simulations were enough in the tested runs?','',
      'The following are the smallest **tested** successful trajectory budgets at 60,000 updates, seed 20261101. '
      'The follow-up budgets and held-out sets were reused adaptively for diagnosis. These counts are not '
      'statistical guarantees across seeds or market laws. The 12,000-update experiment tested three seeds.','',
      '| Decision steps | Smallest tested successful trajectories | Training transitions | Unique training labels | First sustained validation threshold | Selected update | Test RMSE (USD) |','|---:|---:|---:|---:|---:|---:|---:|']
    for T in [8,16,32,64]:
        r=selected[T]
        if r:
            lines.append(f"| {T} | {r['trajectories']:,} | {T*r['trajectories']:,} | {r['training_labels']:,} | {r['sustained_validation_threshold_update']:,} | {r['best_update']:,} | {r['test']['rmse_usd']:.4f} |")
        else:
            r=next(r for r in follow['runs'] if r['T']==T)
            lines.append(f"| {T} | Not established; 256 did not pass | {256*T:,} | {r['training_labels']:,} | Not reached | {r['best_update']:,} | {r['test']['rmse_usd']:.4f} |")
    lines+=['','For unsuccessful rows, the numbers describe the 256-trajectory follow-up. Smaller budgets for those '
             'two timelines were tested at 12,000 updates, not exhaustively at 60,000. Failure at 256 does not prove '
             'that every smaller budget or every longer optimization schedule would fail.','',
             '## Same data, more optimization','',
             'This comparison uses the same 256 trajectories and seed in both columns. The first 12,000 optimizer '
             'updates of each extended run reproduce the original run exactly. No new distinct training '
             'trajectories were added.','',
             '| Steps | Train RMSE at selected 12k checkpoint | Test RMSE at selected 12k checkpoint | Train RMSE at selected 60k checkpoint | Test RMSE at selected 60k checkpoint |','|---:|---:|---:|---:|---:|']
    for T in [8,16,32,64]:
        a=next(r for r in study['runs'] if r['T']==T and r['seed']==20261101 and r['trajectories']==256)
        b=next(r for r in follow['runs'] if r['T']==T)
        lines.append(f"| {T} | {a['train']['rmse_usd']:.4f} | {a['test']['rmse_usd']:.4f} | {b['train']['rmse_usd']:.4f} | {b['test']['rmse_usd']:.4f} |")
    lines+=['','![Convergence with unchanged data](longer_results/training_convergence.png)','',
      'The convergence figure zooms to RMSE ≤ USD 1.20 to expose later training. Larger initial errors remain in the saved curves. The dashed vertical line marks 12,000 updates.','',
      'The 8- and 16-step training errors themselves remain above the benchmark. Their remaining error '
      'cannot be attributed solely to missing held-out coverage. The cause could involve optimization or '
      'the small network’s approximation of short-horizon boundaries; these experiments do not isolate the cause.','',
      '## Simulation-budget sweep','',
      '48 runs: 8, 16, 32, 64 steps × 4, 16, 64, 256 completed training trajectories × 3 seeds, each with '
      '12,000 Adam updates. Every run starts from a fresh network. Trajectory prefixes are nested within each '
      '(timeline, seed), so larger budgets extend the same data.','',
      '| Steps | Test RMSE, 4 trajectories | 16 trajectories | 64 trajectories | 256 trajectories |','|---:|---:|---:|---:|---:|']
    for T in [8,16,32,64]:
        vals=[statistics.mean(r['test']['rmse_usd'] for r in study['runs'] if r['T']==T and r['trajectories']==n) for n in [4,16,64,256]]
        lines.append('| '+str(T)+' | '+' | '.join(f'{v:.4f}' for v in vals)+' |')
    lines+=['','Values are means over the three seeds. No 12,000-update run met the convergence criterion.',
      '','![Simulation budgets](longer_results/simulation_budget.png)','',
      '## What is counted as a simulation?','',
      '- **Training trajectory:** one complete length-T rollout, with actions chosen uniformly from the legal wait/buy/sell menu.',
      '- **Training transition:** one executed action and its resulting next state. A budget of N trajectories costs N×T transitions.',
      '- **Exact planning action evaluation:** a candidate edge in the shared full-depth search. These are additional to training rollouts.',
      '- **Training label:** one distinct retained (state, remaining horizon) example. All valid horizons, including zero, are included.',
      '- **Optimizer update:** one gradient update using existing labels. It creates no new simulated market trajectory.','',
      'Cash enters the terminal value additively, and funding cannot bind in this bounded toy. Therefore all '
      'states with the same (time, bill quantity, endpoint) share the same continuation increment, even if '
      'their cash balances differ. Dynamic programming evaluates those identical subproblems once. '
      'No network values replace terminal labels, and no future depth is truncated.','',
      '| Steps | Complete action paths represented from the initial state | Exact planner action evaluations | Liquidation boundary evaluations | Training transitions for 256 trajectories |','|---:|---:|---:|---:|---:|']
    for m in study['markets']:
        lines.append(f"| {m['T']} | {int(m['root_complete_paths']):,} | {m['oracle_edges']:,} | {m['oracle_boundaries']:,} | {256*m['T']:,} |")
    lines+=['','For 64 steps, enumerating roughly 5.36×10²⁷ complete paths would be impractical. The exact '
      'shared-state planner performs 27,040 action evaluations covering **all endpoints**, plus 325 closing '
      'boundaries. It is built once per timeline and reused across budgets and network seeds. Its measured '
      'construction took about 0.011 seconds in this environment; that timing is specific to this very small '
      'deterministic state space and excludes data generation and fitting. This affine cash reduction '
      'must not be assumed valid with binding funding, hidden orders or path-dependent obligations.','',
      'Evaluation costs are separate: each timeline creates 512 deterministic rollouts per held-out split '
      '(validation and test), then limits each evaluation set to at most 512 states and approximately 2,048 '
      'labels. The same rollout seed is replayed for the two split filters, so those two replay passes are '
      'duplicate market paths rather than distinct scenarios. Policy evaluation also simulates candidate '
      'actions; its per-run count is recorded in `evaluation_candidate_transitions`. Follow-ups reconstruct '
      'the identical training prefixes and reuse the evaluation sets.','',
      '## Value convergence versus strategy quality','']
    bad=[r for r in study['runs'] if r['policy']['full_horizon_regret_usd']>1e-8]
    lines.append(f"At 12,000 updates, {48-len(bad)} of 48 fitted networks selected the exact optimal strategy "
                 'from the initial portfolio through the full timeline, even though their value estimates missed '
                 'the error threshold. The single exception lost USD 0.125 relative to the exact optimum. '
                 'All four 256-trajectory 60k follow-ups selected the full-horizon optimum. Across the original '
                 '48 runs, the worst average regret over all initial-state horizons was USD '
                 f"{max(r['policy']['mean_horizon_regret_usd'] for r in study['runs']):.6f}.")
    lines+=['','This monotonic tape makes the optimal full-horizon action pattern simple: buy up to four bills '
      'as early as possible, then wait. Correct rankings on that path do not certify accurate values for '
      'all portfolios or generalization to a new market process.','',
      '## Controlled setup and limits','',
      '- Initial cash USD 1,000, zero bills; one-unit actions; inventory cap four; face USD 100.',
      '- Price is `P(t)=95+2*t/T`: the same USD 95→97 rise over every strategic timeline. Maturity is `2.5*T`, '
        'and the repeated closing tail remains below face value. Thus the experiment varies decision length '
        'while preserving the overall price move; it does not hold the per-step drift constant.',
      '- The same two one-unit prints per step, ±USD 0.25 offsets, strict through-limit strategic fills at the limit, '
        'subsequent-print liquidation, zero fees/delays and ignored liquidation duration as the four-step example.',
      '- A deterministic hash assigns whole states 70%/15%/15% to train/validation/test. Every horizon of a state '
        'stays in that partition; no exact state is shared between train and either holdout. The initial state '
        'is explicitly in train. These are state holdouts on the same deterministic market law, not new-market tests.',
      '- Four inputs `(cash-1000)/400, quantity/4, time/T, remaining_horizon/T`; 16 tanh units; 97 parameters; '
        '`v=1000+10*network_output`. No architecture enlargement or analytic value skip connection was used.',
      '- Each horizon receives equal sampling weight. Full-batch weighted training is used for at most 256 labels; '
        'otherwise each 256-row batch samples horizons uniformly, then rows uniformly within that horizon.',
      '- Adam learning rate 0.003 through update 6,000, then 0.0006. Validation checkpoints every 500 updates; '
        'the minimum-validation-RMSE checkpoint is selected before its one test evaluation.',
      '- The original 48-run grid was fixed before running. The 60k extensions and smaller-budget refinements '
        'were follow-up diagnoses that reused the holdouts. The successful budgets were checked with one seed, '
        'so a robust minimum simulation requirement remains unestablished.','',
      '## Reproduction and checks','',
      '```bash','cd docs/research/single_bill_full_search',
      'python -m unittest test_longer_timelines -v',
      'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python longer_timelines.py',
      'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python longer_followup.py',
      'OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python sample_refinement.py',
      'python report_longer.py','```','',
      'The runner bounds the original campaign to 600 seconds and writes results after each completed fit. '
      'Each follow-up also has a 600-second bound. Set BLAS to one thread as shown for comparable replay. '
      'Python/NumPy are sufficient for fitting; matplotlib is only needed for report figures.','',
      'Seven focused tests passed: all 61 original labels, explicit eight-step exhaustive paths, sequential '
      'closing prints, split separation/all-horizon coverage, affine cash/count accounting, network '
      'initialization, and an independent optimal buy-first cashflow formula for every planner state '
      'through 64 steps. Follow-up checks reproduce the first 12,000 updates exactly.','',
      f"Measured campaign time: original grid {study['wall_seconds']:.1f}s; 256-trajectory extensions "
      f"{follow['wall_seconds']:.1f}s; smaller-budget refinements {refine['wall_seconds']:.1f}s. "
      'These are wall times on this shared CPU runtime, not hardware-independent throughput claims.','',
      '- [All 48 original runs and model weights](longer_results/study.json)',
      '- [Compact original-run table](longer_results/summary.csv)',
      '- [60k-update continuations](longer_results/followup.json)',
      '- [Smaller-budget refinements](longer_results/refinement.json)',
      '- [Machine-readable selected budgets](longer_results/conclusion.json)','']
    (HERE/'LONGER_TIMELINES.md').write_text('\n'.join(lines))
    conclusion=dict(threshold_usd=threshold,selection_seed=20261101,
        selected={str(T):({k:r[k] for k in ['trajectories','training_labels','best_update','sustained_validation_threshold_update','test','policy']} if r else None) for T,r in selected.items()},
        original_grid_runs=48,extended_runs=4,refinement_runs=6,
        limitations='Adaptive reused state holdouts; one deterministic law; successful budgets checked with one seed')
    (OUT/'conclusion.json').write_text(json.dumps(conclusion,indent=2))
    (OUT/'environment.json').write_text(json.dumps(dict(python=platform.python_version(),numpy=np.__version__,matplotlib=matplotlib.__version__,machine=platform.machine(),blas_threads=1),indent=2))
    # Compact the large machine-readable records without changing their values.
    for name in ['study.json','followup.json','refinement.json']:
        p=OUT/name;p.write_text(json.dumps(json.loads(p.read_text()),separators=(',',':'),allow_nan=False)+'\n')
    print(json.dumps(conclusion,indent=2))

if __name__=='__main__':main()
