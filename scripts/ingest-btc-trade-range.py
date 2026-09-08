#!/usr/bin/env python3
"""Resumable daily ingestion; publish a range only after every day validates.

Local work is disk-backed and limited to one raw day at a time. --upload uses
existing ADC and create-only bucket writes; it does not alter IAM or activation.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trade_data_store import ParquetTradeStore, convert, sha256


def invoke(script, *args):
    subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)], check=True)


def range_manifest(days):
    if not days:
        raise ValueError("No completed days")
    futures = {}
    discrepancy_evidence = []
    for day, store in days:
        for symbol, info in store.source_manifest["futures"].items():
            if 'discrepancy' in info:
                discrepancy_evidence.append(dict(day=day,instrument=symbol,**info['discrepancy'],
                    evidence_files=[{**entry,'uri':'gs://keep-and-lease-market-data/btc/raw/sha256/'+entry['sha256']+'/'+Path(entry['path']).name} for entry in info.get('evidence_files',[])]))
            if symbol not in futures:
                futures[symbol] = {"expiry": info["expiry"], "ordering_prefix_max_ms": info.get("discrepancy",{}).get("prefix_max_timestamp_ms")}
                seed = info.get("seed")
                if seed and seed["timestamp"] < int(datetime.fromisoformat(days[0][0]).replace(tzinfo=timezone.utc).timestamp()) * 1000:
                    futures[symbol]["seed"] = seed
            elif futures[symbol]["expiry"] != info["expiry"]:
                raise ValueError("Contract expiry differs across days")
            if "settlement" in info:
                futures[symbol]["settlement"] = info["settlement"]
    return dict(schema_version=1, source_manifest=dict(start=days[0][1].source_manifest["start"],
                end=days[-1][1].source_manifest["end"], futures=futures, discrepancy_evidence=discrepancy_evidence), partitions=[],
                daily_datasets=[dict(start=store.source_manifest["start"], end=store.source_manifest["end"],
                                     manifest_sha256=hashlib.sha256(store.manifest_bytes).hexdigest(),
                                     local_path="days/"+day) for day, store in days])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True, help="Exclusive UTC date")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--assemble-only", action="store_true", help="Require verified daily upload receipts; no downloads")
    args = parser.parse_args()
    if not 1 <= (args.end-args.start).days <= 90:
        raise ValueError("Select between one and ninety whole UTC days")
    args.output.mkdir(parents=True, exist_ok=True)
    days = []
    day = args.start
    while day < args.end:
        label = day.isoformat()
        raw, parquet = args.output / "raw" / label, args.output / "days" / label
        receipt = args.output / "receipts" / (label+".json")
        if receipt.exists() and args.upload:
            item = json.loads(receipt.read_text())
            store = ParquetTradeStore(item["uri"])
            if hashlib.sha256(store.manifest_bytes).hexdigest() != item["manifest_sha256"]:
                raise ValueError("Published daily receipt mismatch")
        else:
            if args.assemble_only:
                raise ValueError("Missing verified daily receipt: "+label)
            if not (parquet / "manifest.json").exists():
                invoke("refresh-btc-trade-pilot.py", "--date", label, "--output", raw)
                # An interrupted conversion never published its manifest.
                if parquet.exists():
                    shutil.rmtree(parquet)
                convert(raw, parquet)
            store = ParquetTradeStore(parquet)
            # Compare every raw event to Parquet before publication, even on retries.
            evidence = args.output / "evidence" / (label+".json")
            evidence.parent.mkdir(parents=True, exist_ok=True)
            invoke("check-btc-parquet-equivalence.py", "--data", raw, "--parquet", parquet, "--output", evidence)
            if args.upload:
                invoke("upload-btc-trade-parquet.py", "--data", raw, "--parquet", parquet, "--execute")
                digest = hashlib.sha256(store.manifest_bytes).hexdigest()
                uri = "gs://keep-and-lease-market-data/btc/trades/v1/"+digest
                # Verify GCS bytes against the raw stream before recording completion.
                invoke("check-btc-parquet-equivalence.py", "--data", raw, "--parquet", uri, "--output", evidence)
                receipt.parent.mkdir(parents=True, exist_ok=True)
                receipt.write_text(json.dumps(dict(uri=uri, manifest_sha256=digest))+"\n")
                shutil.rmtree(raw)
                shutil.rmtree(parquet)
        days.append((label, store))
        print(json.dumps(dict(completed_day=label, days_completed=len(days), total_days=(args.end-args.start).days)), flush=True)
        day += timedelta(days=1)
    value = range_manifest(days)
    if (value["source_manifest"]["start"][:10] != args.start.isoformat() or
            value["source_manifest"]["end"][:10] != args.end.isoformat()):
        raise ValueError("Receipts do not match the requested period")
    encoded = (json.dumps(value, indent=2)+"\n").encode()
    temporary = args.output / "manifest.pending"
    temporary.write_bytes(encoded)
    # Coverage validation uses the same reader as the worker before publishing.
    check = object.__new__(ParquetTradeStore)
    check.manifest, check.source_manifest = value, value["source_manifest"]
    check._validate_range()
    temporary.replace(args.output / "manifest.json")
    digest = hashlib.sha256(encoded).hexdigest()
    if args.upload:
        from google.cloud import storage
        from google.api_core.exceptions import PreconditionFailed
        name = "btc/trades/ranges/"+digest+"/manifest.json"
        blob = storage.Client().bucket("keep-and-lease-market-data").blob(name)
        try:
            blob.upload_from_string(encoded, if_generation_match=0, checksum="crc32c", content_type="application/json")
        except PreconditionFailed:
            if blob.download_as_bytes(checksum="crc32c") != encoded:
                raise ValueError("Immutable range manifest conflict") from None
        print(json.dumps(dict(uri="gs://keep-and-lease-market-data/"+name.removesuffix('/manifest.json'), manifest_sha256=digest)), flush=True)


if __name__ == "__main__":
    main()
