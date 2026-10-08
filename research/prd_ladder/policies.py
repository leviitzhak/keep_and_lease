"""Research policy replay. Market-data observation and fill notification are immediate.

Cancel reaches the exchange after D; reconciliation acknowledgment takes another D.
An emergency execution is a bounded next-opposite-print proxy, never an IOC claim.
The original shared-slot direction lock is retained and separately diagnosed.
"""
from replay import *

class PolicyReplay(Replay):
    def __init__(self,*args,fresh_seconds=None,index_seconds=5,relax=False,rescue=False,
                 carry_apr=False,concession_bp=5,rescue_slippage_bp=2,**kwargs):
        self.fresh_ms=None if fresh_seconds is None else int(fresh_seconds*1000)
        self.index_ms=int(index_seconds*1000);self.relax=relax;self.rescue=rescue
        self.carry_apr=carry_apr;self.concession_bp=concession_bp;self.slip_bp=rescue_slippage_bp
        self.clock=0;self.timers=[];self.timer_serial=0;self.episodes=[];self.cancellations=[]
        self.next_episode=0;self._executing=False;self._fill_side=None;self._force_price=None
        self.index_time=0;self.index_generation=0;self.expiry_signature=None
        self.fees_btc=0.;self.fee_usd=0.;self.mirror_shadow=[]
        self.backlog_btc_seconds=0.;self.backlog_seconds=0.
        super().__init__(*args,**kwargs)

    def task(self,*args,**kwargs):
        v=super().task(*args,**kwargs)
        v.pending=None;v.cancel_token=0;v.episode=None;v.emergency=False
        v.last_rescue_observation=-1;v.order_serial=0
        return v

    def timer(self,t,kind,payload):
        if t>=self.end:return
        self.timer_serial+=1;heapq.heappush(self.timers,(t,self.timer_serial,kind,payload))

    def gap(self,v):return abs(v.fills[0]-v.fills[1])

    def permission(self,v,leg):
        if self._executing:
            if v.kind=='open' and not self.cells[v.cell]['direction']:return None
            return max(0,v.total-v.fills[leg])
        return super().permission(v,leg)

    def invalidate(self,v):
        self.cancel(v,self.clock,'fill_reconcile')

    def cancel(self,v,t,reason):
        if v.pending is not None:return
        v.cancel_token+=1;token=v.cancel_token
        rec=dict(task_id=v.id,cell=v.cell,reason=reason,requested_ms=t,
                 exchange_effective_ms=t+self.delay,ack_ms=t+2*self.delay,
                 near_at_request=v.fills[0],far_at_request=v.fills[1],
                 near_at_ack=None,far_at_ack=None,residual_contracts_at_ack=None,
                 late_fill_contracts=0,status='pending_at_period_end')
        self.cancellations.append(rec);v.pending=rec;v.requested.clear()
        self.timer(t+self.delay,'cancel',(v.id,token))
        self.timer(t+2*self.delay,'ack',(v.id,token))

    def choose(self,v,q,t):
        c=self.cells[v.cell]
        for tid in c['ids']:
            if tid!=v.id:
                z=self.tasks[tid]
                for leg,oq in z.active.items():
                    if oq['qty']>0:self.mirror_shadow.append((t+self.delay,leg,z.side(leg),dict(oq)))
        super().choose(v,q,t)

    def book(self,c,v,leg,n,price):
        side=self._fill_side if self._fill_side is not None else v.side(leg)
        face=n*10;cash=side*face/price
        self.cash+=cash;c['cash']+=cash;self.turnover+=face/price;c['turnover']+=face/price
        self.turnover_usd+=face;self.pos[leg]+=side*n;c['position'][leg]+=side*n
        opening_side=c['direction']*(1 if leg==0 else -1)
        if side==opening_side:c['lots'][leg].append([n,price])
        else:
            remain=n
            while remain:
                assert c['lots'][leg],('oversold inventory',v.id,leg,n)
                lot=c['lots'][leg][0];k=min(remain,lot[0])
                p=-side*k*10*(1/lot[1]-1/price)
                self.realized+=p;c['realized']+=p;self.realized_usd_at_fills+=p*self.spot
                lot[0]-=k;remain-=k
                if not lot[0]:c['lots'][leg].popleft()

    def anchor(self,v):
        if not self.gap(v):v.anchor_apr=None;return
        lead=0 if v.fills[0]>v.fills[1] else 1
        lots=v.unmatched_fills[lead]
        assert sum(x['contracts'] for x in lots)==self.gap(v)
        v.anchor_apr=sum(x['contracts']*x['apr_pp']/100 for x in lots)/self.gap(v)
        v.anchor_time=v.episode['start_ms']

    def episode_start(self,v,t):
        self.next_episode+=1
        v.episode=dict(episode_id=self.next_episode,task_id=v.id,cell=v.cell,kind=v.kind,
                       start_ms=t,end_ms=None,duration_seconds=None,max_gap_contracts=0,
                       matched_contracts=0,unwound_contracts=0,deadline_reached=False,
                       outcome='open',residual_contracts=None)
        if self.relax:
            for elapsed in [2000,3000,4000,5000]:self.timer(t+elapsed,'relax',(v.id,self.next_episode))
        if self.rescue:self.timer(t+5000,'deadline',(v.id,self.next_episode))

    def finish_episode(self,v,t):
        if v.episode is None or self.gap(v):return
        e=v.episode;e.update(end_ms=t,duration_seconds=(t-e['start_ms'])/1000,residual_contracts=0,
            outcome='mixed' if e['matched_contracts'] and e['unwound_contracts'] else ('unwound' if e['unwound_contracts'] else 'matched'))
        self.episodes.append(e);v.episode=None;v.emergency=False

    def extras(self,f,v,q,t,undo=False,pending_before=None):
        phase=q.get('phase','target');fee_bp=5 if phase=='rescue' else 1
        fee=f['usd_face']/f['limit']*fee_bp/10000;self.fees_btc+=fee;self.fee_usd+=fee*self.spot
        f.update(task_kind=v.kind,action='undo' if undo else 'normal',execution_phase=phase,
                 order_limit=q['limit'],original_target_prd_pp=v.direction*v.magnitude*100,
                 effective_target_prd_pp=q.get('effective_prd_pp',v.direction*v.magnitude*100),
                 reference_type=q.get('reference_type','market'),
                 index_age_at_quote_ms=q.get('index_age_ms',0),index_age_at_fill_ms=t-self.index_time,
                 source_age_at_fill_ms=q.get('reference_age_ms',0)+t-q['observed'],
                 concession_bp=q.get('concession_bp',0),cancel_pending=pending_before is not None,
                 cancel_requested_ms=pending_before['requested_ms'] if pending_before else None,
                 episode_id=v.episode['episode_id'] if v.episode else None,
                 episode_age_ms=t-v.episode['start_ms'] if v.episode else 0,
                 estimated_fee_btc=fee,estimated_fee_bp=fee_bp,
                 rescue_action=q.get('rescue_action',''),rescue_decision_ms=q.get('rescue_decision_ms'),
                 rescue_reference_price=q.get('rescue_reference_price'),
                 rescue_slippage_bp=self.slip_bp if phase=='rescue' else 0)
        if f['cancel_pending']:
            pending_before['late_fill_contracts']+=f['contracts'];self.counts['fills_while_cancel_pending']+=1
            self.counts['contracts_while_cancel_pending']+=f['contracts']
        if phase=='rescue':self.counts['rescue_fills']+=1;self.counts['rescue_'+f['rescue_action']+'_contracts']+=f['contracts']

    def fill(self,v,leg,q,n,row,undo=False,price=None):
        t=row['timestamp'];self.clock=t
        if v.episode is None:self.episode_start(v,t)
        old_matched=min(v.fills);matched_before=len(self.matched);pending_before=v.pending
        if undo:
            assert n<=self.gap(v) and v.fills[leg]>v.fills[1-leg]
            c=self.cells[v.cell];side=-v.side(leg);self._fill_side=side
            self.book(c,v,leg,n,price);self._fill_side=None
            v.fills[leg]-=n;left=n
            while left:
                lot=v.unmatched_fills[leg][0];k=min(left,lot['contracts']);lot['contracts']-=k;left-=k
                if not lot['contracts']:v.unmatched_fills[leg].popleft()
            q['qty']-=n;apr=(price/self.spot-1)/((self.expiry[leg]-t)/YEAR)
            self.fills.append(dict(timestamp_ms=t,utc=utc(t),cell=v.cell,cycle_start_ms=c['first'],
                kind='close' if v.kind=='open' else 'open',direction=v.direction,
                target_prd_pp=v.direction*v.magnitude*100,leg=leg,instrument=self.symbols[leg],
                side='buy' if side==1 else 'sell',contracts=n,usd_face=n*10,limit=price,
                trade_price=row['price'],trade_id=row['trade_id'],trade_seq=row['trade_seq'],trade_usd_face=row['amount'],
                quote_observed_ms=q['observed'],activation_ms=q['activation'],quote_index=q['index'],
                reference_age_ms=q['reference_age_ms'],role='unwind',index_before_print=self.spot,
                fill_apr_pp=apr*100,filled_btc=n*10/price,async_cap_btc=self.async_cap_btc,
                task_id=v.id,aggressor=row['direction']))
            self.counts['fill_events']+=1;v.episode['unwound_contracts']+=n
            self.cancel(v,t,'unwind_reconcile')
        else:
            self._executing=True;limit=q['limit']
            if price is not None:q['limit']=price
            super().fill(v,leg,q,n,row)
            q['limit']=limit;self._executing=False
            v.episode['matched_contracts']+=max(0,min(v.fills)-old_matched)
        self.extras(self.fills[-1],v,q,t,undo,pending_before)
        for m in self.matched[matched_before:]:
            near=self.fills[m['near_fill_id']];far=self.fills[m['far_fill_id']]
            m.update(original_target_prd_pp=v.direction*v.magnitude*100,
                effective_target_prd_pp=q.get('effective_prd_pp',v.direction*v.magnitude*100),
                completion_phase=q.get('phase','target'),near_phase=near.get('execution_phase','target'),
                far_phase=far.get('execution_phase','target'))
        v.episode['max_gap_contracts']=max(v.episode['max_gap_contracts'],self.gap(v))
        self.anchor(v)
        if not self.gap(v):self.finish_episode(v,t)
        if v.id not in self.tasks and v.pending is not None:
            v.pending.update(status='fully_filled_task',near_at_ack=v.fills[0],far_at_ack=v.fills[1],
                residual_contracts_at_ack=0)

    def fresh(self,v,t):
        if self.fresh_ms is None:return True
        if t-self.index_time>self.index_ms:return False
        return bool(self.gap(v)) or all(t-r['timestamp']<=self.fresh_ms for r in self.latest)

    def base_limit(self,v,leg,t):
        tau=[(x-t)/YEAR for x in self.expiry];other=1-leg
        if self.gap(v):
            apr=v.anchor_apr;age=t-v.episode['start_ms'];typ='executed_anchor'
        else:
            r=self.latest[other];age=t-r['timestamp'];typ='market_apr' if self.carry_apr else 'market_price'
            apr=(r['price']/r['index_price']-1)/((self.expiry[other]-r['timestamp'])/YEAR) if self.carry_apr else (r['price']/self.spot-1)/tau[other]
        apr+=v.direction*v.magnitude if leg==1 else -v.direction*v.magnitude
        return self.spot*(1+tau[leg]*apr),age,typ

    def cross_own(self,v,leg,q):
        side=q.get('side',v.side(leg))
        for z in self.tasks.values():
            oq=z.active.get(leg)
            if z.id==v.id or not oq or oq['qty']<=0:continue
            if oq.get('side',z.side(leg))==side:continue
            if q['limit']>=oq['limit'] if side==1 else q['limit']<=oq['limit']:return True
        return False

    def queue_quote(self,v,leg,q,t):
        signature=(q['limit'],q['qty'],q['total'],q['phase'],q['side'])
        if v.requested.get(leg)==signature:return
        v.requested[leg]=signature;self.serial+=1
        q.update(observed=t,activation=t+self.delay,index=self.spot,generation=v.generation,
                 fill_watermark=v.fills[leg],index_age_ms=t-self.index_time)
        heapq.heappush(self.queue,(t+self.delay,self.serial,v.id,leg,q))

    def rescue_quote(self,v,t):
        if not self.gap(v):return
        # Each attempt needs a new observed market event; no synthetic timer liquidity.
        if self.index_time<=v.last_rescue_observation:return
        if t-self.index_time>5000:return
        lead=0 if v.fills[0]>v.fills[1] else 1;lag=1-lead;choices=[]
        for action,leg,side in [('complete',lag,v.side(lag)),('undo',lead,-v.side(lead))]:
            r=self.latest[leg]
            if t-r['timestamp']>60000:continue
            reference=r['price'];estimate=reference*(1+side*self.slip_bp/10000)
            if action=='complete':
                target=self.base_limit(v,leg,t)[0]
                cost=side*(1/target-1/estimate)+.0005/estimate
            else:
                lots=v.unmatched_fills[lead]
                cash=sum(x['contracts']*v.side(lead)/x['price'] for x in lots)/self.gap(v)
                cost=-(cash+side/estimate)+.0005/estimate
            choices.append((cost,action,leg,side,reference))
        if not choices:return
        cost,action,leg,side,reference=min(choices)
        cap=rounded(reference*(1+side*10/10000),side)
        q=dict(limit=cap,qty=self.gap(v),total=v.total,phase='rescue',side=side,
            reference_age_ms=t-self.latest[leg]['timestamp'],reference_type='rescue_trade_proxy',
            concession_bp=0,effective_prd_pp=None,rescue_action=action,rescue_decision_ms=t,
            rescue_reference_price=reference)
        v.last_rescue_observation=self.index_time
        self.queue_quote(v,leg,q,t);self.counts['rescue_attempts']+=1
        self.timer(t+self.delay+1000,'rescue_expire',(v.id,v.generation,t))

    def snapshot(self,t):
        self.clock=t
        if not self.index_time:self.index_time=max(r['timestamp'] for r in self.latest)
        if self.fresh_ms is not None:
            deadlines=[self.index_time+self.index_ms+1]+[r['timestamp']+self.fresh_ms+1 for r in self.latest]
            future=[x for x in deadlines if x>t]
            signature=tuple(deadlines)
            if future and signature!=self.expiry_signature:
                self.expiry_signature=signature;self.timer(min(future),'freshness',signature)
        for v in list(self.tasks.values()):
            if v.pending is not None:continue
            if v.emergency:
                if not v.active and not v.requested:self.rescue_quote(v,t)
                continue
            if not self.fresh(v,t):
                if v.active or v.requested:self.cancel(v,t,'freshness')
                continue
            limits=[self.base_limit(v,leg,t) for leg in [0,1]]
            unknown=v.kind=='open' and not self.cells[v.cell]['direction']
            total=math.floor(.1*min(self.spot,*[rounded(x[0],v.side(i)) for i,x in enumerate(limits)])/10+1e-10) if unknown else v.total
            for leg in [0,1]:
                allowance=super().permission(v,leg)
                if allowance is None:allowance=total
                if allowance<=0:continue
                raw,age,typ=limits[leg];side=v.side(leg);bp=0.
                if self.relax and self.gap(v):
                    bp=self.concession_bp*max(0,min(1,(t-v.episode['start_ms']-2000)/3000))
                    raw*=1+side*bp/10000
                limit=rounded(raw,side)
                if not self.gap(v):allowance=min(allowance,math.floor(self.async_cap_btc*min(self.spot,limit)/10+1e-10))
                if allowance<=0:continue
                effective=v.direction*v.magnitude*100
                if self.gap(v):
                    apr=(raw/self.spot-1)/((self.expiry[leg]-t)/YEAR)
                    effective=(apr-v.anchor_apr if leg==1 else v.anchor_apr-apr)*100
                q=dict(limit=limit,qty=allowance,total=total,phase='relaxed' if bp else 'target',side=side,
                    reference_age_ms=age,reference_type=typ,concession_bp=bp,effective_prd_pp=effective)
                self.queue_quote(v,leg,q,t)

    def arrivals(self,t,inclusive=False):
        while self.queue and (self.queue[0][0]<=t if inclusive else self.queue[0][0]<t):
            _,_,tid,leg,q=heapq.heappop(self.queue);v=self.tasks.get(tid)
            if not v or q['generation']!=v.generation:continue
            if v.pending and q['observed']>=v.pending['requested_ms']:continue
            # Model one edited order per leg, with cumulative filled quantity
            # deducted from an in-flight quantity instruction.
            q['qty']=max(0,q['qty']-max(0,v.fills[leg]-q['fill_watermark']))
            v.active.pop(leg,None)
            if not q['qty']:v.requested.pop(leg,None);continue
            if self.cross_own(v,leg,q):
                self.counts['self_cross_quote_rejections']+=1;v.requested.pop(leg,None)
            else:v.active[leg]=q

    def timer_event(self,t,kind,payload):
        self.clock=t
        if kind=='freshness':return
        tid=payload[0];v=self.tasks.get(tid)
        if not v:return
        if kind in ['cancel','ack']:
            if payload[1]!=v.cancel_token or v.pending is None:return
            if kind=='cancel':
                v.active.clear();v.requested.clear();v.generation+=1
            else:
                rec=v.pending;rec.update(near_at_ack=v.fills[0],far_at_ack=v.fills[1],
                    residual_contracts_at_ack=self.gap(v),status='reconciled')
                v.pending=None;v.requested.clear()
                if v.episode and v.episode['deadline_reached'] and self.gap(v):v.emergency=True
        elif kind in ['relax','deadline']:
            if not v.episode or v.episode['episode_id']!=payload[1]:return
            if kind=='deadline':
                v.episode['deadline_reached']=True;self.counts['hedge_deadlines']+=1
                self.cancel(v,t,'hedge_deadline')
        elif kind=='rescue_expire':
            if v.generation!=payload[1]:return
            if any(q.get('rescue_decision_ms')==payload[2] for q in v.active.values()):
                self.counts['rescue_attempts_expired']+=1;self.cancel(v,t,'rescue_expire')

    def measures(self,t):
        m=super().measures(t)
        m.update(estimated_fees_btc=self.fees_btc,net_estimated_btc=m['gross_btc']-self.fees_btc,
                 net_estimated_usd=(m['gross_btc']-self.fees_btc)*self.spot,
                 index_age_seconds=max(0,t-self.index_time)/1000)
        return m

    def execute_print(self,row):
        t=row['timestamp'];leg=self.symbols.index(row['instrument_name'])
        self.mirror_shadow=[x for x in self.mirror_shadow if x[0]>=t and x[3]['qty']>0]
        for until,l,side,q in self.mirror_shadow:
            if l==leg and (row['price']<q['limit'] if side==1 else row['price']>q['limit']):
                self.counts['ideal_mirror_lock_trade_through_events']+=1;q['qty']=0
        capacity=math.floor(row['amount']/10*self.participation+1e-10);original=capacity;candidates=[]
        for v in list(self.tasks.values()):
            q=v.active.get(leg)
            if not q or q['activation']>=t or q['qty']<=0:continue
            side=q['side'];rescue=q['phase']=='rescue'
            if (rescue or self.opposite_aggressor) and row['direction']!=('sell' if side==1 else 'buy'):continue
            if rescue:
                # One future opposite-aggressor print, adverse tick-rounded price.
                price=row['price']*(1+side*self.slip_bp/10000)
                price=(math.ceil(price/2.5-1e-10) if side==1 else math.floor(price/2.5+1e-10))*2.5
                if not (price<=q['limit'] if side==1 else price>=q['limit']):continue
            else:
                if not (row['price']<q['limit'] if side==1 else row['price']>q['limit']):continue
                price=q['limit']
            candidates.append((-side*q['limit'],q['activation'],v.id,v,q,price))
        for _,_,_,v,q,price in sorted(candidates,key=lambda x:x[:3]):
            if not capacity:break
            if v.id not in self.tasks or v.active.get(leg) is not q:continue
            undo=q.get('rescue_action')=='undo';rescue=q['phase']=='rescue'
            if rescue:
                allowance=self.gap(v)
                if not allowance:continue
                lead=0 if v.fills[0]>v.fills[1] else 1
                if (leg==lead)!=undo:continue
            else:
                allowance=(v.total if self.cells[v.cell]['direction'] else q['total'])-v.fills[leg]
            left=min(capacity,q['qty'],allowance)
            while left>0 and v.id in self.tasks:
                gap=v.fills[1-leg]-v.fills[leg]
                n=min(left,gap) if gap>0 and not undo else left
                self.fill(v,leg,q,n,row,undo,price if rescue else None)
                capacity-=n;left-=n
            if rescue:
                q['qty']=0;self.cancel(v,t,'rescue_result')
        assert 0<=original-capacity<=original

    def run(self,events):
        previous=self.measures(self.start);self.timeline.append(previous);last_bin=0
        groups=iter(itertools.groupby(events,key=lambda r:r['timestamp']))
        current=next(groups,None)
        while current is not None or self.timers or self.queue:
            market_t=current[0] if current is not None else self.end
            timer_t=self.timers[0][0] if self.timers else self.end
            quote_t=self.queue[0][0] if self.queue else self.end
            t=min(market_t,timer_t,quote_t)
            if t>=self.end:break
            assert t>=self.last_t
            dt=(t-self.last_t)/1000;self.unpaired_seconds+=dt*(previous['unpaired_btc']>0)
            self.backlog_btc_seconds+=dt*previous['backlog_btc'];self.backlog_seconds+=dt*(previous['backlog_usd']>0)
            self.weighted_exposure_seconds+=dt*previous['inventory_btc'];self.last_t=t;self.clock=t
            if t//DAY!=self.last_day:
                self.daily.append(dict(previous,date=utc(self.last_day*DAY)[:10]));self.last_day=t//DAY
            before=len(self.fills);self.arrivals(t)
            # Prints at the exact cancellation timestamp remain eligible: a
            # conservative boundary convention. New orders at t cannot fill at t.
            if market_t==t:
                group=list(current[1])
                for row in group:self.execute_print(row)
            while self.timers and self.timers[0][0]==t:
                _,_,kind,payload=heapq.heappop(self.timers);self.timer_event(t,kind,payload)
            self.arrivals(t,True)
            if market_t==t:
                for row in group:
                    leg=self.symbols.index(row['instrument_name']);self.latest[leg]=row
                    self.spot=float(row['index_price']);self.index_time=t
                current=next(groups,None)
            self.snapshot(t);previous=self.measures(t)
            bin_=(t-self.start)//900000
            if len(self.fills)!=before or bin_!=last_bin:
                self.timeline.append(previous);last_bin=bin_
        self.unpaired_seconds+=(self.end-self.last_t)/1000*(previous['unpaired_btc']>0)
        self.backlog_btc_seconds+=(self.end-self.last_t)/1000*previous['backlog_btc']
        self.backlog_seconds+=(self.end-self.last_t)/1000*(previous['backlog_usd']>0)
        self.weighted_exposure_seconds+=(self.end-self.last_t)/1000*previous['inventory_btc']
        final=self.measures(self.end);self.timeline.append(final)
        self.daily.append(dict(final,date=utc(self.last_day*DAY)[:10]))
        for v in self.tasks.values():
            if v.episode:
                e=dict(v.episode);e.update(duration_seconds=(self.end-e['start_ms'])/1000,
                    residual_contracts=self.gap(v),outcome='unresolved_at_end');self.episodes.append(e)
        waits=[m['hedge_wait_ms']/1000 for m in self.matched]
        def quantile(xs,q):
            if not xs:return None
            ys=sorted(xs);return ys[min(len(ys)-1,int(q*(len(ys)-1)))]
        return dict(scenario=self.name,symbols=self.symbols,start=utc(self.start),end_exclusive=utc(self.end),
            delay_ms=self.delay,cancel_delay_ms=self.delay,reconcile_ack_delay_ms=self.delay,
            participation=self.participation,opposite_aggressor=self.opposite_aggressor,
            async_cap_btc=self.async_cap_btc,allocation_btc_per_level=.1,max_reserved_allocation_btc=.6,
            freshness_seconds=None if self.fresh_ms is None else self.fresh_ms/1000,
            index_freshness_seconds=None if self.fresh_ms is None else self.index_ms/1000,
            carry_apr_reference=self.carry_apr,relaxation_enabled=self.relax,
            max_relaxation_price_bp=self.concession_bp,rescue_enabled=self.rescue,
            rescue_policy='cost_comparison_next_opposite_print_proxy' if self.rescue else 'none',
            rescue_slippage_bp=self.slip_bp,rescue_reference_age_limit_seconds=60,
            rescue_index_age_limit_seconds=5,rescue_price_cap_bp=10,rescue_attempt_window_ms=1000,
            fee_assumptions_bp=dict(passive=1,rescue=5),
            timing_model='immediate_observation_and_fill_notice_delayed_cancel_and_ack',
            direction_lock_model='ideal_shared_slot_lock_with_trade_through_diagnostic',
            max_lead_fill_btc=self.max_lead_fill_btc,peak_execution_backlog_btc=self.peak_backlog_btc,
            peak_single_task_backlog_btc=self.peak_task_backlog_btc,**self.counts,
            completed_cycles=len(self.cycles),final=final,max_drawdown_gross_btc=self.drawdown[0],
            peak_inventory_btc=self.peak_gross,unpaired_hours=self.unpaired_seconds/3600,
            average_inventory_btc=self.weighted_exposure_seconds/((self.end-self.start)/1000),
            average_backlog_btc=self.backlog_btc_seconds/((self.end-self.start)/1000),
            backlog_hours=self.backlog_seconds/3600,
            matched_wait_p50_seconds=quantile(waits,.5),matched_wait_p95_seconds=quantile(waits,.95),
            matched_wait_max_seconds=max(waits,default=None),
            matched_within_5_seconds_fraction=sum(x<=5 for x in waits)/len(waits) if waits else None,
            matched_volume_within_5_seconds_fraction=(sum(m['usd_face'] for m in self.matched if m['hedge_wait_ms']<=5000)/sum(m['usd_face'] for m in self.matched)) if self.matched else None,
            episode_count=len(self.episodes),unresolved_episodes=sum(e['outcome']=='unresolved_at_end' for e in self.episodes),
            episode_outcomes=dict(Counter(e['outcome'] for e in self.episodes)))

def scenarios():
    for delay in [500,10]:
        for policy,kwargs in [
            ('control',{}),('fresh60',dict(fresh_seconds=60)),
            ('relax',dict(relax=True)),('timed',dict(relax=True,rescue=True)),
            ('combined',dict(fresh_seconds=60,relax=True,rescue=True))]:
            yield f'{policy}_{delay}ms',dict(delay=delay,**kwargs)
    for age in [5,30,300]:
        yield f'combined_fresh{age}_500ms',dict(delay=500,fresh_seconds=age,relax=True,rescue=True)
    yield 'combined_carry_500ms',dict(delay=500,fresh_seconds=60,relax=True,rescue=True,carry_apr=True)

def save_policy(out,r,summary,coverage):
    save_run(out,r,summary,coverage)
    write_csv(Path(out)/'episodes.csv.gz',r.episodes)
    write_csv(Path(out)/'cancellations.csv.gz',r.cancellations)
