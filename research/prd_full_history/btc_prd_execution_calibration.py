"""First PRD calibration: unit proxy/inverse-future execution experiments.

Not a funded portfolio replay, capacity estimate or trading recommendation.
Reads hash-verified retained raw data only; no network/exchange operations.
Training constructs the grid; later chronological slices evaluate that frozen
grid. One native $10 contract per independent experiment, never shared capital.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import dataclass
import gzip
import hashlib
import heapq
import itertools
import json
import math
from pathlib import Path
import numpy as np
from btc_prd_band_input_screen import DAY, YEAR, FLAGS, ms, stamp, minus_months

FACE = 10.0
TICK = 2.5


@dataclass(frozen=True, slots=True)
class Trade:
    t: int
    price: float
    index: float
    mark: float
    amount: float
    direction: str
    id: str


def load(root_old, root_new):
    old = json.loads((root_old/'summary.json').read_text())
    new = json.loads((root_new/'specification.json').read_text())
    coverage = json.loads((root_new/'input_coverage.json').read_text())
    groups = []
    for r in old['instruments']:
        groups.append((r['instrument'], ms(r['expiry_utc']),
                       ms(old['config']['start']), ms(old['config']['end_exclusive']),
                       [(root_old/r['raw_path'], r['raw_sha256'])]))
    for symbol, expiry in zip(new['symbols'], new['expiry']):
        files = [(root_new/'inputs'/Path(r['path']).name, r['sha256'])
                 for r in coverage if symbol in r['path']]
        groups.append((symbol, expiry, new['start'], new['end'], files))
    loaded, receipts = [], []
    for symbol, expiry, start, end, files in groups:
        rows, seen, last, counts = [], set(), start-1, Counter()
        for path, digest in sorted(files):
            data = path.read_bytes()
            assert hashlib.sha256(data).hexdigest() == digest, path
            for line in gzip.decompress(data).splitlines():
                r = json.loads(line)
                assert r['instrument_name'] == symbol
                assert start <= r['timestamp'] < end
                assert r['trade_id'] not in seen
                seen.add(r['trade_id'])
                counts['raw'] += 1
                if any(r.get(k) for k in FLAGS):
                    counts['flagged'] += 1
                    continue
                assert r['timestamp'] >= last, 'ordinary timestamp reversal'
                assert min(r['price'], r['index_price'], r['mark_price'], r['amount']) > 0
                assert r['amount'] % FACE == 0
                assert r['direction'] in ('buy', 'sell')
                last = r['timestamp']
                rows.append(Trade(last, r['price'], r['index_price'], r['mark_price'],
                                  r['amount'], r['direction'], str(r['trade_id'])))
            receipts.append(dict(file=path.name, sha256=digest))
        loaded.append(dict(symbol=symbol, expiry=expiry, start=start, end=end,
                           rows=rows, counts=dict(counts)))
    return loaded, receipts


def weighted_quantiles(values, weights, quantiles):
    order = np.argsort(values, kind='stable')
    x, w = np.asarray(values)[order], np.asarray(weights)[order]
    cumulative = np.cumsum(w)
    assert cumulative[-1] > 0
    return [float(x[min(len(x)-1, np.searchsorted(cumulative, q*cumulative[-1]))])
            for q in quantiles]


def distribution(rows, expiry, start, end, delay=500):
    """Exact duration-weighted last observed APR, after observation latency.

    Piecewise observed APR (not interpolation); hold through sparse periods.
    No pre-window seed or sample after end. Equal timestamps get zero duration
    except the final deterministically ordered observation of that timestamp.
    """
    selected = [r for r in rows if start <= r.t < end]
    values, weights, durations = [], [], []
    for i, r in enumerate(selected):
        a = max(start, r.t + delay)
        b = min(end, selected[i+1].t + delay if i+1 < len(selected) else end)
        if b <= a:
            continue
        values.append((r.price/r.index-1)/((expiry-r.t)/YEAR))
        weights.append(b-a)
        durations.append(b-a)
    qs = [.05, .10, .25, .50, .75, .90, .95]
    return dict(quantiles={str(q):v for q,v in zip(qs, weighted_quantiles(values, weights, qs))},
                covered_days=sum(weights)/DAY, max_carried_observation_seconds=max(durations)/1000,
                observations=len(selected)), values, weights


class Experiment:
    """One proxy purchase -> short future -> buyback -> proxy sale at a time.

    Four durable order identities per cycle. A filled identity cannot be revived
    by an in-flight amendment. Notifications/market data arrive after d; commands
    after a further d. At ties: raw tape before command/notification processing.
    This prevents retrospective fills even for d=0. Orders otherwise persist.
    """
    def __init__(self, expiry, start, end, high, low, delay=500, band=.01,
                 participation=.1, fee_bp=1., proxy_expense=0., surcharge=0.,
                 future_fee_bp=None, proxy_fee_bp=None, tick=TICK):
        assert high > low and delay >= 0 and 0 < participation <= 1
        assert 0 <= proxy_expense < 1 and surcharge >= 0
        self.expiry, self.start, self.end = expiry, start, end
        self.high, self.low, self.delay, self.band = high, low, delay, band
        self.participation, self.fee = participation, fee_bp/10000
        self.future_fee = (fee_bp if future_fee_bp is None else future_fee_bp)/10000
        self.proxy_fee = (fee_bp if proxy_fee_bp is None else proxy_fee_bp)/10000
        assert tick > 0
        self.tick = tick
        self.expense, self.surcharge = proxy_expense, surcharge
        self.proxy_apr = proxy_expense/(1-proxy_expense)+surcharge
        self.cutoff = minus_months(expiry, 3)
        self.phase, self.cycle = 0, 0
        self.active = None
        self.queue, self.serial = [], 0
        self.known_key, self.last_signature = (0, 0), None
        self.latest, self.proxy, self.entry = None, 0., None
        self.proxy_cost, self.proxy_bought = 0., None
        self.cycle_cash, self.cash = 0., 0.
        self.last_accrual, self.last_index = start, None
        self.fills, self.cycles, self.counts = [], [], Counter()
        self.proxy_hours = self.short_hours = self.pending_short_hours = 0.
        self.final_cycle_net = 0.
        self.cycle_future_realized = self.cycle_fees = 0.
        self.proxy_original = 0.

    def enqueue(self, t, kind, payload):
        self.serial += 1
        heapq.heappush(self.queue, (t, self.serial, kind, payload))

    def accrue(self, t):
        dt = (t-self.last_accrual)/YEAR
        if self.proxy:
            self.proxy_hours += (t-self.last_accrual)/3600000
            if self.entry is None:
                self.pending_short_hours += (t-self.last_accrual)/3600000
            # Synthetic share decay for annual expense; surcharge is explicitly
            # a modeled continuous liquidity cost, not a claimed actual margin fee.
            self.proxy *= (1-self.expense)**dt * math.exp(-self.surcharge*dt)
        if self.entry is not None:
            self.short_hours += (t-self.last_accrual)/3600000
        self.last_accrual = t

    def decision(self, t, row, observed_key):
        self.latest, self.known_key = row, observed_key
        cycle, phase = observed_key
        limit = None
        if phase in (0, 1) and t >= self.cutoff:
            signature = (observed_key, None)
        elif phase in (0, 3):
            signature = (observed_key, 'proxy')
        else:
            rate = self.proxy_apr + (self.high if phase == 1 else self.low)
            price = row.index * (1+(self.expiry-t)/YEAR*rate)
            limit = ((math.ceil(price/self.tick-1e-12) if phase == 1 else
                      math.floor(price/self.tick+1e-12))*self.tick)
            distance = max(0., (limit-row.price)/row.price if phase == 1 else
                           (row.price-limit)/row.price)
            if self.band is not None and distance > self.band:
                limit = None
                self.counts['outside_band_decisions'] += 1
            signature = (observed_key, limit)
        if signature != self.last_signature:
            self.last_signature = signature
            self.enqueue(t+self.delay, 'command',
                         dict(key=observed_key, limit=signature[1], decision=t,
                              observed=row.t, arrival=t+self.delay))
            self.counts['commands'] += 1

    def process(self, t, inclusive=False):
        while self.queue and (self.queue[0][0] <= t if inclusive else self.queue[0][0] < t):
            when, _, kind, payload = heapq.heappop(self.queue)
            if kind == 'observe':
                row, key = payload
                self.decision(when, row, key)
            else:
                if payload['key'] != (self.cycle, self.phase):
                    self.counts['obsolete_completed_order_commands'] += 1
                    continue
                self.active = payload if payload['limit'] is not None else None

    def fill(self, row):
        q = self.active
        if q is None or q['arrival'] >= row.t:
            return
        phase = self.phase
        if phase in (0, 1) and row.t >= self.cutoff:
            return
        if phase in (1, 2):
            # One print budget and one possible native contract in this independent
            # experiment. No division by trade frequency or recycling one print.
            if math.floor(row.amount/FACE*self.participation+1e-12) < 1:
                return
            if row.direction != ('buy' if phase == 1 else 'sell'):
                return
            if not (row.price > q['limit'] if phase == 1 else row.price < q['limit']):
                return
            price = q['limit']
        else:
            price = row.index  # first suitable post-arrival index; synthetic proxy
        self.accrue(row.t)
        fee = (FACE/price*row.index if phase in (1, 2) else
               FACE if phase == 0 else self.proxy*price) * (self.future_fee if phase in (1, 2) else self.proxy_fee)
        cash = -fee
        if phase == 0:
            self.proxy = FACE/price
            self.proxy_cost = FACE
            self.proxy_original = self.proxy
            self.proxy_bought = row.t
            cash -= FACE
        elif phase == 1:
            self.entry = price
        elif phase == 2:
            # Native BTC P&L of one inverse short; converted at the fill-time
            # index as an explicit normalization, no funded collateral claim.
            realized = FACE*(1/price-1/self.entry)*row.index
            cash += realized
            self.cycle_future_realized += realized
            self.entry = None
        else:
            proxy_parts = self.proxy_components(price, row.t)
            cash += self.proxy*price
            self.proxy = 0.
        self.cycle_fees += fee
        self.cash += cash
        self.cycle_cash += cash
        self.fills.append(dict(cycle=self.cycle, phase=phase, t=row.t, trade_id=row.id,
                               price=price, index=row.index, observed=q['observed'],
                               decision=q['decision'], arrival=q['arrival'], fee_usd=fee,
                               cash_usd=cash, future_apr=(price/row.index-1)/((self.expiry-row.t)/YEAR)
                               if phase in (1, 2) else self.proxy_apr))
        self.counts[['proxy_buys','short_entries','short_exits','proxy_sales'][phase]] += 1
        self.active = None
        if phase == 3:
            self.cycles.append(dict(cycle=self.cycle, start=self.proxy_bought, end=row.t,
                                    net_usd=self.cycle_cash,
                                    future_realized_usd=self.cycle_future_realized,
                                    fees_usd=self.cycle_fees, **proxy_parts,
                                    duration_days=(row.t-self.proxy_bought)/DAY))
            self.cycle += 1
            self.phase = 0
            self.cycle_cash = 0.
            self.cycle_future_realized = self.cycle_fees = 0.
            self.proxy_original = 0.
        else:
            self.phase += 1

    def proxy_components(self, index, t):
        if not self.proxy_original:
            return dict(proxy_price_gain_usd=0., proxy_expense_effect_usd=0.,
                        proxy_surcharge_effect_usd=0.)
        expense_only = self.proxy_original*(1-self.expense)**((t-self.proxy_bought)/YEAR)
        return dict(proxy_price_gain_usd=self.proxy_original*index-self.proxy_cost,
                    proxy_expense_effect_usd=(expense_only-self.proxy_original)*index,
                    proxy_surcharge_effect_usd=(self.proxy-expense_only)*index)

    def run(self, rows):
        selected = [r for r in rows if self.start <= r.t < self.end]
        for t, group in itertools.groupby(selected, key=lambda r:r.t):
            self.process(t)
            group = list(group)
            for row in group:
                self.fill(row)
                self.last_index = row.index
            # Batch notification prevents same-time tape reacting to earlier
            # records at the same timestamp, even when delay=0.
            self.enqueue(t+self.delay, 'observe', (group[-1], (self.cycle, self.phase)))
            self.process(t, inclusive=True)
        self.accrue(self.end)
        last = selected[-1]
        residual = self.proxy*last.index
        if self.entry is not None:
            residual += FACE*(1/last.mark-1/self.entry)*last.index
        net = self.cash + residual
        # Identity includes every completed cycle and the unfinished cycle mark.
        self.final_cycle_net = self.cycle_cash + residual
        assert abs(net-sum(c['net_usd'] for c in self.cycles)-self.final_cycle_net) < 1e-8
        ages = [(x['t']-x['observed'])/1000 for x in self.fills if x['phase'] in (1,2)]
        entries = [x['future_apr']-self.proxy_apr for x in self.fills if x['phase']==1]
        exits = [x['future_apr']-self.proxy_apr for x in self.fills if x['phase']==2]
        fees = sum(x['fee_usd'] for x in self.fills)
        open_proxy = self.proxy_components(last.index, self.end)
        open_future = FACE*(1/last.mark-1/self.entry)*last.index if self.entry is not None else 0.
        unrealized = sum(open_proxy.values()) + open_future
        completed = sum(c['net_usd'] for c in self.cycles)
        unfinished_realized = self.cycle_future_realized-self.cycle_fees
        assert abs(net-completed-unfinished_realized-unrealized) < 1e-8
        pnl = dict(completed_cycle_realized_net_usd=completed,
                   unfinished_cycle_realized_net_usd=unfinished_realized,
                   unrealized_mark_net_usd=unrealized,
                   unrealized_future_usd=open_future,
                   **{'unrealized_'+k:v for k,v in open_proxy.items()},
                   completed_cycle_future_realized_usd=sum(c['future_realized_usd'] for c in self.cycles),
                   unfinished_cycle_future_realized_usd=self.cycle_future_realized,
                   completed_cycle_fees_usd=sum(c['fees_usd'] for c in self.cycles),
                   unfinished_cycle_fees_usd=self.cycle_fees,
                   **{'completed_cycle_'+k:sum(c[k] for c in self.cycles) for k in open_proxy})
        return dict(high=self.high, low=self.low, gap=self.high-self.low,
                    delay_ms_each=self.delay, posting_band=self.band, participation=self.participation,
                    fee_bp_each_leg=self.fee*10000 if self.future_fee == self.proxy_fee == self.fee else None,
                    future_fee_bp=self.future_fee*10000, proxy_fee_bp=self.proxy_fee*10000,
                    tick_usd=self.tick, proxy_expense=self.expense, **pnl,
                    proxy_liquidity_surcharge=self.surcharge, **dict(self.counts),
                    completed_cycles=len(self.cycles), net_marked_usd_per_10_face=net,
                    total_transaction_fees_usd=fees,
                    marked_before_transaction_fees_usd=net+fees,
                    actual_entry_prd_mean=float(np.mean(entries)) if entries else None,
                    actual_exit_prd_mean=float(np.mean(exits)) if exits else None,
                    entries_below_target=sum(x < self.high-1e-12 for x in entries),
                    exits_above_target=sum(x > self.low+1e-12 for x in exits),
                    completed_net_usd=sum(c['net_usd'] for c in self.cycles),
                    unfinished_net_marked_usd=self.final_cycle_net,
                    unfinished_phase=self.phase, remaining_proxy_btc=self.proxy,
                    remaining_short_face=FACE if self.entry is not None else 0.,
                    short_hours=self.short_hours, proxy_hours=self.proxy_hours,
                    proxy_without_short_hours=self.pending_short_hours,
                    median_completed_days=float(np.median([c['duration_days'] for c in self.cycles]))
                    if self.cycles else None,
                    max_fill_reference_age_seconds=max(ages) if ages else None,
                    final_index=last.index, final_mark=last.mark,
                    final_observation_age_seconds=(self.end-last.t)/1000)


def run_all(args):
    groups, receipts = load(args.sep_dec, args.dec_mar)
    split = ms('2026-07-21T00:00:00Z')
    distributions, samples, pooled_v, pooled_w = [], [], [], []
    for g in groups:
        spans = [('train',g['start'],g['end'])] if g['end'] <= ms('2026-06-06T00:00:00Z') else [
            ('validation', g['start'], split), ('test', split, g['end'])]
        for phase, start, end in spans:
            d, values, weights = distribution(g['rows'],g['expiry'],start,end)
            distributions.append(dict(symbol=g['symbol'],phase=phase,start=stamp(start),end=stamp(end),**d))
            samples.append((g,phase,start,end))
            if phase == 'train':
                pooled_v.extend(values); pooled_w.extend(weights)
    # Predeclared coarse grid. Do not use later samples to derive levels.
    quantiles = weighted_quantiles(pooled_v, pooled_w, [.10,.25,.50,.75])
    locations = sorted(set(round(x/.0025)*.0025 for x in quantiles))
    candidates = sorted(set([(round(l+w,8),round(l,8)) for l in locations
                             for w in [.0025,.005,.01]] + [(.02,.01)]))
    config = dict(training_end='2026-06-06T00:00:00+00:00', validation_end=stamp(split),
                  test_end='2026-09-04T00:00:00+00:00', train_quantiles=quantiles,
                  location_rounding=.0025, gaps=[.0025,.005,.01],
                  candidates=[dict(high=h,low=l) for h,l in candidates],
                  selection='No winner selected: execution diagnostics only, not funded optimization',
                  default=dict(delay_ms_each=500,posting_band=.01,participation=.1,fee_bp_each_leg=1,
                               proxy_expense=0,proxy_liquidity_surcharge=0),
                  face_usd=FACE, tick_usd=TICK)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'btc-prd-calibration-config.json').write_text(json.dumps(config,indent=2)+'\n')
    runs, audit = [], []
    for g,phase,start,end in samples:
        for h,l in candidates:
            experiment = Experiment(g['expiry'],start,end,h,l)
            result = experiment.run(g['rows'])
            result.update(symbol=g['symbol'],phase=phase,start=stamp(start),end=stamp(end),scenario='base')
            runs.append(result)
            for f in experiment.fills:
                audit.append(dict(symbol=g['symbol'],sample=phase,high=h,low=l,scenario='base',**f))
        print(json.dumps(dict(phase=phase,symbol=g['symbol'],runs=len(candidates))),flush=True)
    # Diagnostics on the entire already-frozen grid; no cherry-picked sensitivity winner.
    stresses = [('always_posted',dict(band=None)),('two_second_delays',dict(delay=2000)),
                ('five_bp_fees',dict(fee_bp=5)),
                ('no_fees',dict(fee_bp=0)),
                ('maker_rebate',dict(future_fee_bp=-1,proxy_fee_bp=0)),
                ('one_ms_delays',dict(delay=1)),
                ('proxy_cost',dict(proxy_expense=.0025,surcharge=.005)),
                ('one_percent_participation',dict(participation=.01))]
    for scenario, kwargs in stresses:
        for g,phase,start,end in samples:
            if phase == 'train':
                continue
            for h,l in candidates:
                experiment = Experiment(g['expiry'],start,end,h,l,**kwargs)
                result = experiment.run(g['rows'])
                result.update(symbol=g['symbol'],phase=phase,start=stamp(start),end=stamp(end),scenario=scenario)
                runs.append(result)
                for f in experiment.fills:
                    audit.append(dict(symbol=g['symbol'],sample=phase,high=h,low=l,scenario=scenario,**f))
        print(json.dumps(dict(sensitivity=scenario)),flush=True)
    report = dict(status='unit_execution_calibration_not_funded_portfolio',config=config,
                  source_counts=[{k:v for k,v in g.items() if k!='rows'} for g in groups],
                  source_hashes=receipts,distributions=distributions,runs=runs,
                  source_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (args.output/'btc-prd-execution-calibration.json').write_text(json.dumps(report,indent=2)+'\n')
    # Deterministic gzip keeps the full execution audit small and reproducible.
    data=''.join(json.dumps(x,separators=(',',':'))+'\n' for x in audit).encode()
    (args.output/'btc-prd-calibration-fills.jsonl.gz').write_bytes(gzip.compress(data,mtime=0))
    print(json.dumps(dict(runs=len(runs),fills=len(audit),candidates=len(candidates))),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sep-dec',required=True,type=Path)
    parser.add_argument('--dec-mar',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    run_all(parser.parse_args())
