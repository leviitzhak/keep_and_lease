"""Native inverse-contract PRD ladder; research only, no exchange order calls.

Uses an ideal instantaneous coupling gate, delayed quote arrival and shared print
capacity. See docs/PRD_LADDER_RESEARCH.md for assumptions and limitations.
"""
from __future__ import annotations
from collections import deque, Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import csv, gzip, hashlib, heapq, itertools, json, math
from pathlib import Path

YEAR = 365 * 86400000
DAY = 86400000
FLAGS = ('block_trade_id','block_rfq_id','combo_trade_id','combo_id','block_trade_leg_count')
OPEN = [.015,.016,.017,.018,.019,.020]
CLOSE = [.010,.009,.008,.007,.006,.005]

def ms(s): return int(datetime.fromisoformat(s.replace('Z','+00:00')).replace(tzinfo=timezone.utc).timestamp()*1000)
def utc(t): return datetime.fromtimestamp(t/1000,timezone.utc).isoformat(timespec='milliseconds')
def eligible(r): return not any(r.get(k) for k in FLAGS)
def digest(b): return hashlib.sha256(b).hexdigest()
def split(n):
    q,r=divmod(n,6)
    return [q+(i<r) for i in range(6)]
def rounded(p,side):
    return (math.floor(p/2.5+1e-10) if side==1 else math.ceil(p/2.5-1e-10))*2.5

@dataclass
class Task:
    id:int
    cell:int
    kind:str
    direction:int
    magnitude:float
    total:int=0
    fills:list=field(default_factory=lambda:[0,0])
    generation:int=0
    anchor_apr:float|None=None
    anchor_time:int=0
    active:dict=field(default_factory=dict)
    requested:dict=field(default_factory=dict)
    def side(self,leg): return self.direction*(1 if leg==0 else -1)*(1 if self.kind=='open' else -1)
    def done(self): return self.total>0 and min(self.fills)==self.total

class Replay:
    def __init__(self,symbols,expiry,seeds,start,end,delay=500,participation=1.0,opposite_aggressor=True,name='base'):
        self.symbols=symbols;self.expiry=expiry;self.start=start;self.end=end
        self.delay=delay;self.participation=participation;self.opposite_aggressor=opposite_aggressor;self.name=name
        self.latest=[seeds[s] for s in symbols]
        assert all(r['timestamp']<start and eligible(r) for r in self.latest)
        self.spot=float(max(self.latest,key=lambda r:(r['timestamp'],int(r['trade_id'])))['index_price'])
        self.tasks={};self.serial=0;self.next_id=0;self.queue=[];self.cells=[]
        self.cash=0.;self.turnover=0.;self.realized=0.;self.pos=[0,0]
        self.fills=[];self.cycles=[];self.daily=[];self.closures=[];self.counts=Counter()
        self.peak_gross=0.;self.peak_unpaired=0.;self.peak_slots=0
        self.high=[0.,0.];self.drawdown=[0.,0.];self.last_t=start
        self.unpaired_seconds=0.;self.weighted_exposure_seconds=0.
        self.last_day=start//DAY;self.last_daily=None
        for i in range(6): self.new_cell(i,start)
        self.snapshot(start)

    def task(self,cell,kind,direction,magnitude,total=0):
        self.next_id+=1
        v=Task(self.next_id,cell,kind,direction,magnitude,total)
        self.tasks[v.id]=v;return v

    def new_cell(self,i,t):
        c=dict(level=i,direction=0,target=0,opened=0,closed=0,created=t,first=None,
               open_id=None,close_ids=[],ids=[],cash=0.,turnover=0.,realized=0.,
               lots=[deque(),deque()],position=[0,0],last_balanced_open=0)
        for direction in [1,-1]: c['ids'].append(self.task(i,'open',direction,OPEN[i]).id)
        if i==len(self.cells):self.cells.append(c)
        else:self.cells[i]=c

    def permission(self,v,leg):
        if v.kind=='open' and not self.cells[v.cell]['direction']:return None
        if v.fills[leg]>v.fills[1-leg]:return 0
        if v.fills[leg]<v.fills[1-leg]:return v.fills[1-leg]-v.fills[leg]
        return v.total-v.fills[leg]

    def snapshot(self,t):
        tau=[(x-t)/YEAR for x in self.expiry]
        for v in list(self.tasks.values()):
            limits=[];ages=[]
            for leg in [0,1]:
                side=v.side(leg);other=1-leg
                if v.fills[leg]<v.fills[other]:
                    apr=v.anchor_apr+(v.direction*v.magnitude if leg==1 else -v.direction*v.magnitude)
                    age=t-v.anchor_time
                else:
                    apr=(self.latest[other]['price']/self.spot-1)/tau[other]
                    apr+=v.direction*v.magnitude if leg==1 else -v.direction*v.magnitude
                    age=t-self.latest[other]['timestamp']
                limits.append(rounded(self.spot*(1+tau[leg]*apr),side));ages.append(age)
            unknown=v.kind=='open' and not self.cells[v.cell]['direction']
            quote_total=math.floor(.1*min(self.spot,*limits)/10+1e-10) if unknown else v.total
            for leg in [0,1]:
                allowance=self.permission(v,leg)
                if allowance is None:allowance=quote_total
                if allowance<=0:continue
                assert limits[leg]>0
                signature=(v.generation,limits[leg],allowance,quote_total)
                if v.requested.get(leg)==signature:continue
                v.requested[leg]=signature;self.serial+=1
                quote=dict(limit=limits[leg],qty=allowance,total=quote_total,observed=t,
                           activation=t+self.delay,index=self.spot,reference_age_ms=ages[leg],generation=v.generation)
                heapq.heappush(self.queue,(t+self.delay,self.serial,v.id,leg,quote))

    def arrivals(self,t,inclusive=False):
        while self.queue and (self.queue[0][0]<=t if inclusive else self.queue[0][0]<t):
            _,_,tid,leg,q=heapq.heappop(self.queue);v=self.tasks.get(tid)
            if v and v.generation==q['generation']:
                # Cancel/replace the old quote; reject a new quote that would
                # trade with our own resting opposite order on this instrument.
                v.active.pop(leg,None)
                own=v.side(leg)
                crossed=False
                for other in self.tasks.values():
                    oq=other.active.get(leg)
                    if other.id==v.id or other.side(leg)==own or not oq or oq['qty']<=0:continue
                    allowance=self.permission(other,leg)
                    if allowance is not None and allowance<=0:continue
                    if (q['limit']>=oq['limit'] if own==1 else q['limit']<=oq['limit']):
                        crossed=True;break
                if crossed:
                    self.counts['self_cross_quote_rejections']+=1
                    v.requested.pop(leg,None)
                else:v.active[leg]=q

    def invalidate(self,v):
        v.generation+=1;v.active.clear();v.requested.clear()

    def choose(self,v,q,t):
        c=self.cells[v.cell]
        assert c['direction']==0
        c.update(direction=v.direction,target=q['total'],first=t,open_id=v.id)
        v.total=q['total']
        for tid in c['ids']:
            if tid!=v.id:self.tasks.pop(tid,None)
        c['ids']=[v.id]
        for mag in CLOSE:
            z=self.task(v.cell,'close',v.direction,mag)
            c['close_ids'].append(z.id);c['ids'].append(z.id)
        self.counts['opening_cycles_started']+=1

    def book(self,c,v,leg,n,price):
        side=v.side(leg);face=n*10
        cash=side*face/price;self.cash+=cash;c['cash']+=cash
        self.turnover+=face/price;c['turnover']+=face/price
        self.pos[leg]+=side*n;c['position'][leg]+=side*n
        if v.kind=='open':c['lots'][leg].append([n,price])
        else:
            remain=n
            while remain:
                lot=c['lots'][leg][0];k=min(remain,lot[0])
                pnl=-side*k*10*(1/lot[1]-1/price)
                self.realized+=pnl;c['realized']+=pnl
                lot[0]-=k;remain-=k
                if lot[0]==0:c['lots'][leg].popleft()

    def fill(self,v,leg,q,n,row):
        t=row['timestamp'];c=self.cells[v.cell]
        if not c['direction']:self.choose(v,q,t)
        allowance=self.permission(v,leg)
        assert n>0 and n<=allowance and n<=q['qty']
        assert q['observed']+self.delay==q['activation']<t
        side=v.side(leg);assert row['price']<q['limit'] if side==1 else row['price']>q['limit']
        if self.opposite_aggressor:assert row['direction']==('sell' if side==1 else 'buy')
        lag=v.fills[leg]<v.fills[1-leg];old=min(v.fills)
        self.book(c,v,leg,n,q['limit']);v.fills[leg]+=n;q['qty']-=n
        self.fills.append(dict(timestamp_ms=t,utc=utc(t),cell=v.cell,cycle_start_ms=c['first'],
            kind=v.kind,direction=v.direction,target_prd_pp=v.direction*v.magnitude*100,
            leg=leg,instrument=self.symbols[leg],side='buy' if side==1 else 'sell',
            contracts=n,usd_face=n*10,limit=q['limit'],trade_price=row['price'],
            trade_id=row['trade_id'],trade_seq=row['trade_seq'],trade_usd_face=row['amount'],
            quote_observed_ms=q['observed'],activation_ms=q['activation'],quote_index=q['index'],
            reference_age_ms=q['reference_age_ms'],role='catch_up' if lag else 'lead',
            index_before_print=self.spot))
        self.counts['fill_events']+=1
        delta=min(v.fills)-old
        if v.kind=='open' and delta:
            c['opened']+=delta
            assigned=split(c['opened'])
            for tid,total in zip(c['close_ids'],assigned):
                z=self.tasks[tid]
                if total>z.total:
                    z.total=total
                    # Existing quantities remain valid; extra size arrives only
                    # through a delayed quote, bounded again at each fill.
            self.counts['opened_contract_pairs']+=delta
        elif v.kind=='close' and delta:
            c['closed']+=delta;self.counts['closed_contract_pairs']+=delta
            self.closures.append(dict(timestamp_ms=t,cell=v.cell,direction=v.direction,
                                     closing_prd_pp=v.direction*v.magnitude*100,contracts=delta,
                                     elapsed_hours=(t-c['first'])/3600000))
        if not lag:
            v.anchor_apr=(q['limit']/self.spot-1)/((self.expiry[leg]-t)/YEAR)
            v.anchor_time=t;self.invalidate(v)
        elif v.fills[0]==v.fills[1]:
            v.anchor_apr=None;self.invalidate(v)
        # Exact conservation of all assigned closing native contracts.
        assert sum(self.tasks[x].total for x in c['close_ids'])==c['opened']
        assert c['closed']<=c['opened']<=c['target']
        if c['opened']==c['target'] and c['closed']==c['target']:
            assert c['position']==[0,0] and not any(c['lots'])
            self.cycles.append(dict(cell=v.cell,opening_prd_pp=c['direction']*OPEN[v.cell]*100,
                direction=c['direction'],opened_utc=utc(c['first']),closed_utc=utc(t),
                contracts=c['target'],gross_btc=c['cash'],turnover_btc=c['turnover'],
                gross_usd_at_close=c['cash']*self.spot,duration_hours=(t-c['first'])/3600000))
            assert abs(c['cash']-c['realized'])<1e-10
            for tid in c['ids']:self.tasks.pop(tid,None)
            self.new_cell(v.cell,t)

    def measures(self,t):
        marks=[float(r.get('mark_price') or r['price']) for r in self.latest]
        gross=self.cash-sum(n*10/p for n,p in zip(self.pos,marks))
        last_trade_pnl=self.cash-sum(n*10/r['price'] for n,r in zip(self.pos,self.latest))
        unpaired=sum(abs(sum(c['position']))*10/self.spot for c in self.cells)
        inventory=sum(max(abs(x) for x in c['position'])*10/self.spot for c in self.cells)
        paired=sum(min(abs(x) for x in c['position'])*10/self.spot for c in self.cells)
        slots=sum(c['direction']!=0 for c in self.cells)
        assert slots<=6
        self.peak_slots=max(self.peak_slots,slots);self.peak_gross=max(self.peak_gross,inventory)
        self.peak_unpaired=max(self.peak_unpaired,unpaired)
        for j,fee in enumerate([0.,.0001]):
            eq=gross-fee*self.turnover;self.high[j]=max(self.high[j],eq)
            self.drawdown[j]=max(self.drawdown[j],self.high[j]-eq)
        tau=[(x-t)/YEAR for x in self.expiry]
        d=((self.latest[1]['price']/self.spot-1)/tau[1]-(self.latest[0]['price']/self.spot-1)/tau[0])*100
        return dict(timestamp_ms=t,utc=utc(t),gross_btc=gross,realized_btc=self.realized,
            unrealized_btc=gross-self.realized,net_1bp_btc=gross-.0001*self.turnover,
            last_trade_mark_gross_btc=last_trade_pnl,index=self.spot,turnover_btc=self.turnover,
            inventory_btc=inventory,paired_inventory_btc=paired,unpaired_btc=unpaired,
            net_directional_face_btc=sum(self.pos)*10/self.spot,
            occupied_levels=slots,near_contracts=self.pos[0],far_contracts=self.pos[1],prd_pp=d,
            near_mark=marks[0],far_mark=marks[1],
            near_mark_age_seconds=(t-self.latest[0]['timestamp'])/1000,
            far_mark_age_seconds=(t-self.latest[1]['timestamp'])/1000)

    def run(self,events):
        previous=self.measures(self.start)
        for t,it in itertools.groupby(events,key=lambda r:r['timestamp']):
            assert self.start<=t<self.end and t>=self.last_t
            if t//DAY!=self.last_day:
                self.daily.append(dict(previous,date=utc(self.last_day*DAY)[:10]))
                self.last_day=t//DAY
            dt=(t-self.last_t)/1000
            self.unpaired_seconds+=dt*(previous['unpaired_btc']>0)
            self.weighted_exposure_seconds+=dt*previous['inventory_btc'];self.last_t=t
            group=list(it);self.arrivals(t)
            for row in group:
                leg=self.symbols.index(row['instrument_name'])
                capacity=math.floor(row['amount']/10*self.participation+1e-10)
                original=capacity;candidates=[]
                for v in list(self.tasks.values()):
                    q=v.active.get(leg)
                    if not q or q['activation']>=t or q['qty']<=0:continue
                    side=v.side(leg)
                    if self.opposite_aggressor and row['direction']!=('sell' if side==1 else 'buy'):continue
                    if not (row['price']<q['limit'] if side==1 else row['price']>q['limit']):continue
                    allowance=self.permission(v,leg)
                    if allowance is not None and allowance<=0:continue
                    candidates.append((-side*q['limit'],q['activation'],v.id,v,q))
                for _,_,_,v,q in sorted(candidates,key=lambda x:x[:3]):
                    if not capacity:break
                    if v.id not in self.tasks:continue
                    allowance=self.permission(v,leg)
                    if allowance is None:allowance=q['total']
                    n=min(capacity,q['qty'],allowance)
                    if n>0:self.fill(v,leg,q,n,row);capacity-=n
                assert 0<=original-capacity<=original
                if len({v.side(leg) for _,_,_,v,q in candidates})>1:
                    self.counts['prints_with_both_sides_crossing']+=1
            self.arrivals(t,True)
            for row in group:
                leg=self.symbols.index(row['instrument_name']);self.latest[leg]=row
                self.spot=float(row['index_price'])
            self.snapshot(t);previous=self.measures(t)
        self.unpaired_seconds+=(self.end-self.last_t)/1000*(previous['unpaired_btc']>0)
        self.weighted_exposure_seconds+=(self.end-self.last_t)/1000*previous['inventory_btc']
        final=self.measures(self.end);self.daily.append(dict(final,date=utc(self.last_day*DAY)[:10]))
        open_cells=[]
        for c in self.cells:
            if c['direction']:
                open_cells.append(dict(level=c['level'],opening_prd_pp=c['direction']*OPEN[c['level']]*100,
                    opened_utc=utc(c['first']),target_contracts=c['target'],paired_opened_contracts=c['opened'],
                    paired_closed_contracts=c['closed'],remaining_near_contracts=c['position'][0],
                    remaining_far_contracts=c['position'][1]))
        summary=dict(scenario=self.name,symbols=self.symbols,start=utc(self.start),end_exclusive=utc(self.end),
            delay_ms=self.delay,participation=self.participation,opposite_aggressor=self.opposite_aggressor,
            allocation_btc_per_level=.1,max_reserved_allocation_btc=.6,**self.counts,
            completed_cycles=len(self.cycles),positive_cycles=sum(x['direction']==1 for x in self.cycles),
            negative_cycles=sum(x['direction']==-1 for x in self.cycles),
            winning_completed_cycles=sum(x['gross_btc']>0 for x in self.cycles),
            final=final,fee_sensitivity_btc={str(bp):final['gross_btc']-bp/10000*self.turnover for bp in [-1,0,1,5]},
            break_even_fee_bp=final['gross_btc']/self.turnover*10000 if self.turnover else None,
            max_drawdown_gross_btc=self.drawdown[0],max_drawdown_1bp_btc=self.drawdown[1],
            peak_inventory_btc=self.peak_gross,peak_unpaired_btc=self.peak_unpaired,peak_occupied_levels=self.peak_slots,
            unpaired_hours=self.unpaired_seconds/3600,
            average_inventory_btc=self.weighted_exposure_seconds/((self.end-self.start)/1000),
            open_cells=open_cells)
        return summary

def load_rows(paths,symbols,start,end):
    rows=[];coverage=[];seen=set();all_rows=[]
    for path in paths:
        data=Path(path).read_bytes();raw=[json.loads(line) for line in gzip.decompress(data).splitlines()]
        ok=[]
        for r in raw:
            assert r['instrument_name'] in symbols and start<=r['timestamp']<end
            key=(r['instrument_name'],str(r['trade_id']))
            assert key not in seen;seen.add(key)
            assert r['amount']>0 and r['amount']%10==0 and r['price']>0 and r['index_price']>0
            if eligible(r):ok.append(r)
        all_rows.extend(raw);coverage.append(dict(path=str(path),sha256=digest(data),raw_rows=len(raw),ordinary_rows=len(ok)))
    # Preserve per-instrument sequence causality if a source timestamp reverses.
    # No trade may move earlier than its preceding sequence observation.
    for symbol in symbols:
        prior=start;last_seq=None
        for r in sorted((r for r in all_rows if r['instrument_name']==symbol),key=lambda r:r['trade_seq']):
            assert last_seq is None or r['trade_seq']>last_seq
            last_seq=r['trade_seq'];source_t=r['timestamp'];prior=max(prior,source_t)
            if prior!=source_t:r=dict(r,source_timestamp_ms=source_t,timestamp=prior)
            assert prior<end,'Sequence-normalized event extends beyond the requested interval'
            if eligible(r):rows.append(r)
    rows.sort(key=lambda r:(r['timestamp'],int(r['trade_id']),r['instrument_name']))
    return rows,coverage

def write_csv(path,rows):
    path=Path(path)
    if not rows:path.write_text('');return
    with (gzip.open(path,'wt',newline='') if path.suffix=='.gz' else path.open('w',newline='')) as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def save_run(out,replay,summary,coverage):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    (out/'input_coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
    for name,rows in [('daily.csv',replay.daily),('fills.csv.gz',replay.fills),('cycles.csv',replay.cycles),('closures.csv.gz',replay.closures)]:
        write_csv(out/name,rows)
