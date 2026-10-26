"""Plot saved historical analytical study outcomes; performs no replay."""
import argparse
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np


def render(root):
    root = Path(root)
    report = json.loads((root/'report.json').read_text())
    for split, title in [('test', 'Held-out test: August 17–September 3, 2026'),
                         ('full_period_original', 'Untuned analytical policy: all 90 cached days')]:
        fig, axes = plt.subplots(2, 1, figsize=(10, 6.2), sharex=True)
        grouped = {}
        for name in report['episodes']:
            folder = root/'episodes'/name
            result = json.loads((folder/'result.json').read_text())
            if result['split'] != split or result['delay_multiplier'] != 1:
                continue
            key = 'Hold' if result['hold'] else result['preset']
            grouped.setdefault(key, []).append(json.loads((folder/'daily.json').read_text()))
        for k, (name, rows) in enumerate(grouped.items()):
            dates = [datetime.fromisoformat(d['date']) for d in rows[0]]
            color = '#9ca3af' if name == 'Hold' else ['#2563eb', '#16a34a', '#9333ea'][k % 3]
            for ax, currency in zip(axes, ['BTC', 'USD']):
                values = np.array([[day['growth'][currency]*100 for day in row] for row in rows])
                ax.plot(dates, values.mean(0), label=name, color=color, linewidth=1.8)
                ax.fill_between(dates, values.min(0), values.max(0), color=color, alpha=.15)
                ax.set_ylabel(f'{currency} growth (%)')
                ax.axhline(0, color='#64748b', linewidth=.6)
                ax.grid(alpha=.2)
        axes[0].legend(loc='best', frameon=False)
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=8))
        fig.suptitle(title, fontsize=14)
        fig.text(.09, .015,
                 'Contractual holdings, not realized expiry settlement. Shading: two latency seeds, not confidence intervals.\n'
                 'Counterfactual linear trading on inverse prints; hourly decisions. Original policy fails funding-stress checks in both seeds.',
                 fontsize=8, color='#475569')
        fig.tight_layout(rect=(0, .06, 1, .96))
        for ext in ('png', 'svg'):
            fig.savefig(root/f'{split}-growth.{ext}', dpi=160)
        plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    render(parser.parse_args().run)
