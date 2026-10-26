"""Lazy causal reader of the completed logical union; no built-in network access.

Callers supply a bounded existing-object getter. The default getter is local-cache
only and fails on missing data. Daily overlay sources are provenance, never read
again as executable prints. Consumers choose contracts using known listing data.
"""
import gzip
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
from .data import FLAGS
from .engine import Trade


def local_getter(root):
    root=Path(root).resolve()
    def get(key):
        path=(root/key).resolve()
        if not path.is_relative_to(root):raise ValueError('Object path outside cache')
        return path.read_bytes()
    return get


class LogicalArchive:
    def __init__(self,manifest,get):
        if manifest.get('status')!='COMPLETE_LOGICAL_UNION' or manifest.get('source_payoff')!='inverse':raise ValueError('Unsupported logical union')
        self.manifest=manifest;self.get=get
        keys=manifest['canonical_receipt_keys']
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate canonical source')
        self.by_symbol={}
        for key in keys:
            match=re.search(r'/receipts/([^/]+)/(\d+)-(\d+)\.json$',key)
            if not match:raise ValueError('Invalid canonical receipt identity')
            symbol,lo,hi=match.groups();self.by_symbol.setdefault(symbol,[]).append((int(lo),int(hi),key))
        for symbol,chunks in self.by_symbol.items():
            chunks.sort()
            if any(hi<lo for lo,hi,_ in chunks) or any(a[1]+1!=b[0] for a,b in zip(chunks,chunks[1:])):
                raise ValueError('Canonical sequence gap/overlap: '+symbol)
        self.pins={r['key']:r for r in manifest.get('read_object_pins',[])}
        for r in manifest.get('metadata_pins',[]):self.pins[r['key']]=r

    @classmethod
    def open(cls,path,get,expected_sha256=None):
        raw=Path(path).read_bytes()
        if str(path).endswith('.gz'):raw=gzip.decompress(raw)
        if expected_sha256 and hashlib.sha256(raw).hexdigest()!=expected_sha256:raise ValueError('Logical manifest hash mismatch')
        return cls(json.loads(raw),get)

    def read(self,key,sha=None,size=None):
        pin=self.pins.get(key,{})
        sha=sha or pin.get('sha256');size=size if size is not None else pin.get('bytes')
        raw=self.get(key)
        if sha and hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Canonical object hash mismatch')
        if size is not None and len(raw)!=size:raise ValueError('Canonical object byte count mismatch')
        return raw

    def instrument_metadata(self):
        pin=next(p for p in self.manifest['metadata_pins'] if p['key'].endswith('/plan-reconciled-v2.json'))
        return json.loads(self.read(pin['key']))['instruments']

    def _stream(self,symbol,start,end,anchor):
        chunks=self.by_symbol[symbol];first,last=chunks[0][0],chunks[-1][1]
        if anchor is None:
            if first!=1:raise ValueError('Verified missing-prefix anchor required: '+symbol)
            anchor=(0,0)
        prior_seq,available=anchor
        if not first-1<=prior_seq<=last:raise ValueError('Anchor outside canonical range')
        for lo,hi,key in chunks:
            if hi<=prior_seq:continue
            receipt=json.loads(self.read(key))
            if (receipt['status'],receipt['instrument'],receipt['first_seq'],receipt['last_seq'],receipt['rows'])!=('COMPLETE',symbol,lo,hi,hi-lo+1):
                raise ValueError('Canonical receipt mismatch')
            objects=[o for o in receipt['objects'] if o['key'].endswith('/trades.jsonl.gz')]
            if len(objects)!=1:raise ValueError('Ambiguous canonical trade object')
            obj=objects[0];raw=gzip.decompress(self.read(obj['key'],obj['sha256'],obj['bytes']))
            lines=raw.splitlines()
            if len(lines)!=hi-lo+1:raise ValueError('Canonical raw row count mismatch')
            seen=set()
            for index,line in enumerate(lines):
                r=json.loads(line);seq=r['trade_seq'];identifier=str(r['trade_id'])
                if r['instrument_name']!=symbol or seq!=lo+index or identifier in seen:raise ValueError('Canonical native identity mismatch')
                seen.add(identifier)
                if seq<=prior_seq:continue
                if not isinstance(r.get('timestamp'),int) or r['timestamp']<=0:raise ValueError('Invalid native timestamp blocks causal replay')
                available=max(available,r['timestamp'])
                if available>=end:return
                if available<start:continue
                if r.get('direction') not in ('buy','sell') or not all(isinstance(r.get(k),(int,float)) and math.isfinite(r[k]) and r[k]>0 for k in ('price','amount','index_price')):continue
                executable=available==r['timestamp'] and not any(r.get(k) for k in FLAGS)
                trade=Trade(available,symbol,r['price'],r['amount'],r['direction'],identifier,r['index_price'],executable=executable,source_time=r['timestamp'])
                yield available,symbol,seq,trade

    def trades(self,start,end,*,symbols,prefix_anchors=None):
        if start>=end or len(symbols)!=len(set(symbols)):raise ValueError('Invalid replay window/universe')
        anchors=prefix_anchors or {}
        streams=[self._stream(s,start,end,anchors.get(s)) for s in sorted(symbols)]
        for _,_,_,trade in heapq.merge(*streams,key=lambda r:r[:3]):yield trade

