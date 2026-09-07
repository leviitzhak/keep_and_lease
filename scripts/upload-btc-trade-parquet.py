#!/usr/bin/env python3
"""Publish verified raw/Parquet pilot files to an immutable GCS prefix.

Requires existing Application Default Credentials with bucket object-create and
read access. Does not change IAM, obtain credentials or replace existing objects.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trade_data_store import ParquetTradeStore, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--bucket", default="keep-and-lease-market-data")
    parser.add_argument("--execute", action="store_true", help="Upload after all local hashes pass")
    args = parser.parse_args()
    store = ParquetTradeStore(args.parquet)
    manifest_hash = hashlib.sha256(store.manifest_bytes).hexdigest()
    prefix = "btc/trades/v1/" + manifest_hash
    if sha256(args.data / "manifest.json") != store.manifest["source_manifest_sha256"]:
        raise ValueError("Source manifest mismatch")
    files = []
    for item in [store.source_manifest["spot"], *store.source_manifest["futures"].values()]:
        files.append((args.data / item["path"], "btc/raw/sha256/" + item["sha256"] + "/" + Path(item["path"]).name, item["sha256"]))
    source_hash = store.manifest["source_manifest_sha256"]
    files.append((args.data / "manifest.json", "btc/raw/sha256/" + source_hash + "/manifest.json", source_hash))
    for item in store.manifest["partitions"]:
        files.append((args.parquet / item["path"], prefix + "/" + item["path"], item["sha256"]))
    files.append((args.parquet / "manifest.json", prefix + "/manifest.json", manifest_hash))
    for path, _, expected in files:
        if sha256(path) != expected:
            raise ValueError(f"Local checksum mismatch: {path.name}")
    plan = dict(uri=f"gs://{args.bucket}/{prefix}", files=len(files),
                bytes=sum(p.stat().st_size for p, _, _ in files), manifest_published_last=True)
    print(json.dumps(plan, indent=2), flush=True)
    if not args.execute:
        return
    from google.cloud import storage
    from google.api_core.exceptions import PreconditionFailed
    bucket = storage.Client().bucket(args.bucket)
    for path, relative, expected in files:
        blob = bucket.blob(relative, chunk_size=8 * 1024 * 1024)
        blob.metadata = {"sha256": expected}
        try:
            blob.upload_from_filename(str(path), if_generation_match=0, checksum="crc32c")
        except PreconditionFailed:
            # A retry may encounter an existing object. Verify bytes before reuse.
            blob.reload()
            digest = hashlib.sha256()
            with blob.open("rb", chunk_size=1024 * 1024) as stream:
                while block := stream.read(1024 * 1024):
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError(f"Existing cloud object differs: {relative}")
        print(json.dumps({"uploaded_or_verified": relative}), flush=True)


if __name__ == "__main__":
    main()
