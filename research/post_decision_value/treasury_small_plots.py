"""Render saved single-BILL diagnostics; never fit or generate test labels."""
import argparse
import gzip
import json
from pathlib import Path


def render(output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    output = Path(output)
    curve = json.loads((output / 'learning-curve.json').read_text())
    predictions = json.loads((output / 'predictions.json').read_text())
    report = json.loads((output / 'report.json').read_text())
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    colors = {'train': '#4669a6', 'validation': '#cf7b31', 'test': '#208a75'}
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), layout='constrained')
    ax = axes[0]
    for split in ('train', 'validation'):
        ax.plot([p['updates'] for p in curve],
                [p[split]['loss'] for p in curve], label=split.title(),
                color=colors[split], linewidth=2)
    ax.set(yscale='log', xlabel='Optimizer updates', ylabel='Normalized scalar MSE',
           title='Learning and validation')
    ax.legend(frameon=False)
    ax.axvline(report['selected_updates'], color='#757575', linestyle=':', linewidth=1)
    ax.grid(alpha=.18)
    ax = axes[1]
    for split in ('train', 'validation', 'test'):
        for kind, marker in (('hold', 'o'), ('boundary', 'x')):
            rows = [r for r in predictions if r['split'] == split and r['kind'] == kind]
            if rows:
                ax.scatter([r['target'] for r in rows], [r['prediction'] for r in rows],
                           color=colors[split], marker=marker, alpha=.75, s=32,
                           label=f'{split.title()} / {kind}')
    values = [r[k] for r in predictions for k in ('target', 'prediction')]
    lo, hi = min(values), max(values)
    padding = max((hi-lo)*.07, .0001)
    ax.plot([lo-padding, hi+padding], [lo-padding, hi+padding], '--', color='#6b7280')
    ax.set(xlabel='Complete replay utility', ylabel='Predicted utility',
           title='Saved checkpoint calibration')
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=.18)
    ax = axes[2]
    choice_split = 'test' if any(r['split']=='test' for r in predictions) else 'validation'
    test = [r for r in predictions if r['split'] == choice_split and r['kind'] == 'hold']
    cases = sorted({r['case'] for r in test})
    if cases:
        for i, case in enumerate(cases):
            rows = [r for r in test if r['case'] == case]
            best_prediction = max(r['prediction'] for r in rows)
            chosen = next(r for r in rows if r['prediction'] >= best_prediction-1e-6)
            optimum = max(r['target'] for r in rows)
            ax.bar(i-.18, chosen['target'], width=.36, color=colors['test'],
                   label='Selected action' if i == 0 else None)
            ax.bar(i+.18, optimum, width=.36, color='#b5beca',
                   label='Best feasible reference' if i == 0 else None)
            ax.annotate(f"q={chosen['quantity']:g}", (i, max(chosen['target'], optimum)),
                        xytext=(0, 8), textcoords='offset points', ha='center', fontsize=9)
        labels = [next(r['category'] for r in test if r['case'] == c).replace('_', '\n')
                  for c in cases]
        ax.set_xticks(range(len(cases)), labels)
        ax.margins(y=.35)
        ax.legend(frameon=False, fontsize=8)
    else:
        ax.text(.5, .5, 'Fresh test withheld\nValidation gate failed', ha='center',
                va='center', transform=ax.transAxes)
    ax.axhline(0, color='#6b7280', linewidth=.8)
    title = 'Fresh test action choices' if choice_split=='test' else 'Validation choices (fresh test withheld)'
    ax.set(ylabel='Complete hold-through-maturity utility', title=title)
    ax.grid(axis='y', alpha=.18)
    fig.suptitle('Single BILL | four received history steps | diagnostic only', fontsize=15)
    fig.savefig(output / 'analysis.png', dpi=180)
    fig.savefig(output / 'analysis.svg')
    plt.close(fig)
    # A saved training-label replay illustrates what the four-step input omits:
    # the simulator still processes both partial fills and the entire maturity.
    rows = json.loads(gzip.decompress((output / 'rows-train.json.gz').read_bytes()))
    row = next(r for r in rows if r['category']=='profitable' and
               r['kind']=='hold' and r['quantity']==60)
    history = row['history']
    start = row['observation_time']
    events = row['replay']['events']
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.3), layout='constrained')
    axes[0].plot([(h['received']-start)/1000 for h in history],
                 [h['price'] for h in history], 'o-', color=colors['train'])
    axes[0].set(xlabel='Seconds before initial decision', ylabel='Received BILL price (USD)',
                title='Exactly four received history records')
    days = [0.] + [(e['time']-start)/86400000 for e in events]
    cash = [10000.] + [e['balances_after']['USD'] for e in events]
    units = [0.] + [e['positions_after'].get('BILL', {}).get('quantity', 0.) for e in events]
    axes[1].step(days, cash, where='post', color=colors['test'])
    axes[1].set(xlabel='Days after initial decision', ylabel='USD cash (excludes BILL inventory)',
                title='Both purchases and day-28 redemption')
    axes[2].step(days, units, where='post', color=colors['train'])
    axes[2].set(xlabel='Days after initial decision', ylabel='BILL units held',
                title='Partial fills: 30 + 30; final inventory: 0')
    for ax in axes:
        ax.grid(alpha=.18)
    fig.suptitle('Saved label replay | profitable training case | 60-unit hold action', fontsize=14)
    fig.savefig(output / 'history-and-cashflows.png', dpi=180)
    fig.savefig(output / 'history-and-cashflows.svg')
    plt.close(fig)
    return {'plot': str(output / 'analysis.png'), 'rows': len(predictions),
            'test_cases': len(cases) if choice_split=='test' else 0, 'report_present': bool(report)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(render(args.output)))
