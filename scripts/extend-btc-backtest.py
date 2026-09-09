#!/usr/bin/env python3
"""Extend a saved CLI backtest into a NEW output directory using its last checkpoint.

Parent must contain parameters.json, audit/ and checkpoints/. The manifest and
engine must be unchanged. At most the tail after the last checkpoint is replayed.
"""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest_audit import AuditCollection, DirectoryAuditStore
from replay_checkpoints import DirectoryCheckpoints
from replay_extension import extend_checkpoint
from trade_data_store import ParquetTradeStore
import btc_trade_backtest as replay


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--dataset', required=True)
    p.add_argument('--end', required=True)
    args = p.parse_args()
    if args.output.resolve() == args.parent.resolve() or args.output.exists():
        raise ValueError('Choose a new extension output directory')
    old = json.loads((args.parent/'parameters.json').read_text())
    new = dict(old, backtest_end=args.end)
    store = ParquetTradeStore(args.dataset)
    coverage = dict(id='extended-research',start=store.source_manifest['start'],
                    end=store.source_manifest['end'],maximum_decisions=16_000_000)
    replay.validate(new, coverage=coverage)
    parent = DirectoryCheckpoints(args.parent/'checkpoints').latest()
    audit = AuditCollection(DirectoryAuditStore(args.output/'audit'))
    audit.checkpoints = DirectoryCheckpoints(args.output/'checkpoints')
    extend_checkpoint(parent, old, new, store.manifest_bytes, ROOT,
                      DirectoryAuditStore(args.parent/'audit'), audit.store, audit.checkpoints)
    (args.output/'parameters.json').write_text(json.dumps(new, indent=2)+'\n')
    result = replay.run(new, ROOT, audit, lambda stage, detail: print(stage+': '+detail, flush=True),
                        store=store, coverage=coverage)
    (args.output/'result.json').write_text(json.dumps(result)+'\n')


if __name__ == '__main__':
    main()
