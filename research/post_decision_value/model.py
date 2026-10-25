"""One shared continuation, independent scalar expected-utility regression head."""
from dataclasses import asdict
import hashlib
import math
import time
from pathlib import Path
import numpy as np
import torch
from torch import nn

CURRENCIES = ('BTC', 'USD')


def identity(symbol):
    value = int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4], 'big') / 2**32
    return math.sin(2*math.pi*value), math.cos(2*math.pi*value)


def features(obs, goal, instruments):
    """Only observable arguments; fixed economic scaling, no fitted future stats."""
    ref = goal.reference['BTC']
    hold = obs.ledger.holdings(instruments)
    g = [obs.time/1e12, (goal.horizon-obs.time)/86400000, (goal.resolution-obs.time)/31557600000,
         (obs.time-obs.last_decision)/60000, goal.drawdown, goal.failure_penalty, goal.composition_penalty,
         float(goal.mode=='target'), float(goal.mode=='btc'), goal.tolerance,
         (goal.target_deadline-obs.time)/86400000, float(goal.maintain_band),
         obs.ledger.credit_limit/ref, obs.ledger.debt_principal/ref, len(obs.pending)/6,
         float(obs.failure_observed)]
    for c in CURRENCIES:
        scale = goal.scale(c)
        g.extend([goal.initial[c]*goal.reference[c]/ref, hold[c]/scale, goal.floor(c)/scale,
                  obs.ledger.balances[c]/scale, obs.ledger.collateral[c]/scale,
                  obs.reserved[c]/scale, goal.target[c], goal.reference[c]/ref])
    items = []
    for symbol, ins in sorted(instruments.items()):
        market = obs.market.get(symbol)
        pos = obs.ledger.positions.get(symbol)
        prefix = [*identity(symbol), (ins.expiry-obs.time)/31557600000, float(ins.payoff=='inverse'),
                  ins.tick/ref, ins.lot if ins.payoff=='linear' else ins.lot/ref,
                  ins.fee_bps/100, ins.margin_fraction,
                  ins.btc(pos.quantity,pos.basis)/goal.scale('BTC') if pos else 0.,
                  pos.basis/ref if pos else 0., market['price']/ref if market else 0.,
                  min(100., (obs.time-market['received'])/60000) if market else 100.,
                  float(market is None)]
        items.append(prefix+[0.]*7)
        for oid, variants in sorted(obs.uncertain.items()):
            for o in variants:
                if o.symbol != symbol:
                    continue
                pending = [p for p in obs.pending if oid in p['instruction']['targets'] or any(v['identifier']==oid for v in p['instruction']['orders'])]
                kind = pending[-1]['instruction']['kind'] if pending else ''
                items.append(prefix+[ins.btc(o.quantity,o.limit)/goal.scale('BTC')/.02, 100*(o.limit/(market['price'] if market else ref)-1),
                                     (obs.time-o.created)/60000, float(oid in obs.confirmed),
                                     float(kind=='create'),float(kind=='amend'),float(kind in ('cancel','emergency'))])
    for flow in obs.ledger.flows:
        items.append([*identity(flow.identifier),(flow.date-obs.time)/31557600000,
                      float(flow.currency=='BTC'),flow.amount/goal.scale(flow.currency),float(flow.kind=='debt')]+[0.]*14)
    if len(items)>32:
        raise ValueError('Item capacity exceeded; do not silently drop held instruments')
    history=[]
    for row in obs.history[-64:]:
        history.append([*identity(row['symbol']), row['price']/ref,row['index']/ref,
                        math.log1p(row['amount'])/20, 1. if row['side']=='buy' else -1.,
                        (obs.time-row['received'])/60000,(row['received']-row['time'])/1000])
    if not history:
        history=[[0.]*8]
    return dict(global_=g, items=items or [[0.]*20], history=history,
                initial=[goal.initial[c] for c in CURRENCIES], scales=[goal.scale(c) for c in CURRENCIES])


def batch(features_list):
    n=len(features_list)
    ni=max(len(f['items']) for f in features_list)
    nh=max(len(f['history']) for f in features_list)
    items=torch.zeros(n,ni,20); hist=torch.zeros(n,nh,8)
    imask=torch.ones(n,ni,dtype=torch.bool); hmask=torch.ones(n,nh,dtype=torch.bool)
    for i,f in enumerate(features_list):
        items[i,:len(f['items'])]=torch.tensor(f['items'])
        hist[i,:len(f['history'])]=torch.tensor(f['history'])
        imask[i,:len(f['items'])]=False; hmask[i,:len(f['history'])]=False
    return torch.tensor([f['global_'] for f in features_list],dtype=torch.float32),items,hist,imask,hmask


class ValueNetwork(nn.Module):
    def __init__(self, width=64, layers=2, heads=4, history_mode='transformer'):
        super().__init__()
        self.configuration=dict(width=width,layers=layers,heads=heads,history_mode=history_mode)
        self.history_mode=history_mode
        self.item=nn.Sequential(nn.Linear(20,width),nn.Tanh(),nn.Linear(width,width))
        self.hist=nn.Linear(8,width)
        self.position=nn.Parameter(torch.zeros(64,width))
        layer=nn.TransformerEncoderLayer(width,heads,dim_feedforward=width*2,dropout=0.,batch_first=True,activation='gelu')
        self.encoder=nn.TransformerEncoder(layer,layers,enable_nested_tensor=False)
        self.readout=nn.Sequential(nn.Linear(width*2+32,width),nn.Tanh(),nn.Linear(width,5))
        self.register_buffer('label_mean',torch.zeros(3))
        self.register_buffer('label_scale',torch.ones(3))
        self.continuation='unfitted'

    def history_encoding(self, hist, mask):
        embedded=self.hist(hist)+self.position[:hist.shape[1]]
        if self.history_mode=='mlp':
            return embedded
        causal=torch.triu(torch.ones(hist.shape[1],hist.shape[1],dtype=torch.bool),diagonal=1)
        return self.encoder(embedded,mask=causal,src_key_padding_mask=mask)

    def forward(self, data):
        global_,items,hist,imask,hmask=data
        encoded=self.item(items).masked_fill(imask.unsqueeze(-1),0.)
        ipool=encoded.sum(1)/(~imask).sum(1,keepdim=True)
        eh=self.history_encoding(hist,hmask)
        last=(~hmask).sum(1)-1
        hp=eh[torch.arange(eh.shape[0]),last]
        return self.readout(torch.cat((global_,ipool,hp),dim=1))

    def predict(self, fs):
        self.eval()
        with torch.no_grad():
            z=self(batch(fs))
            y=(z[:,:3]*self.label_scale+self.label_mean).numpy()
            flags=torch.sigmoid(z[:,3:]).numpy()
        initial=np.array([f['initial'] for f in fs]); scales=np.array([f['scales'] for f in fs])
        return dict(objective=y[:,0], terminal_holdings=initial+y[:,1:3]*scales,
                    failure=flags[:,0], attainment=flags[:,1],continuation=self.continuation)


def labels(records):
    if not records or any(not r['outcome']['done'] or r['outcome']['truncated'] for r in records):
        raise ValueError('Only complete outcomes can be regressed')
    versions={r['continuation'] for r in records}
    if len(versions)!=1:
        raise ValueError('Mixed continuations require an explicitly separate pretraining run')
    y=[]
    for r in records:
        o=r['outcome']
        y.append([o['utility'],o['growth']['BTC'],o['growth']['USD'],float(o['failed']),float(o['attained'])])
    return np.array(y,dtype=np.float32),versions.pop()


def fit(model, records, *, updates=200, seed=7, optimizer=None, rng=None, wall_seconds=1200, normalize=True):
    if not 0<=updates<=2000 or wall_seconds>1200:
        raise ValueError('Training cap exceeded')
    y,continuation=labels(records)
    model.continuation=continuation
    if normalize:
        model.label_mean.copy_(torch.tensor(y[:,:3].mean(0)))
        model.label_scale.copy_(torch.tensor(np.maximum(y[:,:3].std(0),1e-4)))
    target=torch.tensor(y)
    optimizer=optimizer or torch.optim.Adam(model.parameters(),lr=.001)
    rng=rng or np.random.default_rng(seed)
    started=time.monotonic(); losses=[]
    for _ in range(updates):
        if time.monotonic()-started>wall_seconds:
            break
        ids=rng.choice(len(records),min(32,len(records)),replace=False)
        inputs=batch([records[i]['features'] for i in ids])
        t=target[ids]; normalized=(t[:,:3]-model.label_mean)/model.label_scale
        model.train(); optimizer.zero_grad()
        pred=model(inputs)
        loss=((pred[:,:3]-normalized)**2).mean()+.05*nn.functional.binary_cross_entropy_with_logits(pred[:,3:],t[:,3:])
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite model loss')
        loss.backward(); nn.utils.clip_grad_norm_(model.parameters(),5.); optimizer.step()
        losses.append(float(loss.detach()))
    return optimizer,rng,dict(updates=len(losses),seconds=time.monotonic()-started,
                              first_loss=losses[0] if losses else None,last_loss=losses[-1] if losses else None,
                              continuation=continuation,normalization='training-only label moments')


def save_model(path, model, optimizer, rng, identity):
    payload=dict(configuration=model.configuration,model=model.state_dict(),optimizer=optimizer.state_dict(),
                 numpy_rng=rng.bit_generator.state,torch_rng=torch.get_rng_state(),identity=identity,
                 continuation=model.continuation)
    tmp=Path(str(path)+'.tmp'); torch.save(payload,tmp); tmp.replace(path)


def load_model(path, expected_identity):
    # Trusted project checkpoint only; tensor-only loader rejects arbitrary code.
    p=torch.load(path,map_location='cpu',weights_only=True)
    if p['identity']!=expected_identity:
        raise ValueError('Checkpoint identity mismatch')
    model=ValueNetwork(**p['configuration']);model.load_state_dict(p['model']);model.continuation=p['continuation']
    optimizer=torch.optim.Adam(model.parameters(),lr=.001);optimizer.load_state_dict(p['optimizer'])
    rng=np.random.default_rng();rng.bit_generator.state=p['numpy_rng'];torch.set_rng_state(p['torch_rng'])
    return model,optimizer,rng
