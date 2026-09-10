#!/usr/bin/env python3
"""Compare aggregate metrics; full order/fill evidence stays at each audit URI."""
import argparse
import json
from pathlib import Path


def compare(directory):
    directory=Path(directory)
    reports={p:json.loads((directory/p/'report.json').read_text()) for p in ('sequence','timestamp')}
    left,right=reports['sequence'],reports['timestamp']
    for key in ('days','interval_seconds','strategy_parameters_sha256'):
        if left[key]!=right[key]:raise ValueError('Cannot compare different replay windows or clocks')
    for key in ('manifest_sha256','capital_usd','participation','delay_seconds'):
        if left['replay'][key]!=right['replay'][key]:raise ValueError('Cannot compare different datasets or execution settings')
    metrics={}
    for section,keys in [('summary',('ending_nav','compounded_return','max_drawdown','direct_holding_return')),
                         ('replay',('fills','orders','cancelled_remainders','fees_usd','turnover_usd','treasury_interest_usd','no_fresh_curve_decisions'))]:
        for key in keys:
            a,b=left[section][key],right[section][key]
            metrics[key]=dict(sequence=a,timestamp=b,timestamp_minus_sequence=b-a)
    result=dict(days=left['days'],interval_seconds=left['interval_seconds'],metrics=metrics,
                scenarios={p:dict(ordering=r['replay']['ordering'],audit_uri=r['audit_destination'],
                                 anomaly_evidence=r['replay']['anomaly_evidence']) for p,r in reports.items()},
                limitation='Sensitivity to these two assumed timelines only; no reconstruction or bound of historical publication delay. Aggregate differences do not identify every changed order; full per-order evidence is retained in the linked audits.')
    (directory/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--directory',required=True)
    print(json.dumps(compare(p.parse_args().directory)['metrics'],indent=2))
