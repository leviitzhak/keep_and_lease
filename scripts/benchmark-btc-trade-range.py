#!/usr/bin/env python3
"""Measure one continuous 500 ms replay at the documented 1/7/30/90-day gates.

No activation or timeout changes. Full audits stream to the supplied local disk
or, with --gcs-audit, the authorized market validation bucket. Reports are compact.
"""
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import resource
import re
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest_audit import AuditCollection, DirectoryAuditStore
import btc_trade_backtest as replay
from replay_checkpoints import DirectoryCheckpoints, fingerprint
from trade_data_store import ParquetTradeStore


def main():
    from server.audit_limits import configure_audit_limits
    configure_audit_limits()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--days", type=int, choices=[1, 7, 30, 90], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ordering", choices=["sequence", "timestamp"], default="sequence")
    parser.add_argument("--interval", type=float, default=.5)
    parser.add_argument("--gcs-audit", action="store_true")
    parser.add_argument("--checkpoint-id", help="Stable 32-hex validation ID for a workflow retry")
    parser.add_argument("--expected-manifest-sha", help="Require the reviewed range manifest hash")
    parser.add_argument("--max-wall-seconds", type=float, default=0, help="Yield successfully at a durable checkpoint after this budget")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    store = ParquetTradeStore(args.dataset)
    if args.expected_manifest_sha and hashlib.sha256(store.manifest_bytes).hexdigest() != args.expected_manifest_sha:
        raise ValueError("Benchmark manifest differs from the reviewed range")
    if args.checkpoint_id and not re.fullmatch("[0-9a-f]{32}", args.checkpoint_id):
        raise ValueError("Invalid validation checkpoint ID")
    source = store.source_manifest
    start = replay.us_time(source["start"])
    end = start + args.days * 86400_000_000
    if end > replay.us_time(source["end"]):
        raise ValueError("Dataset does not cover the benchmark window")
    parameters = json.loads((ROOT / "strategies/research-btc-long-gradual-500ms.json").read_text())["parameters"]
    parameters["trade_ordering"] = args.ordering
    parameters.update(backtest_start=replay.iso_time(start), backtest_end=replay.iso_time(end),
                      execution_interval_seconds=args.interval)
    if args.gcs_audit:
        from google.cloud import storage
        from server.cloud import GcsResultStore
        results = GcsResultStore(storage.Client(), "keep-and-lease-market-data")
        identifier_path = args.output / "validation-job-id.txt"
        if not identifier_path.exists():
            identifier_path.write_text(args.checkpoint_id or uuid.uuid4().hex)
        identifier = identifier_path.read_text().strip()
        if args.checkpoint_id and identifier != args.checkpoint_id:
            raise ValueError("Output folder belongs to a different validation")
        audit_store = results.audit_store(identifier)
        checkpoints = results.checkpoint_store(identifier)
        destination = f"gs://keep-and-lease-market-data/jobs/{identifier}/audit"
    else:
        audit_store = DirectoryAuditStore(args.output / "audit")
        checkpoints = DirectoryCheckpoints(args.output / "checkpoints")
        destination = str(args.output / "audit")
    parameters_path = args.output / 'parameters.json'
    parameters_path.write_text(json.dumps(parameters, indent=2)+'\n')
    report_blob = None
    if args.gcs_audit:
        report_blob = storage.Client().bucket('keep-and-lease-market-data').blob('jobs/'+identifier+'/benchmark-report.json')
        if report_blob.exists():
            encoded = report_blob.download_as_bytes(checksum='crc32c')
            saved = json.loads(encoded)
            if (saved['days'] != args.days or saved['ordering'] != args.ordering or
                    saved.get('fingerprint') != fingerprint(parameters, store.manifest_bytes, ROOT)):
                raise ValueError('Completed report identity differs')
            (args.output/'report.json').write_bytes(encoded)
            print('Reused completed benchmark report', flush=True)
            return
    audit = AuditCollection(audit_store)
    audit.checkpoints = checkpoints
    coverage = dict(id="staged-benchmark", start=source["start"], end=source["end"], maximum_decisions=16_000_000)
    began = time.monotonic()
    class CheckpointYield(Exception):
        pass
    def progress(stage, detail):
        print(stage+': '+detail, flush=True)
        if stage == 'trade_checkpoint' and args.max_wall_seconds and time.monotonic()-began >= args.max_wall_seconds:
            raise CheckpointYield()
    try:
        result = replay.run(parameters, ROOT, audit, progress, store=store, coverage=coverage)
    except CheckpointYield:
        (args.output/'continuation.json').write_text(json.dumps(dict(status='checkpointed',
            wall_seconds=time.monotonic()-began, checkpoint_id=args.checkpoint_id))+'\n')
        return
    datasets = result["audit"]["datasets"]
    report = dict(fingerprint=fingerprint(parameters, store.manifest_bytes, ROOT), manifest_sha256=hashlib.sha256(store.manifest_bytes).hexdigest(), strategy_parameters_sha256=hashlib.sha256(json.dumps({k:v for k,v in parameters.items() if k != "trade_ordering"},sort_keys=True).encode()).hexdigest(),
                  days=args.days, ordering=args.ordering, interval_seconds=args.interval, wall_seconds=time.monotonic()-began,
                  peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                  summary=result["summary"], replay=result["trade_replay"], audit_destination=destination,
                  audit_compressed_bytes=sum(e["compressed_bytes"] for v in datasets.values() for e in v["chunks"]),
                  audit_manifest_bytes=len(json.dumps(result["audit"], separators=(",", ":")).encode()),
                  audit_rows={p: v["rows"] for p, v in datasets.items()},
                  audit_chunk_hashes={p: [e["sha256"] for e in v["chunks"]] for p,v in datasets.items()})
    if report["peak_rss_mib"] + 2*report["replay"]["ordering"].get("ordering_database_bytes",0)/1024**2 > 3584 or len(result["series"]) > 2002:
        raise ValueError("Staged benchmark exceeded worker/plot headroom")
    (args.output / "report.json").write_text(json.dumps(report, indent=2)+"\n")
    if report_blob is not None:
        report_blob.upload_from_string((args.output/'report.json').read_bytes(), if_generation_match=0,
                                       checksum='crc32c', content_type='application/json')
    print(json.dumps({k:report[k] for k in ("days","wall_seconds","peak_rss_mib","audit_compressed_bytes","audit_destination")}))


if __name__ == "__main__":
    main()
