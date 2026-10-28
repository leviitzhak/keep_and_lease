"""Config-driven, one-campaign Treasury max-min experiment (no network access).

Run: python -m research.post_decision_value.treasury_learning run --output NEW_DIR
Replot/verify use saved outcomes and never train or inspect another test set.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch

from .decision_clock import DecisionSchedule
from .engine import Instruction, Order
from .liquidation import ClosingRule, liquidate
from .model import ValueNetwork, action_features, batch
from .pilot import code_identity, write_json
from .robust_rollout import CampaignBudget, Controller, TARGET_VERSION, collect_post_state, digest, rollout
from .treasury_fixtures import DAY, accept_anchor, action_provider, finite_toy_optimum, fixture_engine, hold_reference, make_cases, scenario_set, replay_reference
from .treasury_model import DIAGNOSTIC_VERSION, FEATURE_NAMES, FEATURE_VERSION, TreasuryValue, encode, error, fit_scalar, load_scalar, save_scalar

DEFAULT_CONFIG = Path(__file__).with_name('treasury_learning_config.json')


def read(path):
    p = Path(path)
    return json.loads(gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_text())


def validate_config(config):
    if config['schema']!='treasury-maxmin-campaign-v1': raise ValueError('Unknown campaign schema')
    if config['objective'] != dict(BTC=.5,USD=.5,**{'lambda':10},failure_penalty=1,drawdown=.1):
        raise ValueError('This experiment fixes the agreed objective and floors')
    if config['price_offsets'] != [0] or config['inventory_cap'] != 60 or config['quantities'] != [5,25,60]:
        raise ValueError('Changed action domain needs a new independent reference/version')
    if set(config['scenario_seeds']) & set(config['audit_seeds']):
        raise ValueError('Winner audit must use independent uncertainty seeds')
    if not config['controllers'] or not config['scenario_seeds'] or not config['audit_seeds']:
        raise ValueError('Nonempty J, K and independent audit required')
    if config['diagnosis_updates']+sum(config['cycle_updates'])>config['limits']['updates']:
        raise ValueError('Aggregate optimizer schedule exceeds cap')
    if len(config['cycle_updates']) != 2:
        raise ValueError('Initial campaign has exactly one collect/refit and one recollect/refit')
    if any(c['count'] < 4 or c['count'] % 4 for c in config['splits'].values()):
        raise ValueError('Balanced four-category fixture groups required')
    # Oracle assumes every prescribed action can arrive before the next sparse
    # fill and all reports arrive before the following opportunity.
    d=config['delays']
    if (d['decision']+d['delivery']+d['report'])*(1+d['jitter'])*(1+d['congestion'])>=1000:
        raise ValueError('Delay law outside finite-toy reference support')


def diagnosis_rows(cases, config, budget):
    rows = []
    actions = action_provider(config)
    for case in cases:
        base = fixture_engine(case, config)
        candidates, _ = actions(base.observe(), base.goal, base.instruments)
        scenario = scenario_set(case, [311], config, 'diagnostic')[0]
        for action in candidates:
            if action.kind not in ('wait', 'create'):
                continue
            q = sum(o.quantity for o in action.orders)
            e = accept_anchor(deepcopy(base), action, config)
            h = case['decision_end']-e.now
            result = rollout(e, h, scenario, Controller(0), None, encode, actions,
                             config, budget, hold=True)
            reference = hold_reference(case, q, h)
            if not result['outcome']['done'] or abs(result['outcome']['utility']-reference['utility']) > config['acceptance']['accounting_atol']:
                raise AssertionError('Independent maturity accounting mismatch')
            rows.append(dict(case=case['id'], category=case['category'], quantity=q, kind='hold',
                             horizon_ms=h, features=encode(e.observe(), Instruction(), e.goal, e.instruments, h),
                             done=True, target=result['outcome']['utility'], target_version=DIAGNOSTIC_VERSION,
                             identity='training-diagnostic-hold-boundary-v1', reference=reference,
                             replay={k:v for k,v in result.items() if k not in ('engine','anchors')}))
            # Owned inventory boundary is economically different from a newly
            # submitted instruction, which is atomically cancelled at H=0.
            owned = deepcopy(e)
            owned.add_tape(scenario['trades'])
            owned.advance(case['start']+DAY+1000)
            budget.event(owned.hidden.processed)
            boundary = liquidate(owned, scenario['trades'], scenario['label_end'], ClosingRule(**config['closing']), budget)
            reference = hold_reference(case, q, 0, inventory=True)
            if not boundary['done'] or abs(boundary['utility']-reference['utility']) > config['acceptance']['accounting_atol']:
                raise AssertionError('Independent boundary accounting mismatch')
            rows.append(dict(case=case['id'], category=case['category'], quantity=q, kind='boundary',
                             horizon_ms=0, features=encode(owned.observe(), Instruction(), owned.goal, owned.instruments, 0),
                             done=True, target=boundary['utility'], target_version=DIAGNOSTIC_VERSION,
                             identity='training-diagnostic-hold-boundary-v1', reference=reference, replay=boundary))
    return rows


def diagnosis_gates(model, rows, config):
    prediction = model.predict([r['features'] for r in rows])
    choices = []
    for case in sorted({r['case'] for r in rows}):
        indices = [i for i, r in enumerate(rows) if r['case']==case and r['kind']=='hold']
        best = max(prediction[i] for i in indices)
        selected = next(i for i in indices if prediction[i] >= best-config['tie_margin'])
        optimum = max(rows[i]['target'] for i in indices)
        choices.append(dict(case=case, category=rows[selected]['category'], quantity=rows[selected]['quantity'],
                            utility=rows[selected]['target'], optimal=optimum,
                            correct=abs(rows[selected]['target']-optimum)<=config['acceptance']['quantity_atol']))
    return dict(passed=all(c['correct'] for c in choices) and error(model,rows)['max_error']<=config['acceptance']['diagnosis_max_error'],
                choices=choices, errors=error(model,rows))


def collect_cases(cases, config, budget, model, output=None, stage=0):
    controllers = [Controller(**c) for c in config['controllers']]
    actions = action_provider(config)
    identity = digest(dict(model=model.fingerprint(), configuration=config,
                           target=TARGET_VERSION, stage=stage))
    rows = []
    for case in cases:
        budget.check()
        base = fixture_engine(case, config)
        scenarios = scenario_set(case, config['scenario_seeds'], config, 'search')
        audits = scenario_set(case, config['audit_seeds'], config, 'winner-audit')
        # Initial candidate post-states plus predeclared subsampled states from
        # one outer network trajectory. Inner branches never invoke collection.
        candidates, _ = actions(base.observe(), base.goal, base.instruments)
        parents = [(accept_anchor(deepcopy(base), a, config), 'initial', a.payload()) for a in candidates]
        outer = rollout(base, case['decision_end']-base.now, scenarios[0], Controller(401,.2),
                        model, encode, actions, config, budget, retain_anchors=True)
        for index in config['anchor_indices']:
            if index < len(outer['anchors']):
                parents.append((outer['anchors'][index], f'outer-{index}', outer['decisions'][index]['instruction']))
        for parent, origin, action in parents:
            sampled = collect_post_state(parent, config['horizons_ms'], scenarios, audits, controllers,
                                         model, encode, actions, config, budget, identity)
            for row in sampled:
                row.update(case=case['id'], category=case['category'], origin=origin, instruction=action)
                audit_references(case,row,config)
            rows.extend(sampled)
        if output:
            write_json(output, rows)  # completed work survives an aggregate cap
    return rows


def audit_references(case, row, config):
    if not row['done']: return
    matrix=[]
    for branches in row['branches']:
        values=[]
        for branch in branches:
            ref=replay_reference(case,branch)
            if abs(ref['utility']-branch['outcome']['utility'])>config['acceptance']['accounting_atol']:
                raise AssertionError('Independent sampled-controller accounting mismatch')
            branch['independent_reference']=ref
            values.append(ref['utility'])
        matrix.append(values)
    row['independent_target']=max(min(r) for r in matrix)
    if abs(row['independent_target']-row['target'])>config['acceptance']['accounting_atol']:
        raise AssertionError('Independent max-min reduction mismatch')


def evaluate(cases, config, budget, model):
    """Execute causal policy first. Offline references/search never choose actions."""
    actions = action_provider(config)
    results = []
    for case in cases:
        base = fixture_engine(case, config)
        h = case['decision_end']-base.now
        scenarios = scenario_set(case, config['audit_seeds']+[229], config, 'heldout-policy')
        policy = []
        for s in scenarios:
            r = rollout(base, h, s, Controller(0), model, encode, actions, config, budget)
            r.pop('engine'); r.pop('anchors'); policy.append(r)
        oracle = finite_toy_optimum(case,h,config,budget)
        candidates, _ = actions(base.observe(),base.goal,base.instruments)
        search = []
        for action in candidates:
            parent = accept_anchor(deepcopy(base),action,config)
            labels = collect_post_state(parent,[h],scenario_set(case,config['scenario_seeds'],config,'search'),
                       scenario_set(case,config['audit_seeds'],config,'winner-audit'),
                       [Controller(**c) for c in config['controllers']],model,encode,actions,config,budget,
                       digest(dict(model=model.fingerprint(),target=TARGET_VERSION,config=config)))
            labels[0]['instruction']=action.payload()
            audit_references(case,labels[0],config)
            labels[0]['prediction']=float(model.predict([labels[0]['features']])[0])
            search.extend(labels)
        complete = all(p['outcome']['done'] for p in policy) and all(r['done'] for r in search)
        outcomes = [p['outcome'] for p in policy]
        utilities = [o['utility'] for o in outcomes] if complete else []
        robust_search = max(r['target'] for r in search) if complete else None
        purchased = [sum(max(0.,f['quantity']) for f in p['fills']) for p in policy]
        expected_q = oracle['witness']['quantity']
        results.append(dict(case=case['id'],category=case['category'],done=complete,
                            cash_hold=0.,analytical_bill_hold=hold_reference(case,60,h) if case['category']!='cash_constrained' else None,
                            policy=policy, search=search, toy_optimum=oracle,
                            mean=float(np.mean(utilities)) if utilities else None,
                            minimum=min(utilities) if utilities else None,
                            p10=float(np.quantile(utilities,.1)) if utilities else None,
                            search_value=robust_search,
                            search_oracle_gap=oracle['value']-robust_search if complete else None,
                            policy_gap=oracle['value']-min(utilities) if complete else None,
                            search_policy_gap=robust_search-min(utilities) if complete else None,
                            bought_quantities=purchased,
                            correct_quantity=all(abs(q-expected_q)<=config['acceptance']['quantity_atol'] for q in purchased),
                            growth=[o.get('growth') for o in outcomes],failures=sum(o.get('failed',True) for o in outcomes),
                            fees=[o.get('fees') for o in outcomes],
                            turnover=[sum(abs(f['quantity']*f['price']) for f in p['fills']) for p in policy]))
    errors = [abs(r['prediction']-r['target']) for c in results if c['done'] for r in c['search']]
    a = config['acceptance']
    profitable = [r for r in results if r['category']=='profitable']
    losses = [r for r in results if r['category'] in ('overpriced','fee_erased')]
    gates = dict(complete=all(r['done'] for r in results),
                 profitable=sum(r['correct_quantity'] for r in profitable)/max(1,len(profitable))>=a['profitable_accuracy'],
                 loss_avoidance=sum(all(q==0 for q in r['bought_quantities']) for r in losses)/max(1,len(losses))>=a['loss_avoidance'],
                 constraints=sum(r['failures'] for r in results)<=a['constraint_failures'],
                 quantities=all(r['correct_quantity'] for r in results),
                 value_mae=bool(errors) and float(np.mean(errors))<=a['value_mae'],
                 policy_gap=all(r['done'] for r in results) and float(np.mean([r['policy_gap'] for r in results]))<=a['mean_policy_gap'],
                 search_gap=all(r['done'] for r in results) and max(r['search_oracle_gap'] for r in results)<=a['max_search_oracle_gap'])
    return dict(passed=all(gates.values()),gates=gates,cases=results,
                prediction_mae=float(np.mean(errors)) if errors else None)


def run(output, config_path=DEFAULT_CONFIG):
    config=read(config_path)
    validate_config(config)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1);torch.manual_seed(config['seed'])
    budget=CampaignBudget(config['limits'])
    cases={s:make_cases(s,config) for s in config['splits']}
    splits=[cases[s] for s in ('train','validation','test')]
    if any(max(c['label_end'] for c in left)>=min(c['start'] for c in right) for left,right in zip(splits,splits[1:])):
        raise ValueError('Overlapping split allocations including closing buffers')
    # Freeze all settings and exact fixture specifications before any fitting or
    # reading held-out outcomes. Do not build test tape/labels until final selection.
    identity=dict(**code_identity(),configuration_sha256=digest(config),fixtures_sha256=digest(cases),
                  target_version=TARGET_VERSION,feature_version=FEATURE_VERSION)
    write_json(output/'configuration.json',config);write_json(output/'identity.json',identity)
    write_json(output/'fixtures.json',cases)
    write_json(output/'splits.json',{s:[{k:c[k] for k in ('id','start','decision_end','label_end')} for c in cs] for s,cs in cases.items()})
    environment=dict(hostname=platform.node(),platform=platform.platform(),python=platform.python_version(),
                     torch=torch.__version__,numpy=np.__version__,device='cpu',threads=torch.get_num_threads(),
                     cpu=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),platform.processor()),
                     memory_total_kb=int(Path('/proc/meminfo').read_text().split('MemTotal:')[1].split()[0]),
                     thread_environment={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')})
    write_json(output/'environment.json',environment)
    report=dict(identity=identity,source_kind='synthetic_fixture',passed=False,
                stages={'0':'implemented','1':'pending','2':'pending','3':'implemented','4':'implemented','5':'pending','6':'pending'},
                limitations=['Tiny synthetic Treasury only; no historical profitability evidence.',
                             'K reseeds future execution delays on one fixed tape; it does not sample market movements.',
                             'Exact oracle covers the declared constant-price two-purchase toy only.',
                             'Liquidation assumes atomic cancellation and print-price closing with declared participation.',
                             'Treasury payments remain contractual projections; closing duration is ignored.',
                             'Scalar inputs/model support one BILL and the frozen objective, not the general legacy instrument universe.'])
    model=TreasuryValue(**config['architecture']);optimizer=None
    curve=[]
    try:
        train=diagnosis_rows(cases['train'],config,budget)
        validation=diagnosis_rows(cases['validation'],config,budget)
        write_json(output/'diagnosis-train.json.gz',train);write_json(output/'diagnosis-validation.json.gz',validation)
        report['stages']['1']='implemented'
        # Inspect legacy feature magnitudes without fitting another network.
        e=fixture_engine(cases['train'][0],config);e.advance(cases['train'][0]['maturity']-DAY)
        old=action_features(e.observe(),Instruction(),e.goal,e.instruments)
        raw=np.array([v for row in old['history'] for v in row])
        diagnostics=dict(legacy_max_history_abs=float(abs(raw).max()),
                         legacy_max_global_abs=max(abs(v) for v in old['global_']),
                         new_feature_names=FEATURE_NAMES,architecture='two hidden SiLU layers, one scalar',
                         parameters=sum(p.numel() for p in model.parameters()),
                         target='complete outcome scalar only; no auxiliary loss imbalance',
                         normalization='training-only feature and label moments; constant feature scale=1')
        def checkpoint(m,opt,point):
            save_scalar(output/'last-model.pt',m,opt,identity)
        optimizer,diag_curve,best=fit_scalar(model,train,validation,config['diagnosis_updates'],budget,callback=checkpoint)
        curve.extend([dict(stage='diagnosis',**p) for p in diag_curve])
        # Tiny train gate is assessed at the training endpoint; validation selects
        # the later stages, never the fresh test. Preserve both diagnostics.
        diagnostics.update(train=diagnosis_gates(model,train,config),validation=diagnosis_gates(model,validation,config),
                           x_mean=model.x_mean.tolist(),x_scale=model.x_scale.tolist(),
                           y_mean=float(model.y_mean),y_scale=float(model.y_scale))
        write_json(output/'diagnosis.json',diagnostics);write_json(output/'learning-curve.json',curve)
        save_scalar(output/'diagnosis-model.pt',model,optimizer,identity)
        if not diagnostics['train']['passed']:
            report['stages']['2']='failed';report['stages']['5']='blocked_by_diagnostic_gate'
            report['reason']='Frozen tiny training-control gate failed; no retry or fresh-test inspection.'
            save_scalar(output/'selected-model.pt',model,optimizer,identity)
        else:
            report['stages']['2']='implemented'
            for stage,updates in enumerate(config['cycle_updates']):
                budget.check()
                frozen=deepcopy(model);frozen.eval()
                tr=collect_cases(cases['train'],config,budget,frozen,output/f'train-{stage}.json.gz',stage)
                va=collect_cases(cases['validation'],config,budget,frozen,output/f'validation-{stage}.json.gz',stage)
                incomplete=[r for r in tr+va if not r['done'] and r.get('reason')!='unsupported_horizon']
                if incomplete: raise RuntimeError('Incomplete supported replica; cycle not fitted')
                eligible_tr=[r for r in tr if r['done']];eligible_va=[r for r in va if r['done']]
                # No silent mixing of previous continuation datasets. Warm start
                # weights; fresh optimizer and train-only normalization per stage.
                optimizer,points,best=fit_scalar(model,eligible_tr,eligible_va,updates,budget,callback=checkpoint)
                curve.extend([dict(stage=f'cycle-{stage}',**p) for p in points])
                write_json(output/'learning-curve.json',curve)
                save_scalar(output/f'last-stage-{stage}.pt',model,optimizer,identity)
                model.load_state_dict(best['state'])
                optimizer.load_state_dict(best['optimizer'])
                torch.set_rng_state(best['torch_rng'])
                save_scalar(output/f'selected-stage-{stage}.pt',model,optimizer,identity)
                report[f'cycle_{stage}']=dict(continuation_model=frozen.fingerprint(),label_identity=eligible_tr[0]['identity'],
                    training_samples=len(eligible_tr),validation_samples=len(eligible_va),
                    unsupported=sum(not r['done'] for r in tr+va),incomplete=len(incomplete),
                    selected_updates=best['updates'],selected_validation_error=error(model,eligible_va))
            save_scalar(output/'selected-model.pt',model,optimizer,identity)
            write_json(output/'frozen-selection.json',dict(model_sha256=model.fingerprint(),identity=identity,
                        test_evaluations=0,selection=config['selection']))
            # The only fresh held-out pass; this call never refits or selects.
            evaluation=evaluate(cases['test'],config,budget,model)
            write_json(output/'test-evaluation.json.gz',evaluation)
            report.update(passed=evaluation['passed'],gates=evaluation['gates'],
                          prediction_mae=evaluation['prediction_mae'],test_evaluations=1)
            report['stages']['5']='implemented' if evaluation['passed'] else 'failed_learning_acceptance'
    except (RuntimeError,AssertionError) as exc:
        report['reason']=str(exc);report['stages']['5']='blocked_or_capped'
        save_scalar(output/'selected-model.pt',model,optimizer,identity)
    report['resources']=budget.summary()
    report['resources']['peak_rss_kb']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report['parameters']=sum(p.numel() for p in model.parameters())
    report['checkpoint_target_version']=model.target_version
    report['checkpoint_label_identity']=model.label_identity
    report['stages']['6']='local_artifacts_pending_publication'
    write_json(output/'learning-curve.json',curve);write_json(output/'report.json',report)
    # Inference/restoration examples require no fresh labels or policy selection.
    examples=read(output/'diagnosis-train.json.gz')[:4] if (output/'diagnosis-train.json.gz').exists() else []
    fs=[r['features'] for r in examples]
    restored,_,_=load_scalar(output/'selected-model.pt',identity)
    np.testing.assert_array_equal(model.predict(fs),restored.predict(fs))
    write_json(output/'inference-examples.json',dict(features=fs,predictions=restored.predict(fs).tolist(),
                reference=[r['target'] for r in examples],reference_scope='diagnostic hold/boundary, not new continuation calibration'))
    print(json.dumps(report,indent=2),flush=True)
    return report


def verify(output):
    output=Path(output);identity=read(output/'identity.json')
    model,_,_=load_scalar(output/'selected-model.pt',identity)
    examples=read(output/'inference-examples.json')
    np.testing.assert_allclose(model.predict(examples['features']),examples['predictions'],rtol=0,atol=1e-8)
    config=read(output/'configuration.json')
    if digest(config)!=identity['configuration_sha256']:raise ValueError('Configuration hash mismatch')
    cases={c['id']:c for cs in read(output/'fixtures.json').values() for c in cs}
    for row in read(output/'diagnosis-train.json.gz'):
        calculated=hold_reference(cases[row['case']],row['quantity'],row['horizon_ms'],inventory=row['kind']=='boundary')
        if abs(row['target']-calculated['utility'])>config['acceptance']['accounting_atol']:
            raise ValueError('Saved independent reference mismatch')
    print(json.dumps(dict(verified=True,model=model.fingerprint(),examples=len(examples['features']))))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=('run','verify','plots'))
    p.add_argument('--output',required=True);p.add_argument('--config',default=str(DEFAULT_CONFIG))
    a=p.parse_args()
    if a.command=='run':run(a.output,a.config)
    elif a.command=='verify':verify(a.output)
    else:
        from .treasury_plots import render
        render(a.output)


if __name__=='__main__':main()
