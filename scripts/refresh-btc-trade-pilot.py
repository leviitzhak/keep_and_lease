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
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
        if stamp(info["creation_timestamp"]) >= hi or stamp(info["expiration_timestamp"]) <= lo:
            return None
        path, meta_path = out / (symbol + ".jsonl.gz"), out / (symbol + ".meta.json")
        if path.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta["sha256"] != digest(path) or meta["start_ms"] != lo or meta["end_ms"] != hi:
                raise ValueError("Cached futures file mismatch")
            if "verified_last_seq" not in meta:
                tail = api("get_last_trades_by_instrument_and_time", instrument_name=symbol,
                           start_timestamp=lo, end_timestamp=hi - 1, count=1000, sorting="desc")["trades"]
                expected_last = max((x["trade_seq"] for x in tail), default=None)
                if meta["last_seq"] != expected_last:
                    raise ValueError(f"Cached trade tail incomplete: {symbol}")
                meta["verified_last_seq"] = expected_last
                meta_path.write_text(json.dumps(meta, indent=2) + "\n")
            return meta
        seed = api("get_last_trades_by_instrument_and_time", instrument_name=symbol,
                   end_timestamp=lo - 1, count=1000, sorting="desc")["trades"]
        seed.sort(key=lambda x: x["trade_seq"], reverse=True)
        result = api("get_last_trades_by_instrument_and_time", instrument_name=symbol,
                     start_timestamp=lo, end_timestamp=hi - 1, count=1000, sorting="asc")
        # Timestamp sorting does not order equal-millisecond trades by sequence.
        # Bound subsequent pages by sequence, including the first page, so a
        # timestamp tie split across pages cannot silently discard a print.
        first_seq = min((x["trade_seq"] for x in result["trades"]), default=None)
        if seed:
            first_seq = seed[0]["trade_seq"] + 1
        if first_seq is not None:
            page_lo, page_hi = first_seq, first_seq + 899
            result = api("get_last_trades_by_instrument", instrument_name=symbol,
                         start_seq=page_lo, end_seq=page_hi, count=1000, sorting="asc")
        count, raw_bytes, previous_seq, previous_ts = 0, 0, None, None
        temporary = path.with_suffix(".part")
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            while True:
                # The history server may include neighboring trades sharing the
                # endpoint timestamp. Over-fetch, then enforce exact seq bounds.
                trades = sorted((x for x in result["trades"]
                                 if page_lo <= x["trade_seq"] <= page_hi),
                                key=lambda x: x["trade_seq"]) if first_seq is not None else []
                for trade in trades:
                    ts, seq = trade["timestamp"], trade["trade_seq"]
                    if ts >= hi:
                        break
                    if ts < lo or seq != (previous_seq + 1 if previous_seq is not None else first_seq):
                        raise ValueError(f"Trade sequence/window gap: {symbol}: {previous_seq} -> {seq}")
                    if previous_ts is not None and ts < previous_ts:
                        raise ValueError(f"Unsorted trade timestamps: {symbol}")
                    row = json.dumps(trade, separators=(",", ":")) + "\n"
                    stream.write(row)
                    raw_bytes += len(row.encode())
                    count += 1
                    previous_seq, previous_ts = seq, ts
                if not trades or trades[-1]["timestamp"] >= hi:
                    break
                page_lo, page_hi = previous_seq + 1, previous_seq + 900
                result = api("get_last_trades_by_instrument", instrument_name=symbol,
                             start_seq=page_lo, end_seq=page_hi,
                             count=1000, sorting="asc")
        temporary.replace(path)
        tail = api("get_last_trades_by_instrument_and_time", instrument_name=symbol,
                   start_timestamp=lo, end_timestamp=hi - 1, count=1000, sorting="desc")["trades"]
        expected_last = max((x["trade_seq"] for x in tail), default=None)
        if previous_seq != expected_last:
            raise ValueError(f"Missing end of trade window: {symbol}")
        meta = dict(path=path.name, sha256=digest(path), rows=count, jsonl_bytes=raw_bytes,
                    gzip_bytes=path.stat().st_size, seed=seed[0] if seed else None,
                    start_ms=lo, end_ms=hi, expiry=info["expiration_timestamp"],
                    last_seq=previous_seq, verified_last_seq=expected_last, last_ms=previous_ts)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        print(json.dumps({symbol: {k: meta[k] for k in ("rows", "gzip_bytes")}}), flush=True)
        return meta

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
    manifest = dict(schema_version=1, start=start.isoformat(), end=end.isoformat(),
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
