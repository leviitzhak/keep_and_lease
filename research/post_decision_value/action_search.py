"""Actor-free optimization of V(immediate post-decision state).

The domain includes every native tick/lot inside configurable bounds. Stochastic
search budgets computation, not the legal price/quantity menu; it approximates an
argmax and never claims to enumerate an enormous Cartesian product completely.
"""
from dataclasses import dataclass,replace,field
import math
import random
from .engine import Instruction,Order,admissible


@dataclass(frozen=True)
class ActionDomain:
    min_btc: float=.0001
    max_btc: float=.02
    price_band_bps: float=50.
    max_new_orders: int=2

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.min_btc,self.max_btc,self.price_band_bps)) or not 0<self.min_btc<=self.max_btc or not 0<=self.price_band_bps<10000 or not 1<=self.max_new_orders<=6:
            raise ValueError('Invalid bounded native action domain')

    def symbols(self,obs,goal,instruments):
        return [s for s in sorted(instruments) if s in obs.market and obs.time<instruments[s].expiry<=goal.resolution]

    def price_ticks(self,obs,ins):
        ref=obs.market[ins.symbol]['price'];band=self.price_band_bps/10000
        return max(1,math.ceil(ref*(1-band)/ins.tick-1e-9)),math.floor(ref*(1+band)/ins.tick+1e-9)

    def quantity_lots(self,ins,price):
        factor=1 if ins.payoff=='linear' else price
        return max(1,math.ceil(self.min_btc*factor/ins.lot-1e-9)),math.floor(self.max_btc*factor/ins.lot+1e-9)

    def quote(self,rng,obs,ins,identifier,group='',old=None,radius=None):
        lo,hi=self.price_ticks(obs,ins)
        if lo>hi:return None
        if old is not None and radius is not None:
            tick=round(old.limit/ins.tick)+rng.randint(-radius,radius)
            tick=max(lo,min(hi,tick))
        else:tick=rng.randint(lo,hi)
        price=tick*ins.tick;ql,qh=self.quantity_lots(ins,price)
        if ql>qh:return None
        if old is not None and radius is not None:
            qty=round(abs(old.quantity)/ins.lot)+rng.randint(-radius,radius)
            qty=max(ql,min(qh,qty));sign=1 if old.quantity>0 else -1
        else:qty=rng.randint(ql,qh);sign=rng.choice((-1,1))
        return Order(identifier,ins.symbol,sign*qty*ins.lot,price,group,obs.time)

    def sample(self,rng,obs,goal,instruments):
        symbols=self.symbols(obs,goal,instruments);ids=sorted(obs.uncertain)
        kind=rng.choice(('create','amend','cancel','batch')) if ids else 'create'
        targets=[];orders=[]
        if kind in ('amend','cancel','batch'):
            # Every nonempty subset has support; no lexicographic truncation.
            targets=[oid for oid in ids if rng.random()<.5]
            if not targets and kind!='batch':targets=[rng.choice(ids)]
            if kind in ('amend','batch'):
                for oid in targets:
                    old=obs.uncertain[oid][-1]
                    if old.symbol not in symbols:continue
                    if kind=='batch' and rng.random()<.5:continue  # cancellation
                    o=self.quote(rng,obs,instruments[old.symbol],oid,old.group)
                    if o:orders.append(o)
        n=rng.randint(1,self.max_new_orders) if kind=='create' else rng.randint(0,self.max_new_orders) if kind=='batch' else 0
        if symbols:
            for leg in range(n):
                s=rng.choice(symbols)
                o=self.quote(rng,obs,instruments[s],f'o-{obs.submitted}-{leg}',f'g-{obs.submitted}' if n>1 else '')
                if o:orders.append(o)
        if not orders and not targets:return Instruction()
        if kind=='amend' and not orders:return Instruction('cancel',targets=tuple(targets))
        return Instruction(kind,tuple(orders),tuple(targets))

    def mutate(self,rng,obs,action,instruments,radius):
        if not action.orders:return action
        index=rng.randrange(len(action.orders));old=action.orders[index]
        new=self.quote(rng,obs,instruments[old.symbol],old.identifier,old.group,old=old,radius=radius)
        if new is None:return action
        orders=list(action.orders);orders[index]=new
        return replace(action,orders=tuple(orders))

    def contains(self,obs,action,instruments):
        for o in action.orders:
            ins=instruments[o.symbol];lo,hi=self.price_ticks(obs,ins);ql,qh=self.quantity_lots(ins,o.limit)
            ticks=o.limit/ins.tick;lots=abs(o.quantity)/ins.lot
            if abs(ticks-round(ticks))>1e-7 or not lo<=round(ticks)<=hi:return False
            if abs(lots-round(lots))>1e-7 or not ql<=round(lots)<=qh:return False
        return True

    def single_order_count(self,obs,goal,instruments):
        # The exact count is cheap for ordinary near-market bands. Pairs and batch
        # edits multiply it; they are deliberately not materialized here.
        total=0
        for s in self.symbols(obs,goal,instruments):
            ins=instruments[s];lo,hi=self.price_ticks(obs,ins)
            if ins.payoff=='linear':
                ql,qh=self.quantity_lots(ins,obs.market[s]['price']);total+=max(0,hi-lo+1)*max(0,qh-ql+1)*2
            else:
                for tick in range(lo,hi+1):
                    ql,qh=self.quantity_lots(ins,tick*ins.tick);total+=max(0,qh-ql+1)*2
        return total


def sparse_levels(lo,hi,extra,rng):
    """Endpoints, midpoint and random interior native steps; no large enumeration."""
    if lo>hi:return ()
    fixed={lo,hi,(lo+hi)//2}
    # Sampling range is O(extra), even when a tick/lot interval is enormous.
    fixed.update(rng.sample(range(lo+1,hi),min(extra,max(0,hi-lo-1))))
    return tuple(sorted(fixed))


@dataclass(frozen=True)
class SparseGridDomain(ActionDomain):
    random_points: int=2

    def __post_init__(self):
        super().__post_init__()
        if type(self.random_points) is not int or not 0<=self.random_points<=16:raise ValueError('Grid random points must be 0..16')

    def prepare(self,rng,obs,goal,instruments):
        prices={};quantities={}
        for s in self.symbols(obs,goal,instruments):
            ins=instruments[s];lo,hi=self.price_ticks(obs,ins)
            prices[s]=sparse_levels(lo,hi,self.random_points,rng)
            for tick in prices[s]:
                ql,qh=self.quantity_lots(ins,tick*ins.tick)
                quantities[s,tick]=sparse_levels(ql,qh,self.random_points,rng)
        return PreparedGrid(self.min_btc,self.max_btc,self.price_band_bps,self.max_new_orders,prices,quantities)


@dataclass(frozen=True)
class PreparedGrid(ActionDomain):
    prices: dict=field(default_factory=dict)
    quantities: dict=field(default_factory=dict)

    def quote(self,rng,obs,ins,identifier,group='',old=None,radius=None):
        prices=self.prices.get(ins.symbol,())
        if not prices:return None
        tick=rng.choice(prices);lots=self.quantities[ins.symbol,tick]
        if not lots:return None
        sign=(1 if old.quantity>0 else -1) if old is not None else rng.choice((-1,1))
        return Order(identifier,ins.symbol,sign*rng.choice(lots)*ins.lot,tick*ins.tick,group,obs.time)

    def anchors(self,rng,obs,instruments):
        actions=[]
        for s,ticks in self.prices.items():
            if not ticks:continue
            ins=instruments[s]
            for tick in sorted({ticks[0],ticks[-1]}):
                lots=self.quantities[s,tick]
                if not lots:continue
                for quantity in sorted({lots[0],lots[-1]}):
                    for sign in (-1,1):
                        actions.append(Instruction('create',(Order(f'o-{obs.submitted}-0',s,sign*quantity*ins.lot,tick*ins.tick,'',obs.time),)))
        for oid,variants in obs.uncertain.items():
            old=variants[-1];ticks=self.prices.get(old.symbol,())
            if not ticks:continue
            ins=instruments[old.symbol]
            for tick in sorted({ticks[0],ticks[-1]}):
                ql,qh=self.quantity_lots(ins,tick*ins.tick)
                if ql>qh:continue
                quantity=max(ql,min(qh,round(abs(old.quantity)/ins.lot)))
                # Retaining the current size is an additional useful amendment
                # point; it is not a restriction on independently sampled sizes.
                order=replace(old,quantity=math.copysign(quantity*ins.lot,old.quantity),limit=tick*ins.tick,created=obs.time)
                actions.append(Instruction('amend',(order,),(oid,)))
        rng.shuffle(actions)  # Fair instrument support when anchors exceed budget.
        return actions


class ValueActionSearch:
    def __init__(self,domain=None,evaluations=128,rounds=4,async_cap=.02):
        if not 4<=evaluations<=4096 or not 1<=rounds<=evaluations:
            raise ValueError('Bounded search requires 4..4096 proposals and valid rounds')
        self.domain=domain or ActionDomain();self.evaluations=evaluations;self.rounds=rounds;self.async_cap=async_cap

    def choose(self,obs,goal,instruments,score,*,rng=None,epsilon=0.):
        if not 0<=epsilon<=1:raise ValueError('Exploration probability')
        rng=rng or random.Random(0);audit=[];accepted=[];scores=[];seen=set();attempts=0
        domain=self.domain.prepare(rng,obs,goal,instruments) if isinstance(self.domain,SparseGridDomain) else self.domain
        fixed=[Instruction(),Instruction('emergency',targets=tuple(sorted(obs.uncertain)))]
        if obs.uncertain:fixed.append(Instruction('cancel',targets=tuple(sorted(obs.uncertain))))
        anchors=domain.anchors(rng,obs,instruments) if isinstance(domain,PreparedGrid) else []
        fixed.extend(anchors);anchor_count=len(anchors)
        # Every round retains global sampling support and refines good states.
        for stage in range(self.rounds):
            batch=[];limit=(stage+1)*self.evaluations//self.rounds
            while attempts<limit:
                if fixed:action=fixed.pop(0)
                elif accepted and stage>0 and rng.random()<.5:
                    elites=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)[:8]
                    action=domain.mutate(rng,obs,accepted[rng.choice(elites)],instruments,max(1,16//(stage+1)))
                else:action=domain.sample(rng,obs,goal,instruments)
                attempts+=1;key=repr(action)
                if key in seen:continue
                seen.add(key)
                ok,reason=admissible(obs,action,goal,instruments,self.async_cap)
                if ok and not domain.contains(obs,action,instruments):raise ValueError('Search escaped native domain')
                audit.append(dict(instruction=action.payload(),accepted=ok,reason=reason))
                if ok:batch.append(action)
            if batch:
                values=[float(v) for v in score(batch)]
                if len(values)!=len(batch) or any(not math.isfinite(v) for v in values):raise ValueError('Finite scalar objective required for every post-state')
                accepted.extend(batch);scores.extend(values)
        if not accepted:
            return Instruction('emergency',targets=tuple(sorted(obs.uncertain))),dict(proposals=audit,attempts=attempts,accepted=0,objective=None,explored=False)
        explore=rng.random()<epsilon
        index=rng.randrange(len(accepted)) if explore else max(range(len(scores)),key=scores.__getitem__)
        return accepted[index],dict(proposals=audit,attempts=attempts,accepted=len(accepted),objective=scores[index],explored=explore,
                                    search='sparse endpoint/random grid' if isinstance(domain,PreparedGrid) else 'stochastic global proposals and local refinement; approximate scalar argmax',
                                    boundary_proposals=anchor_count,boundary_proposals_not_attempted=len(fixed),
                                    price_grid={s:[t*instruments[s].tick for t in ticks] for s,ticks in domain.prices.items()} if isinstance(domain,PreparedGrid) else None)
