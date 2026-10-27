"""Typed, hash-receipted cash-asset tapes; never turn indicative prices into fills."""
import gzip,hashlib,json,math
from dataclasses import asdict
from pathlib import Path
from .accounting import Instrument
from .engine import Trade


def load_cash_bundle(root,*,byte_cap=8_000_000,row_cap=100000):
    root=Path(root).resolve();raw=(root/'manifest.json').read_bytes();m=json.loads(raw)
    if m.get('schema_version')!=1 or m.get('currency')!='USD':raise ValueError('Explicit USD cash bundle required; no assumed USDT parity')
    instruments={}
    for row in m['instruments']:
        row=dict(row);row['cashflows']=tuple(tuple(v) for v in row.get('cashflows',[]));ins=Instrument(**row)
        if ins.is_future or ins.symbol in instruments:raise ValueError('Unique cash asset identities required')
        instruments[ins.symbol]=ins
    tape=[];byte_count=0;count=0;ids=set();evidence=[]
    for obj in m['objects']:
        path=(root/obj['file']).resolve()
        if not path.is_relative_to(root):raise ValueError('Cash source outside cache')
        kind=obj['kind']
        if kind not in ('observed_trade','indicative_quote','synthetic_fixture') or not obj.get('source_uri'):raise ValueError('Explicit cash source provenance required')
        body=path.read_bytes();byte_count+=len(body)
        if byte_count>byte_cap or len(body)!=obj['bytes'] or hashlib.sha256(body).hexdigest()!=obj['sha256']:raise ValueError('Cash source byte/hash mismatch or budget')
        text=gzip.decompress(body) if path.suffix=='.gz' else body
        if len(text)>64_000_000:raise ValueError('Expanded cash input budget')
        for line in text.splitlines():
            row=json.loads(line);tr=Trade(**row);count+=1
            if count>row_cap:raise ValueError('Cash row budget')
            ins=instruments[tr.symbol];key=(tr.symbol,tr.identifier)
            if key in ids:raise ValueError('Duplicate cash trade identity')
            ids.add(key)
            if tr.time<ins.listed_at or tr.side not in ('buy','sell') or not all(math.isfinite(v) and v>0 for v in (tr.price,tr.amount,tr.index)):
                raise ValueError('Invalid native cash trade')
            if tr.source_payoff!=ins.payoff:raise ValueError('Cash native unit mismatch')
            if tr.source_time is not None and (tr.source_time>tr.time or (tr.source_time<tr.time and tr.executable)):
                raise ValueError('Backdated cash observations cannot authorize retroactive fills')
            if kind=='indicative_quote' and tr.executable:raise ValueError('Indicative quotes cannot authorize execution')
            tape.append(tr)
        evidence.append(obj)
    return instruments,sorted(tape,key=lambda t:(t.time,t.symbol,t.identifier)),dict(
        schema_version=1,manifest_sha256=hashlib.sha256(raw).hexdigest(),files=evidence,
        instruments={s:asdict(i) for s,i in instruments.items()},rows=count,bytes=byte_count,
        currency='USD',interpretation=m.get('interpretation','Explicit source kinds govern fill eligibility'))


def attach_cash_blocks(blocks,instruments,tape):
    """Use only already-available records as seeds; keep all future events hidden."""
    for b in blocks:
        prior={}
        for tr in tape:
            if tr.time<b['start']-10000:prior[tr.symbol]=tr
        eligible=[s for s,i in instruments.items() if i.listed_at<b['start']-10000 and b['start']<i.expiry]
        if any(s not in prior for s in eligible):raise ValueError('Missing observable cash seed')
        b['seeds'].extend(prior[s] for s in eligible)
        b['tape'].extend(t for t in tape if b['start']<=t.time<=b['end'])
        b['tape'].sort(key=lambda t:(t.time,t.symbol,t.identifier))
