"""Opt-in synthetic trade paths for the existing native event engine.

No calibration, fitting, network access or historical-data substitution occurs.
Rates price bills; idle USD never earns automatic interest. Dated funding pays
on the actual futures inventory at the event, in its native currency.
"""
import argparse
from dataclasses import asdict, dataclass, field
import gzip
import hashlib
import json
import math
from pathlib import Path
import random

from .accounting import Instrument
from .engine import Trade

DAY = 86400000
VERSION = 'synthetic-market-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SimulationConfig:
    enabled: bool = False
    seed: int = 280126
    start: int = 1767225610000
    days: int = 28
    step_hours: int = 6
    tail_days: int = 2
    universe: str = 'treasury'
    trend: str = 'flat'
    trend_annual: float = .20
    volatility_annual: float = .20
    initial_spot: float = 100000.
    rate_annual: float = .04
    rate_volatility: float = .005
    premium_annual: float = -.04
    premium_volatility: float = .02
    mean_reversion: float = 8.
    spread_bps: float = 4.
    liquidity: float = 1.
    funding_daily_bps: float = 0.
    fee_bps: float = 5.
    future_payoff: str = 'linear'
    maturity_days: int = 28
    future_expiry_days: int = 35
    row_cap: int = 10000

    def __post_init__(self):
        if type(self.enabled) is not bool: raise ValueError('enabled must be boolean')
        if self.universe not in ('treasury','full') or self.trend not in ('up','flat','down'):
            raise ValueError('Unknown universe or spot regime')
        if self.future_payoff not in ('linear','inverse'): raise ValueError('Unsupported futures payoff')
        for k in ('seed','start','days','step_hours','tail_days','maturity_days','future_expiry_days','row_cap'):
            if type(getattr(self,k)) is not int: raise ValueError(k+' must be an integer')
        if not (0<=self.seed<2**32 and self.start>DAY and 1<=self.days<=28 and self.step_hours in (1,2,3,6,12,24) and 1<=self.tail_days<=3):
            raise ValueError('Synthetic time/seed limits')
        if self.maturity_days!=28 or not self.days+self.tail_days<self.future_expiry_days<=60:
            raise ValueError('Keep bill terms fixed and futures expiry beyond the closing tail')
        if not 1<=self.row_cap<=10000: raise ValueError('Synthetic row cap is 10000')
        bounds=dict(trend_annual=(0,1),volatility_annual=(0,1),initial_spot=(1000,1000000),
                    rate_annual=(-.05,.25),rate_volatility=(0,.1),premium_annual=(-.5,.5),
                    premium_volatility=(0,.3),mean_reversion=(0,100),spread_bps=(0,200),
                    liquidity=(.001,10),funding_daily_bps=(-100,100),fee_bps=(0,99))
        for k,(lo,hi) in bounds.items():
            v=getattr(self,k)
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:
                raise ValueError('Invalid synthetic parameter: '+k)


@dataclass
class MarketBundle:
    instruments: dict
    seeds: list
    trades: list
    start: int
    decision_end: int
    label_end: int
    funding: list = field(default_factory=list)
    path: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def payload(self):
        data=dict(schema=VERSION,instruments={s:asdict(i) for s,i in self.instruments.items()},
                  seeds=[asdict(t) for t in self.seeds],trades=[asdict(t) for t in self.trades],
                  funding=self.funding,path=self.path,start=self.start,
                  decision_end=self.decision_end,label_end=self.label_end,metadata=self.metadata)
        data['sha256']=digest(data)
        return data

    def scenario(self, seed=1):
        """Native collector interface. Same tape, independent execution delays."""
        return dict(id=f'{self.metadata.get("id","local")}:{seed}',seed=seed,trades=self.trades,
                    funding=self.funding,decision_end=self.decision_end,label_end=self.label_end,
                    tape_sha256=self.payload()['sha256'],law=self.metadata.get('scenario_law','user-supplied'))


def generate(config):
    c=config if isinstance(config,SimulationConfig) else SimulationConfig(**config)
    if not c.enabled: raise ValueError('Market simulation is disabled; explicitly enable it')
    configuration=asdict(c); identity=digest(configuration)
    maturity=c.start+c.maturity_days*DAY;expiry=c.start+c.future_expiry_days*DAY
    instruments={'BILL':Instrument('BILL',maturity,payoff='treasury',source_payoff='treasury',
                  tick=.01,lot=1.,fee_bps=c.fee_bps,cashflows=((maturity,100.),),listed_at=c.start-DAY)}
    if c.universe=='full':
        instruments.update(SPOT=Instrument('SPOT',expiry+DAY,payoff='spot',source_payoff='spot',
                            tick=.01,lot=.0001,fee_bps=c.fee_bps,listed_at=c.start-DAY),
                           FUTURE=Instrument('FUTURE',expiry,payoff=c.future_payoff,source_payoff=c.future_payoff,
                            tick=.01,lot=.0001 if c.future_payoff=='linear' else 1.,fee_bps=c.fee_bps,listed_at=c.start-DAY))
    steps=(c.days+c.tail_days)*24//c.step_hours+1
    if steps*len(instruments)*2>c.row_cap: raise ValueError('Requested path exceeds synthetic row cap')
    def noise(channel,n):
        seed=int.from_bytes(hashlib.sha256(f'{c.seed}:{channel}:{n}'.encode()).digest()[:8],'big')
        return random.Random(seed).gauss(0,1)
    dt=c.step_hours/(24*365.25);rho=math.exp(-c.mean_reversion*dt)
    spot,rate,premium=c.initial_spot,c.rate_annual,c.premium_annual
    trades,seeds,path,funding=[],[],[],[]
    end=c.start+c.days*DAY;label_end=end+c.tail_days*DAY
    for n in range(steps):
        t=c.start+n*c.step_hours*3600000
        if n:
            mu={'up':c.trend_annual,'flat':0.,'down':-c.trend_annual}[c.trend]
            spot*=math.exp((mu-.5*c.volatility_annual**2)*dt+c.volatility_annual*math.sqrt(dt)*noise('spot',n))
            rate=max(-.05,min(.25,c.rate_annual+rho*(rate-c.rate_annual)+c.rate_volatility*math.sqrt(dt)*noise('rate',n)))
            premium=max(-.5,min(.5,c.premium_annual+rho*(premium-c.premium_annual)+c.premium_volatility*math.sqrt(dt)*noise('premium',n)))
        mids={'BILL':100*math.exp(-rate*max(0,maturity-t)/(365.25*DAY)),
              'SPOT':spot,'FUTURE':spot*math.exp((rate+premium)*max(0,expiry-t)/(365.25*DAY))}
        path.append(dict(time=t,spot=spot,rate_annual=rate,premium_annual=premium,
                         bill=mids['BILL'],future=mids['FUTURE'],funding_daily_bps=c.funding_daily_bps))
        for symbol,ins in instruments.items():
            mid=mids[symbol]
            if n==0:
                seeds.append(Trade(c.start-1000,symbol,ins.round_price(mid,1),1000,'buy',
                                   f'sim:{identity[:10]}:seed:{symbol}',spot,ins.source_payoff))
            if t>=ins.expiry: continue
            liquidity=c.liquidity*math.exp(.2*noise('liquidity:'+symbol,n))
            amount=60*liquidity if symbol=='BILL' else (.1 if ins.payoff!='inverse' else 10000)*liquidity
            # Two explicit synthetic prints, not inferred executable quotes.
            for side,sign,offset in [('sell',-1,0),('buy',1,1)]:
                when=t+offset
                if when>label_end:continue
                price=ins.round_price(mid*(1+sign*c.spread_bps/20000),sign)
                trades.append(Trade(when,symbol,price,amount,side,f'sim:{identity[:10]}:{n}:{symbol}:{side}',spot,ins.source_payoff))
        if c.universe=='full' and n and n*c.step_hours%24==0:
            funding.append(dict(time=t,symbol='FUTURE',rate=c.funding_daily_bps/10000,
                                price=mids['FUTURE'],source='synthetic_market'))
    return MarketBundle(instruments,seeds,sorted(trades,key=lambda t:(t.time,t.symbol,t.identifier)),
                        c.start,end,label_end,funding,path,dict(id=identity,source_kind='synthetic_market',
                        configuration=configuration,calibration='none; explicitly configured law',
                        scenario_law='seeded joint spot/rate/premium paths, shared spot across instruments, lognormal trade capacity; separate execution jitter',
                        interpretation='Synthetic trade prints and contractual receipts; no observed market liquidity or historical settlement claim.'))


def select_market(existing, simulation=None):
    """Off means exactly the existing input; never silently synthesize missing data."""
    if not simulation or not simulation.get('enabled',False):return existing
    return generate(simulation)


def load_payload(data):
    data=dict(data);expected=data.pop('sha256',None)
    if data.get('schema')!=VERSION or digest(data)!=expected:raise ValueError('Market bundle schema/hash mismatch')
    if data['metadata'].get('source_kind') not in ('synthetic_market','synthetic_fixture','observed_trade','indicative_quote'):
        raise ValueError('Explicit data provenance required')
    if (any(type(data[k]) is not int for k in ('start','decision_end','label_end')) or
            not 0<data['start']<=data['decision_end']<=data['label_end'] or
            data['label_end']-data['start']>60*DAY):raise ValueError('Invalid split windows')
    if len(data['trades'])+len(data['seeds'])+len(data.get('funding',[]))>10000 or len(data.get('path',[]))>10000:raise ValueError('Market row cap')
    if not 1<=len(data['instruments'])<=16:raise ValueError('Instrument count cap')
    instruments={}
    for s,row in data['instruments'].items():
        row=dict(row);row['cashflows']=tuple(tuple(v) for v in row.get('cashflows',[]))
        instruments[s]=Instrument(**row)
        if s!=instruments[s].symbol:raise ValueError('Instrument identity mismatch')
    seeds=[Trade(**t) for t in data['seeds']];trades=[Trade(**t) for t in data['trades']]
    seen=set()
    for tr in seeds+trades:
        if tr.symbol not in instruments or tr.source_payoff!=instruments[tr.symbol].source_payoff:raise ValueError('Native units mismatch')
        if (type(tr.time) is not int or type(tr.executable) is not bool or
                not isinstance(tr.identifier,str) or not 1<=len(tr.identifier)<=160 or
                not all(not isinstance(v,bool) and math.isfinite(v) and v>0 for v in (tr.price,tr.amount,tr.index)) or
                tr.side not in ('buy','sell')):raise ValueError('Invalid trade')
        if tr.source_time is not None and tr.source_time!=tr.time and tr.executable:raise ValueError('Backdated executable print')
        key=(tr.symbol,tr.identifier)
        if key in seen:raise ValueError('Duplicate trade identity')
        seen.add(key)
        if data['metadata']['source_kind']=='indicative_quote' and tr.executable:raise ValueError('Indicative records cannot fill')
    if any(tr.time>=data['start'] for tr in seeds) or any(not data['start']<=tr.time<=data['label_end'] for tr in trades):raise ValueError('Trade outside declared allocation')
    if {tr.symbol for tr in seeds}!=set(instruments):raise ValueError('Observable seed required for every instrument')
    seen=set()
    for f in data.get('funding',[]):
        ins=instruments.get(f['symbol']);key=(f['symbol'],f['time'])
        if (data['metadata']['source_kind']!='synthetic_market' or f.get('source')!='synthetic_market' or
                not ins or not ins.is_future or type(f['time']) is not int or
                not data['start']<=f['time']<=data['label_end'] or f['time']>=ins.expiry or
                not math.isfinite(f['rate']) or abs(f['rate'])>.01 or
                not math.isfinite(f['price']) or f['price']<=0 or key in seen):
            raise ValueError('Invalid synthetic funding provenance, units or allocation')
        seen.add(key)
    return MarketBundle(instruments,seeds,sorted(trades,key=lambda t:(t.time,t.symbol,t.identifier)),
                        data['start'],data['decision_end'],data['label_end'],data.get('funding',[]),
                        data.get('path',[]),data['metadata'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--enabled',action='store_true',help='Explicitly enable synthetic data generation')
    p.add_argument('--config',help='JSON SimulationConfig; enabled must also be true or use --enabled')
    p.add_argument('--output',required=True);a=p.parse_args()
    c=json.loads(Path(a.config).read_text()) if a.config else {}
    if a.enabled:c['enabled']=True
    bundle=generate(c);path=Path(a.output)
    if path.exists():raise ValueError('Output already exists')
    path.parent.mkdir(parents=True,exist_ok=True)
    body=json.dumps(bundle.payload(),sort_keys=True,allow_nan=False).encode()
    if len(gzip.compress(body,mtime=0))>8000000:raise ValueError('Compressed input cap')
    path.write_bytes(body)
    print(json.dumps(dict(path=str(path),rows=len(bundle.trades),sha256=bundle.payload()['sha256'],source_kind='synthetic_market')))


if __name__=='__main__':main()
