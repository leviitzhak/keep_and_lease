"""Explicit research timelines with disk-backed ordering and original provenance."""
from dataclasses import replace
import gzip
import heapq
import json
from pathlib import Path
import sqlite3
import tempfile
import time

POLICY_VERSION = 'btc-ordering-v1'
POLICIES = ('sequence', 'timestamp')


def sorted_raw_futures(path, *, contiguous=True):
    """Validate sequence identity before sorting; never hold a whole tape in RAM."""
    with tempfile.TemporaryDirectory(prefix='btc-sort-') as root:
        db = sqlite3.connect(str(Path(root)/'raw.sqlite'))
        try:
            db.execute('PRAGMA cache_size=-8192')
            db.execute('PRAGMA max_page_count=131072')
            db.execute('PRAGMA temp_store=FILE')
            db.execute('CREATE TABLE trades(seq INTEGER PRIMARY KEY,id TEXT UNIQUE,ts INTEGER,raw TEXT)')
            previous = None
            with gzip.open(path, 'rt') as stream:
                for line in stream:
                    row = json.loads(line)
                    seq = row['trade_seq']
                    if previous is not None and (seq<=previous or contiguous and seq!=previous+1):
                        raise ValueError('Source trade sequence gap or duplicate')
                    previous = seq
                    db.execute('INSERT INTO trades VALUES(?,?,?,?)',(seq,row['trade_id'],row['timestamp'],line))
            db.commit()
            for raw, in db.execute('SELECT raw FROM trades ORDER BY ts,seq'):
                yield raw
        finally:
            db.close()


class OrderedTradeStore:
    """Normalize futures over the entire pinned range; stream spot separately.

    The SQL prefix maximum crosses UTC days and selected-window boundaries.
    This is an assumed timeline, not a reconstruction of historical arrival time.
    """
    def __init__(self, store, policy, progress=None):
        if policy not in POLICIES:
            raise ValueError('Unknown trade ordering policy')
        self.store, self.policy = store, policy
        self.report = dict(policy=policy, policy_version=POLICY_VERSION,
                           delayed_trades=0, max_delay_us=0, delayed_btc_volume=0.0)
        self.progress = progress or (lambda *_: None)
        self.preparation_seconds = 0.0
        self.temp = None
        self.db = None

    def __getattr__(self, name):
        return getattr(self.store, name)

    def close(self):
        if self.db is not None: self.db.close(); self.db = None
        if self.temp is not None: self.temp.cleanup(); self.temp = None

    def __del__(self):
        self.close()

    def prepare(self):
        if self.db is not None: return
        from btc_trade_backtest import us_time
        started = time.monotonic()
        self.temp = tempfile.TemporaryDirectory(prefix='btc-order-')
        db = self.db = sqlite3.connect(str(Path(self.temp.name)/'futures.sqlite'))
        db.execute('PRAGMA cache_size=-8192')
        db.execute('PRAGMA max_page_count=131072')
        db.execute('PRAGMA journal_mode=OFF')
        db.execute('PRAGMA temp_store=FILE')
        db.execute('CREATE TABLE raw(symbol TEXT,seq INTEGER,raw_us INTEGER,price REAL,btc REAL,side TEXT,id TEXT,executable INTEGER,PRIMARY KEY(symbol,seq),UNIQUE(symbol,id))')
        symbols = set(self.source_manifest['futures'])
        count = 0
        for event in self.store.trades(symbols=symbols):
            if event.sequence is None:
                raise ValueError('Sequence-preserving replay requires source sequence metadata')
            db.execute('INSERT INTO raw VALUES(?,?,?,?,?,?,?,?)',
                (event.symbol,event.sequence,event.us,event.price,event.btc,event.side,event.identifier,event.executable))
            count += 1
            if count%8192 == 0:
                self.store.check_cancelled()
                self.progress('trade_ordering',f'Indexed {count:,} futures records across the pinned range')
        # One causal anchor per instrument, including any captured pre-range
        # sequence envelope prefix. It initializes time only and is never emitted.
        db.execute('CREATE TABLE anchors(symbol TEXT PRIMARY KEY,us INTEGER)')
        for symbol,info in self.source_manifest['futures'].items():
            seed = info.get('seed')
            anchor = max(seed['timestamp']*1000 if seed else -1,
                         (info.get('ordering_prefix_max_ms', info.get('discrepancy',{}).get('prefix_max_timestamp_ms')) or -1)*1000)
            db.execute('INSERT INTO anchors VALUES(?,?)',(symbol,anchor))
        db.execute('CREATE TABLE ordered AS SELECT raw.*, MAX(MAX(raw_us) OVER (PARTITION BY raw.symbol ORDER BY seq ROWS UNBOUNDED PRECEDING), anchors.us) AS effective_us FROM raw JOIN anchors ON raw.symbol=anchors.symbol')
        db.execute('CREATE INDEX effective_order ON ordered(effective_us,symbol,seq)')
        db.commit()
        delayed, maximum, volume = db.execute('SELECT COUNT(*),MAX(effective_us-raw_us),SUM(btc) FROM ordered WHERE effective_us>raw_us').fetchone()
        self.report.update(ordering_database_bytes=(Path(self.temp.name)/'futures.sqlite').stat().st_size, dataset_futures=count,dataset_delayed_trades=delayed,
                           dataset_max_delay_us=maximum or 0,dataset_delayed_btc_volume=volume or 0)
        self.preparation_seconds = time.monotonic()-started
        self.store.check_cancelled()

    def trades(self, *, start_us=None, end_us=None, symbols=None, batch_rows=8192):
        if self.policy == 'timestamp' or symbols == {'SPOT'}:
            return self.store.trades(start_us=start_us,end_us=end_us,symbols=symbols,batch_rows=batch_rows)
        self.prepare()
        from trade_replay import Trade
        def futures():
            query = 'SELECT effective_us,symbol,price,btc,side,id,executable,raw_us,seq FROM ordered WHERE 1=1'
            params = []
            if start_us is not None: query+=' AND effective_us>=?';params.append(start_us)
            if end_us is not None: query+=' AND effective_us<?';params.append(end_us)
            query+=' ORDER BY effective_us,symbol,seq'
            for us,symbol,price,btc,side,identifier,executable,raw_us,seq in self.db.execute(query,params):
                if symbols is None or symbol in symbols:
                    yield Trade(us,symbol,price,btc,side,identifier,bool(executable),raw_us,seq)
        streams = [futures()]
        if symbols is None or 'SPOT' in symbols:
            streams.append(self.store.trades(start_us=start_us,end_us=end_us,symbols={'SPOT'},batch_rows=batch_rows))
        return heapq.merge(*streams,key=lambda e:(e.us,e.symbol,e.sequence or 0))

    def window_report(self, start, end):
        if self.policy == 'sequence':
            self.prepare()
            n,maximum,volume = self.db.execute('SELECT COUNT(*),MAX(effective_us-raw_us),SUM(btc) FROM ordered WHERE effective_us>=? AND effective_us<? AND effective_us>raw_us',(start,end)).fetchone()
            self.report.update(delayed_trades=n,max_delay_us=maximum or 0,delayed_btc_volume=volume or 0)
        return dict(self.report)
