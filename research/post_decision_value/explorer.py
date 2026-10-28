"""Local, training-free state explorer. Run with python -m ...explorer --open."""
import argparse
import base64
from copy import deepcopy
from dataclasses import asdict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import math
import os
from pathlib import Path
import pickle
import secrets
import tarfile
import threading
import time
import urllib.request
import webbrowser
import zipfile

from .accounting import Cashflow, Goal, Ledger, Position
from .engine import Delays, Engine, Instruction, Order, admissible, post_decision
from .liquidation import ClosingRule, liquidate
from .market_simulation import DAY, MarketBundle, SimulationConfig, digest, generate, load_payload
from .robust_rollout import CampaignBudget, Controller, rollout
from .treasury_fixtures import action_provider, finite_toy_optimum, fixture_engine, hold_reference, scenario_set
from .treasury_model import DIAGNOSTIC_VERSION, FEATURE_VERSION, TreasuryValue, encode

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).with_name('explorer_web')
ARCHIVE = 'treasury-maxmin-v1.tar.gz'
ARCHIVE_SHA = 'c417e6b00cfe79cd09faa24a40d1de1190dd69bbf8ffe47fb18344647d8b2c3f'
ARCHIVE_BYTES = 2329910
URL = f'https://raw.githubusercontent.com/leviitzhak/keep_and_lease/cd7839d46ed0a7004546d7d6a6a36844dc959b73/docs/research/post_decision_value/{ARCHIVE}'
BODY_CAP = 8_000_000
MODEL_CAP = 2_000_000
VERSION = 'state-explorer-v1'


def number(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{name} must be finite in [{lo}, {hi}]')
    return value


def integer(value, name, lo, hi):
    number(value, name, lo, hi)
    if type(value) is not int: raise ValueError(name+' must be an integer')
    return value


def clean(value):
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)): return [clean(v) for v in value]
    return value


def budget(config, seconds=8, decisions=200):
    limits = dict(config['limits'], wall_seconds=seconds, decisions=decisions)
    return CampaignBudget(limits)


def read_bundle(blob):
    """Known immutable archive only; read selected members without extraction."""
    if len(blob) != ARCHIVE_BYTES or hashlib.sha256(blob).hexdigest() != ARCHIVE_SHA:
        raise ValueError('Published archive checksum/size mismatch')
    wanted = {'selected-model.pt','configuration.json','identity.json','fixtures.json','inference-manifest.json'}
    files = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as tar:
        members = tar.getmembers()
        if len(members)>500 or sum(m.size for m in members)>512*1024*1024:
            raise ValueError('Archive bounds exceeded')
        for member in members:
            parts = Path(member.name).parts
            if Path(member.name).is_absolute() or '..' in parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe archive entry')
            if len(parts)==2 and parts[1] in wanted:
                if parts[1] in files or member.size>MODEL_CAP: raise ValueError('Invalid inference member')
                files[parts[1]] = tar.extractfile(member).read()
    if set(files)!=wanted: raise ValueError('Missing inference members')
    return files


def load_inference(blob):
    """Tensor-only loader, no optimizer construction, RNG mutation, or training."""
    import torch
    if len(blob)>MODEL_CAP: raise ValueError('Checkpoint byte cap')
    if not zipfile.is_zipfile(io.BytesIO(blob)):raise ValueError('A modern tensor-only checkpoint ZIP is required')
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        members=archive.infolist()
        if len(members)>256 or sum(m.file_size for m in members)>8_000_000:
            raise ValueError('Checkpoint uncompressed byte/member cap')
    try:
        payload = torch.load(io.BytesIO(blob), map_location='cpu', weights_only=True)
    except (pickle.UnpicklingError, RuntimeError, EOFError) as error:
        raise ValueError('Invalid tensor-only checkpoint') from error
    if not isinstance(payload,dict):raise ValueError('Checkpoint mapping required')
    if payload.get('schema')!='treasury-scalar-checkpoint-v1' or payload.get('feature_version')!=FEATURE_VERSION:
        raise ValueError('Only treasury-scalar-checkpoint-v1 is supported; legacy targets are not relabeled')
    if payload.get('target_version') not in (DIAGNOSTIC_VERSION, 'sampled-maxmin-sequential-close-v1'):
        raise ValueError('Unsupported or unfitted target')
    digest(payload['identity'])  # Metadata must be finite JSON, never executable objects.
    if not isinstance(payload.get('label_identity'),str):raise ValueError('Explicit label identity required')
    width = integer(payload.get('width'), 'width', 1, 128)
    with torch.random.fork_rng(devices=[]):
        model = TreasuryValue(width)
    model.load_state_dict(payload['state'])
    if any(not torch.isfinite(v).all() for v in model.state_dict().values()):
        raise ValueError('Nonfinite checkpoint')
    if (model.x_scale<=0).any() or model.y_scale<=0: raise ValueError('Invalid normalization')
    model.identity = payload['identity']; model.target_version = payload['target_version']
    model.label_identity = payload.get('label_identity','unspecified'); model.eval()
    return model


class Explorer:
    def __init__(self, cache=None):
        self.cache = Path(cache or Path(os.environ.get('LOCALAPPDATA', Path.home()/'.cache'))/'keep-and-lease-explorer')
        files = read_bundle((ROOT/'docs/research/post_decision_value'/ARCHIVE).read_bytes())
        self.config = json.loads(files['configuration.json'])
        fixtures = json.loads(files['fixtures.json'])
        # Deliberately exclude the untouched fresh-test split from this explorer.
        self.cases = {c['id']:c for split in ('train','validation') for c in fixtures[split]}
        self.published = files
        self.model = load_inference(files['selected-model.pt'])
        if self.model.identity != json.loads(files['identity.json']): raise ValueError('Checkpoint source mismatch')
        self.manifest = json.loads(files['inference-manifest.json'])
        self.checkpoint_id = 'published-diagnostic'
        self.model_sha = hashlib.sha256(files['selected-model.pt']).hexdigest()
        self.custom = None
        self.markets = {}
        self.lock = threading.Lock()

    def checkpoint(self):
        return dict(id=self.checkpoint_id, sha256=self.model_sha, target=self.model.target_version,
                    feature_version=FEATURE_VERSION, label_identity=self.model.label_identity,
                    acceptance=self.manifest.get('acceptance'), manifest=self.manifest,
                    status='Diagnostic only · repeated-policy gate failed' if self.checkpoint_id=='published-diagnostic'
                    else 'User checkpoint · acceptance unverified', url=URL, archive_sha256=ARCHIVE_SHA)

    def bootstrap(self):
        return dict(version=VERSION, checkpoint=self.checkpoint(), simulation_enabled=False,
                    cases=[dict(id=c['id'], category=c['category'], split=c['split']) for c in self.cases.values()],
                    simulation_defaults=asdict(SimulationConfig()), benchmark=dict(BTC=1.,USD=10000.),
                    limits=dict(surface_cells=63, replay_decisions=200, replay_seconds=8, input_bytes=BODY_CAP),
                    checkpoints=[dict(id='published-diagnostic',label='Treasury diagnostic · published')]+
                    ([dict(id='user',label='Loaded local scalar checkpoint')] if self.custom else []))

    def select_checkpoint(self, request):
        which = request.get('id','published-diagnostic')
        if which=='published-diagnostic':
            self.model = load_inference(self.published['selected-model.pt'])
            self.manifest = json.loads(self.published['inference-manifest.json'])
            self.model_sha = hashlib.sha256(self.published['selected-model.pt']).hexdigest()
        elif which=='user' and self.custom:
            self.model,self.manifest,self.model_sha = self.custom
        else: raise ValueError('Unknown checkpoint')
        self.checkpoint_id=which
        return self.checkpoint()

    def import_checkpoint(self, request):
        blob=base64.b64decode(request['base64'], validate=True)
        actual=hashlib.sha256(blob).hexdigest()
        if actual!=request.get('sha256'): raise ValueError('Local checkpoint checksum mismatch')
        model=load_inference(blob)
        manifest=dict(acceptance='unverified', source_identity=model.identity,
                      active_target_version=model.target_version, trained_domain='User supplied; not independently verified',
                      normalization='checkpoint buffers', duration_ignored=True)
        self.custom=(model,manifest,actual)
        return self.select_checkpoint(dict(id='user'))

    def download(self):
        # Fixed allowlisted immutable URL. Download is user-triggered, never startup.
        with urllib.request.urlopen(URL, timeout=20) as response:
            if response.geturl()!=URL: raise ValueError('Unexpected checkpoint redirect')
            blob=response.read(ARCHIVE_BYTES+1)
        files=read_bundle(blob)
        self.cache.mkdir(parents=True,exist_ok=True)
        target=self.cache/ARCHIVE
        temporary=self.cache/(ARCHIVE+'.tmp')
        temporary.write_bytes(blob); temporary.replace(target)
        self.published=files
        return dict(verified=True, bytes=len(blob),sha256=ARCHIVE_SHA,checkpoint=self.select_checkpoint({}))

    def market(self, request):
        if request.get('kind','fixture') not in ('fixture','simulation','import'):
            raise ValueError('Unknown market mode')
        if request.get('kind')=='simulation':
            bundle=generate(request.get('configuration',{}))
        elif request.get('kind')=='import':
            bundle=load_payload(request['bundle'])
        else:
            case=self.cases[request.get('id',next(iter(self.cases)))]
            engine=fixture_engine(case,self.config)
            scenario=scenario_set(case,[211],self.config,'explorer')[0]
            from .engine import Trade
            seed=Trade(case['start']-1000,'BILL',case['price'],1000,'buy','seed',100000.,'treasury')
            bundle=MarketBundle(engine.instruments,[seed],scenario['trades'],case['start'],case['decision_end'],
                                case['label_end'],metadata=dict(id=case['id'],source_kind='synthetic_fixture',
                                scenario_law=scenario['law']))
        key=digest(bundle.payload())
        # Only built-in, unchanged fixtures get independent toy references.
        case=case if request.get('kind','fixture')=='fixture' else None
        self.markets[key]=(bundle,case)
        if len(self.markets)>8: del self.markets[next(iter(self.markets))]
        return dict(id=key,source=bundle.metadata,start=bundle.start,decision_end=bundle.decision_end,
                    label_end=bundle.label_end,instruments={s:asdict(i) for s,i in bundle.instruments.items()},
                    rows=len(bundle.trades),funding_events=len(bundle.funding),
                    defaults=dict(time=bundle.start,horizon_ms=bundle.decision_end-bundle.start,
                                  balances=dict(BTC=1.,USD=10000.),collateral=dict(BTC=0.,USD=9999. if case and case['category']=='cash_constrained' else 0.),
                                  positions={},flows=[],orders=[],action=dict(kind='wait',orders=[],targets=[])))

    def instruction(self, data, instruments, now):
        orders=[]
        rows=data.get('orders',[]); targets=data.get('targets',[])
        if len(rows)>6 or len(targets)>6: raise ValueError('At most six order variants')
        for n,row in enumerate(rows):
            symbol=row['symbol']
            if symbol not in instruments: raise ValueError('Unknown instrument')
            identifier=str(row.get('identifier',f'new-{n}'))
            if not 1<=len(identifier)<=80: raise ValueError('Order ID length')
            orders.append(Order(identifier,symbol,number(row['quantity'],'quantity',-1e6,1e6),
                                number(row['limit'],'limit',.000001,1e8),created=now))
        if any(not isinstance(t,str) or len(t)>80 for t in targets): raise ValueError('Invalid target')
        return Instruction(data.get('kind','wait'),tuple(orders),tuple(targets))

    def state(self, request):
        bundle,case=self.markets[request['market_id']]
        state=request['state']; now=integer(state['time'],'time',bundle.start,bundle.decision_end)
        h=integer(state['horizon_ms'],'horizon_ms',0,bundle.decision_end-now)
        seed=integer(request.get('seed',211),'execution seed',0,2**32-1)
        goal=Goal(dict(BTC=1.,USD=10000.),now+h,max(bundle.label_end,max(i.expiry for i in bundle.instruments.values())),mode='weighted_growth')
        e=Engine(bundle.instruments,Ledger(dict(BTC=1.,USD=10000.)),goal,seed,
                 Delays(**self.config['delays']),participation=1.,event_cap=30000)
        e.seed_market(bundle.seeds,bundle.start); e.add_tape(bundle.trades);e.add_funding(bundle.funding)
        # Market-only history. The edited portfolio describes a hypothetical NOW,
        # not a backdated purchase and not cash received from historical holdings.
        e.advance(now)
        p=Ledger({c:number(state['balances'][c],c,0,1e8) for c in ('BTC','USD')})
        p.collateral={c:number(state.get('collateral',{}).get(c,0),c+' collateral',0,p.balances[c]) for c in ('BTC','USD')}
        p.settled_ids=e.hidden.ledger.settled_ids.copy()
        positions=state.get('positions',{})
        if len(positions)>16: raise ValueError('Position cap')
        for s,v in positions.items():
            ins=bundle.instruments[s];q=number(v['quantity'],'inventory',-1e6,1e6)
            if not q:continue
            if ins.payoff=='spot':raise ValueError('SPOT holdings belong in BTC balance')
            if now>=ins.expiry or (not ins.is_future and q<0) or abs(ins.round_quantity(q)-q)>1e-8:
                raise ValueError('Expired, short cash asset or non-native inventory')
            p.positions[s]=Position(q,number(v['basis'],'basis',.000001,1e8))
        flows=state.get('flows',[])
        if len(flows)>16: raise ValueError('Liability cap')
        for n,f in enumerate(flows):
            if f['currency'] not in ('BTC','USD'): raise ValueError('Unknown cash currency')
            p.flows.append(Cashflow(f'edited-{n}',integer(f['date'],'liability date',now+1,bundle.label_end),
                                   f['currency'],number(f['amount'],'liability',-1e8,0),'liability'))
        e.hidden.ledger=p.clone();e.observable.ledger=p.clone();e.hidden.failures=[]
        e.hidden.min_headroom={'BTC':math.inf,'USD':math.inf};e.hidden.min_funding=math.inf;e._check()
        e.observable.failure_observed=bool(e.hidden.failures)
        rows=state.get('orders',[])
        if len(rows)>6: raise ValueError('Order count cap')
        for row in rows:
            a=self.instruction(dict(kind='create',orders=[row]),bundle.instruments,now)
            ok,reason=admissible(e.observable,a,e.goal,e.instruments)
            if not ok: raise ValueError('Existing order '+a.orders[0].identifier+': '+reason)
            status=row.get('status','working')
            if status=='pending':e.submit(a)
            elif status=='working':
                e.observable=post_decision(e.observable,a,e.instruments)
                e.observable.pending.pop()
                o=a.orders[0];e.hidden.orders[o.identifier]=o;e.observable.confirmed[o.identifier]=o
            else: raise ValueError('Order status must be working or pending')
        action=self.instruction(state.get('action',{}),e.instruments,now)
        return e,action,h,bundle,case

    def prediction(self,e,a,h):
        ok,reason=admissible(e.observable,a,e.goal,e.instruments)
        if not ok:return dict(admissible=False,reason=reason,value=None,features=None)
        try:
            fs=encode(e.observe(),a,e.goal,e.instruments,h)
            value=float(self.model.predict([fs])[0])
            return dict(admissible=True,reason=reason,value=value,features=fs,
                        feature_sha256=digest(fs),target=self.model.target_version,
                        validation='Unvalidated edited state until a matching diagnostic reference is available')
        except (ValueError,KeyError) as error:
            return dict(admissible=True,reason=reason,value=None,features=None,unavailable=str(error))

    def reference(self,e,a,h,case):
        unavailable=dict(value=None,kind='unavailable',reason='Outside independent diagnostic reference scope')
        if (not case or self.model.target_version!=DIAGNOSTIC_VERSION or
                self.model.label_identity!=json.loads(self.published['inference-manifest.json'])['label_identity']):return unavailable
        obs=e.observable;p=obs.ledger
        if (obs.time!=case['start'] or obs.uncertain or obs.pending or p.flows or p.debt_principal or
                p.balances['BTC']!=1. or p.collateral['BTC'] or p.collateral['USD']!= (9999. if case['category']=='cash_constrained' else 0.) or
                obs.failure_observed):return unavailable
        q=0.;inventory=False
        if a.kind=='wait' and not p.positions and p.balances['USD']==case['usd']:
            return dict(value=0.,kind='exact diagnostic hold',scope='Unchanged base-only cash, wait forever')
        if (a.kind=='create' and len(a.orders)==1 and not p.positions and p.balances['USD']==case['usd'] and
                h==case['decision_end']-case['start']):
            o=a.orders[0]
            if o.symbol!='BILL' or o.limit!=case['price'] or o.quantity not in self.config['quantities'] or case['category']=='cash_constrained':return unavailable
            q=o.quantity
        elif a.kind=='wait' and h==0 and set(p.positions)=={'BILL'}:
            pos=p.positions['BILL'];q=pos.quantity;inventory=True
            if q not in self.config['quantities'] or pos.basis!=case['price'] or abs(p.balances['USD']-(case['usd']-q*case['price']*(1+case['fee_bps']/10000)))>1e-7:return unavailable
        else:return unavailable
        ref=hold_reference(case,q,h,inventory=inventory)
        return dict(value=ref['utility'],kind='exact diagnostic boundary' if inventory else 'exact diagnostic purchase then hold',
                    scope='Independent fixed-fixture cash arithmetic; same diagnostic target',outcome=ref)

    def evaluate(self,request):
        e,a,h,bundle,case=self.state(request)
        prediction=self.prediction(e,a,h)
        ref=self.reference(e,a,h,case) if prediction['admissible'] else dict(value=None,kind='unavailable')
        error=prediction['value']-ref['value'] if prediction['value'] is not None and ref['value'] is not None else None
        if error is not None:
            prediction['validation']=('Matching diagnostic reference; repeated policy still failed' if self.checkpoint_id=='published-diagnostic'
                                      else 'Matching diagnostic reference; checkpoint acceptance remains unverified')
        boundary_state=deepcopy(e)
        if prediction['admissible']:boundary_state.submit(a)
        boundary=liquidate(boundary_state,bundle.trades,bundle.label_end,ClosingRule(**self.config['closing']))
        toy=None
        if case and e.now==case['start'] and not e.observable.uncertain and not e.hidden.ledger.positions and not e.hidden.ledger.flows and e.hidden.ledger.balances=={'BTC':1.,'USD':10000.} and e.hidden.ledger.collateral=={'BTC':0.,'USD':9999. if case['category']=='cash_constrained' else 0.}:
            toy=finite_toy_optimum(case,h,self.config,budget(self.config))
        return clean(dict(prediction=prediction,reference=ref,signed_error=error,liquidation=boundary,
                          toy_optimum=toy,sampled_search=dict(value=None,reason='No matching completed rollout target for edited states'),
                          observable=asdict(e.observe()),instruments={s:asdict(i) for s,i in e.instruments.items()},
                          benchmark=asdict(e.goal),checkpoint=self.checkpoint(),source=bundle.metadata,
                          horizon_ms=h,interpretation='Liquidation uses ex-post subsequent trades on the current portfolio with atomic order cancellation; duration ignored. It is not a model input.'))

    def surface(self,request):
        e,_,h,bundle,case=self.state(request)
        quantities=request['quantities'];prices=request['prices'];symbol=request['symbol']
        if symbol not in e.instruments or not quantities or not prices or len(quantities)*len(prices)>63:
            raise ValueError('Surface requires 1..63 cells and a known instrument')
        cells=[];b=budget(self.config)
        for q in quantities:
            for price in prices:
                b.check()
                action=self.instruction(dict(kind='create',orders=[dict(identifier='surface-new',symbol=symbol,quantity=q,limit=price)]),e.instruments,e.now) if q else Instruction()
                pred=self.prediction(e,action,h);ref=self.reference(e,action,h,case) if pred['admissible'] else dict(value=None,kind='unavailable')
                cells.append(dict(quantity=q,price=price,**{k:v for k,v in pred.items() if k!='features'},
                                  reference=ref['value'],error=pred['value']-ref['value'] if pred['value'] is not None and ref['value'] is not None else None))
        ranked=sorted((c for c in cells if c['value'] is not None),key=lambda c:c['value'],reverse=True)
        return dict(cells=cells,ranking=ranked[:10],horizon_ms=h,reference_scope='Matching diagnostic reference only; blank is unavailable')

    def replay(self,request):
        e,a,h,bundle,case=self.state(request)
        ok,reason=admissible(e.observable,a,e.goal,e.instruments)
        if not ok:raise ValueError(reason)
        policy=request.get('policy','hold')
        if policy not in ('hold','network'):raise ValueError('Unsupported policy')
        if policy=='network':
            if not case or set(e.instruments)!={'BILL'}:raise ValueError('Network replay is limited to the declared BILL fixture action domain')
            encode(e.observe(),a,e.goal,e.instruments,h)
        # The submitted post-state is the fixed anchor, before any fill/report.
        e.submit(a)
        from .decision_clock import DecisionSchedule
        schedule=DecisionSchedule(e,e.now+h,**self.config['clock']);schedule.accept()
        limit=integer(request.get('max_decisions',200),'max_decisions',1,200)
        b=budget(self.config,decisions=limit)
        # Hold uses no network/candidates. A single jump still processes every
        # exact exchange event; the decision cap cannot alter a hold trajectory.
        if policy=='hold':
            e.event_trace=[];e.event_cap=min(e.event_cap,e.hidden.processed+30000)
            processed=e.hidden.processed
            try:
                e.advance(e.now+h)
                b.event(e.hidden.processed-processed)
                outcome=liquidate(e,bundle.trades,bundle.label_end,ClosingRule(**self.config['closing']),b)
                if e.hidden.processed-processed+len(outcome['trace'])>30000:
                    outcome=dict(done=False,truncated=True,reason='replay_event_cap_including_tail')
            except RuntimeError as error:
                outcome=dict(done=False,truncated=True,reason=str(error))
            decisions=[];events=e.event_trace;fills=e.hidden.fills
        else:
            branch=rollout(e,h,bundle.scenario(request.get('seed',211)),Controller(101),self.model,encode,
                           action_provider(self.config),self.config,b)
            outcome=branch['outcome'];decisions=branch['decisions'];events=branch['events'];fills=branch['fills']
        return clean(dict(outcome=outcome,decisions=decisions,events=events,fills=fills,policy=policy,
                          horizon_ms=h,countdown='fixed deadline; physical elapsed time',seed=request.get('seed',211),
                          source=bundle.metadata,market_sha256=bundle.payload()['sha256'],
                          checkpoint=self.checkpoint(),budgets=b.summary(),
                          interpretation='One realized path, not a max-min value or uncertainty estimate. Hidden events are diagnostic output only.'))

    def dispatch(self,path,data):
        routes={'/api/market':self.market,'/api/evaluate':self.evaluate,'/api/surface':self.surface,
                '/api/replay':self.replay,'/api/checkpoint/select':self.select_checkpoint,
                '/api/checkpoint/import':self.import_checkpoint,'/api/checkpoint/download':lambda _:self.download(),
                '/api/market/export':lambda d:self.markets[d['market_id']][0].payload()}
        if path not in routes:raise ValueError('Unknown API route')
        return routes[path](data)


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,app):
        if address[0]!='127.0.0.1':raise ValueError('Explorer binds IPv4 loopback only')
        self.app=app;self.token=secrets.token_urlsafe(32)
        super().__init__(address,Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def setup(self):
        super().setup();self.connection.settimeout(25)
    def send(self,status,body,kind='application/json'):
        if kind=='application/json':body=json.dumps(clean(body),allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers();self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
    def do_GET(self):
        if not self.valid_host():return self.send(403,dict(error='Invalid loopback host'))
        if self.path=='/api/bootstrap':
            with self.server.app.lock: data=self.server.app.bootstrap()
            return self.send(200,dict(**data,token=self.server.token))
        files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        if self.path not in files:return self.send(404,dict(error='Not found'))
        name,kind=files[self.path];self.send(200,(STATIC/name).read_bytes(),kind)
    def do_POST(self):
        origin=f'http://127.0.0.1:{self.server.server_port}'
        if (not self.valid_host() or self.headers.get('Origin') not in (None,origin) or
                self.headers.get('X-Explorer-Token')!=self.server.token):
            return self.send(403,dict(error='Same-origin explorer token required'))
        if self.headers.get('Content-Type')!='application/json':return self.send(415,dict(error='JSON required'))
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=BODY_CAP:return self.send(413,dict(error='Request byte cap'))
            data=json.loads(self.rfile.read(size),parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            if not isinstance(data,dict):raise ValueError('JSON object required')
            if not self.server.app.lock.acquire(blocking=False):return self.send(409,dict(error='Another calculation is running'))
            try:result=self.server.app.dispatch(self.path,data)
            finally:self.server.app.lock.release()
            self.send(200,result)
        except (ValueError,KeyError,TypeError,RuntimeError,OverflowError,AttributeError,IndexError) as error:
            self.send(400,dict(error=str(error)))
        except (OSError,EOFError) as error:
            self.send(503,dict(error='Local file or download unavailable: '+str(error)))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8765)
    p.add_argument('--open',action='store_true');p.add_argument('--cache');args=p.parse_args()
    import torch
    torch.set_num_threads(1)
    app=Explorer(args.cache);server=Server(('127.0.0.1',args.port),app)
    url=f'http://127.0.0.1:{server.server_port}'
    print(f'Treasury explorer: {url}\nDiagnostic checkpoint; no training. Ctrl+C to stop.',flush=True)
    if args.open:webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
