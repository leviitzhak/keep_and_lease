#!/usr/bin/env python3
"""Download one matched UTC day of Binance spot and Deribit dated-future trades.

Raw, reproducible research cache only; never changes the active minute provider.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deribit_trade_ingest import download_future as reconcile_future

HISTORY = "https://history.deribit.com/api/v2/public/"


def fetch(url):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt == 4:
                raise
            time.sleep(min(8, 2 ** attempt))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def api(method, **params):
    url = HISTORY + method + "?" + urllib.parse.urlencode(params)
    value = json.loads(fetch(url))
    if "error" in value:
        raise ValueError(value["error"])
    return value["result"]


def stamp(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-06-25")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    start = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    lo, hi = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    out = args.output or ROOT / "work/btc-trade-pilot" / args.date
    out.mkdir(parents=True, exist_ok=True)
    name = f"BTCUSDT-trades-{args.date}.zip"
    url = "https://data.binance.vision/data/spot/daily/trades/BTCUSDT/" + name
    checksum = fetch(url + ".CHECKSUM").decode().split()[0]
    archive = out / name
    if not archive.exists():
        # Stream the large archive; never retain it alongside parsed trades.
        temporary = archive.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=90) as response, temporary.open("wb") as stream:
            while block := response.read(1024 * 1024):
                stream.write(block)
        temporary.replace(archive)
    if digest(archive) != checksum:
        raise ValueError("Binance checksum mismatch")
    with zipfile.ZipFile(archive) as zipped:
        member, = zipped.infolist()
        count, first, last, previous_id = 0, None, None, None
        with zipped.open(member) as stream:
            for row in csv.reader(io.TextIOWrapper(stream)):
                trade_id, ts = int(row[0]), int(row[4])
                # Archive timestamps changed from milliseconds to microseconds in 2025.
                ts = ts * 1000 if ts < 10 ** 14 else ts
                if not lo * 1000 <= ts < hi * 1000 or (last is not None and ts < last):
                    raise ValueError("Spot timestamps out of order/window")
                if previous_id is not None and trade_id != previous_id + 1:
                    raise ValueError("Spot trade ID gap")
                first = ts if first is None else first
                last, previous_id = ts, trade_id
                count += 1
        spot = dict(url=url, sha256=checksum, archive_bytes=archive.stat().st_size,
                    csv_bytes=member.file_size, rows=count, first_us=first, last_us=last,
                    path=name)
    print(json.dumps({"spot": spot}), flush=True)
    source = json.loads((ROOT / "public/data/btc/intraday/deribit_1m/manifest.json").read_text())
    entries = source["contracts"]
    if isinstance(entries, list):
        entries = {x["instrument_name"]: x for x in entries}
    futures = {}
    def download_future(symbol, info):
        return reconcile_future(api, symbol, info, lo, hi, out)

    with ThreadPoolExecutor(max_workers=3) as executor:
        pending = {executor.submit(download_future, symbol, info): symbol for symbol, info in sorted(entries.items())
                   if stamp(info["creation_timestamp"]) < hi and stamp(info["expiration_timestamp"]) > lo}
        for future in as_completed(pending):
            futures[pending[future]] = future.result()
    futures = dict(sorted(futures.items()))
    # Published BTC/USD delivery prices are used only at the exact contract expiry.
    expiring = {s: info for s, info in futures.items() if lo <= stamp(info["expiry"]) < hi}
    if expiring:
        delivery_url = "https://www.deribit.com/api/v2/public/get_delivery_prices?index_name=btc_usd&count=1000&offset=0"
        response = fetch(delivery_url)
        delivery = json.loads(response)["result"]["data"]
        prices = {row["date"]: row["delivery_price"] for row in delivery}
        for symbol, info in expiring.items():
            price = prices.get(info["expiry"][:10])
            if price is None or not price > 0:
                raise ValueError(f"Missing verified delivery price: {symbol}")
            info["settlement"] = dict(time=info["expiry"], price=price, source=delivery_url,
                                      response_sha256=hashlib.sha256(response).hexdigest(),
                                      record={"date": info["expiry"][:10], "delivery_price": price})
    evidence_files = [entry for item in futures.values() for entry in item.get('evidence_files', [])]
    manifest = dict(evidence_files=evidence_files, schema_version=1, start=start.isoformat(), end=end.isoformat(),
                    spot=spot, futures=futures, futures_source=HISTORY,
                    assumptions=["USDT/USD=1, unmeasured", "Inverse quotes proxy regular futures prices",
                                 "Inverse trade amount is USD face; BTC volume = amount / price",
                                 "Trade history is not historical order-book depth"])
    if expiring:
        manifest["delivery_price_response"] = response.decode()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(str(out / "manifest.json"))


if __name__ == "__main__":
    main()
