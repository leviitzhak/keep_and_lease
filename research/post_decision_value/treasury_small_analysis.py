"""Posthoc analysis of saved development rows and a frozen BILL checkpoint.

This command never fits, generates fixtures, evaluates a fresh test, or selects
another checkpoint. A history-slot substitution is a feature-sensitivity probe,
not an alternative policy or an acceptance result.
"""
import argparse
from collections import defaultdict
import hashlib
import math
from pathlib import Path

import torch

from .treasury_fixtures import hold_reference
from .treasury_small_diagnostic import FEATURE_NAMES, load_model, read, write_json


def metrics(rows):
    errors = [row['prediction']-row['target'] for row in rows]
    return dict(labels=len(errors), cases=len({row['case'] for row in rows}),
                mae=sum(abs(value) for value in errors)/len(errors),
                rmse=math.sqrt(sum(value*value for value in errors)/len(errors)),
                max_absolute_error=max(abs(value) for value in errors),
                mean_signed_error=sum(errors)/len(errors),
                minimum_signed_error=min(errors), maximum_signed_error=max(errors))


def analyze(output):
    output = Path(output)
    torch.set_num_threads(1)
    identity = read(output/'identity.json')
    frozen = read(output/'frozen-selection.json')
    report = read(output/'report.json')
    model = load_model(output/'selected-model.pt', identity)
    if model.fingerprint() != frozen['model_sha256'] or frozen['identity'] != identity:
        raise ValueError('Saved model does not match the frozen selection')
    # Only these two named files are read. No test rows, tape or labels are used.
    development = {split:read(output/f'rows-{split}.json.gz')
                   for split in ('train', 'validation')}
    saved_cases = read(output/'fixtures.json')
    cases = {case['id']:case for split in development for case in saved_cases[split]}
    predictions = []
    source_rows = []
    for split, rows in development.items():
        estimates = model.predict([row['features'] for row in rows])
        for row, estimate in zip(rows, estimates):
            if row['split'] != split:
                raise ValueError('Saved development split mismatch')
            source_rows.append(row)
            predictions.append({key:row[key] for key in
                                ('split', 'case', 'category', 'kind', 'quantity', 'target')}
                               | dict(prediction=float(estimate),
                                      signed_error=float(estimate)-row['target']))
    grouped = defaultdict(list)
    for row in predictions:
        grouped[(row['split'], row['kind'], row['category'])].append(row)
    grouped_metrics = [dict(split=split, kind=kind, category=category, **metrics(rows))
                       for (split, kind, category), rows in sorted(grouped.items())]
    by_split = {split:metrics([row for row in predictions if row['split']==split])
                for split in development}
    by_kind = [dict(split=split, kind=kind,
                   **metrics([row for row in predictions
                              if row['split']==split and row['kind']==kind]))
               for split in development for kind in ('hold', 'boundary')]
    worst = sorted(predictions, key=lambda row:abs(row['signed_error']), reverse=True)[:12]

    accounting = []
    for row in source_rows:
        reference = hold_reference(cases[row['case']], row['quantity'], row['horizon_ms'],
                                   inventory=row['kind']=='boundary')
        outcome = row['replay']['outcome'] if row['kind']=='hold' else row['replay']
        if not outcome['done']:
            raise ValueError('Incomplete saved replay cannot enter analysis')
        accounting.append(dict(case=row['case'], kind=row['kind'], quantity=row['quantity'],
                               label_error=abs(row['target']-reference['utility']),
                               replay_utility_error=abs(outcome['utility']-reference['utility']),
                               balance_error=max(abs(outcome['balances'][currency]-reference['balances'][currency])
                                                 for currency in ('BTC', 'USD'))))

    def match(split, suffix):
        found = [row for row in development[split] if row['case'].endswith(suffix)
                 and row['category']=='fee_erased' and row['quantity']==60 and row['kind']=='hold']
        if len(found) != 1:
            raise ValueError('Declared matched-economics pair not found exactly once')
        return found[0]

    train_row, validation_row = match('train', '-train-6'), match('validation', '-validation-2')
    train_case, validation_case = cases[train_row['case']], cases[validation_row['case']]
    if (train_case['price'], train_case['fee_bps']) != (99.93, 60.) or (
            validation_case['price'], validation_case['fee_bps']) != (99.93, 60.):
        raise ValueError('Declared economic price/fee pair changed')
    if abs(train_row['target']-validation_row['target']) > 1e-12:
        raise ValueError('Matched pair has unequal complete outcomes')
    swapped = validation_row['features'][:20] + train_row['features'][20:]
    before_hash = model.fingerprint()
    estimates = model.predict([train_row['features'], validation_row['features'], swapped])
    if model.fingerprint() != before_hash:
        raise AssertionError('Feature-sensitivity probe altered model weights')
    base_differences = [dict(feature=FEATURE_NAMES[index], train=train_row['features'][index],
                            validation=validation_row['features'][index],
                            absolute_difference=abs(train_row['features'][index]-validation_row['features'][index]))
                        for index in range(20)
                        if train_row['features'][index] != validation_row['features'][index]]
    sensitivity = dict(scope='Posthoc feature-sensitivity probe only; no policy evaluation, retraining or selection',
                       train_case=train_row['case'], validation_case=validation_row['case'],
                       quantity=60, kind='hold', price=99.93, fee_bps=60.,
                       common_complete_outcome=train_row['target'],
                       base_feature_differences=base_differences,
                       changed_history_features=[FEATURE_NAMES[index] for index in range(20, len(FEATURE_NAMES))
                                                 if train_row['features'][index] != validation_row['features'][index]],
                       train_prediction=float(estimates[0]), validation_prediction=float(estimates[1]),
                       validation_with_train_history_prediction=float(estimates[2]),
                       substitution_prediction_change=float(estimates[2]-estimates[1]),
                       original_validation_absolute_error=abs(float(estimates[1])-validation_row['target']),
                       substituted_validation_absolute_error=abs(float(estimates[2])-validation_row['target']),
                       checkpoint_unchanged=True,
                       interpretation='This matched pair measures sensitivity to the history slots. It does not prove that all validation error is caused by history or establish a better policy.')
    result = dict(schema='treasury-small-saved-development-analysis-v1',
                  analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  model_sha256=model.fingerprint(), selected_updates=frozen['selected_updates'],
                  inputs_read=['rows-train.json.gz', 'rows-validation.json.gz', 'selected-model.pt',
                               'identity.json', 'frozen-selection.json', 'fixtures.json', 'report.json'],
                  analysis_split_scope=['train', 'validation'],
                  training_report_status=report['status'], training_report_test_evaluations=report['test_evaluations'],
                  fresh_test_evaluations_performed=0, optimizer_updates_performed=0,
                  per_split=by_split, per_split_kind=by_kind,
                  per_split_kind_category=grouped_metrics, worst_errors=worst,
                  independent_accounting=dict(labels=len(accounting),
                      maximum_label_error=max(row['label_error'] for row in accounting),
                      maximum_replay_utility_error=max(row['replay_utility_error'] for row in accounting),
                      maximum_balance_error=max(row['balance_error'] for row in accounting)),
                  matched_economics_history_sensitivity=sensitivity)
    write_json(output/'analysis-details.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = analyze(args.output)
    import json
    print(json.dumps({key:result[key] for key in
                      ('per_split', 'independent_accounting', 'matched_economics_history_sensitivity')}, indent=2))
