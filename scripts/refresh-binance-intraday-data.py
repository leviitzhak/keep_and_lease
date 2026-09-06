#!/usr/bin/env python3
"""Import checksum-verified Binance BTCUSDT 1m archives as a USD spot proxy.

No currency conversion is performed: the research proxy assumes USDT/USD=1.
Activation occurs only after verifying a complete, strictly ordered minute grid.
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import tempfile
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://data.binance.vision/data/spot"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def archive(period, frequency, directory):
    name = f"BTCUSDT-1m-{period}.zip"
    url = f"{BASE}/{frequency}/klines/BTCUSDT/1m/{name}"
    expected = fetch(url + ".CHECKSUM").decode().split()[0]
    path = directory / name
    data = path.read_bytes() if path.exists() else fetch(url)
    if sha256(data) != expected:
        raise ValueError(f"Checksum mismatch: {name}")
    path.write_bytes(data)
    print(f"Verified {name}", flush=True)
    return path, {"url": url, "sha256": expected, "bytes": len(data)}


def download(start, end, directory):
    """Prefer monthly files; missing monthly archives fall back to daily files."""
    result = []
    cursor = start
    while cursor < end:
        following_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        stop = min(following_month, end)
        try:
            result.append(archive(cursor.strftime("%Y-%m"), "monthly", directory))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            days = [cursor + timedelta(days=i) for i in range((stop - cursor).days)]
            with ThreadPoolExecutor(max_workers=4) as executor:
                result.extend(executor.map(
                    lambda day: archive(day.isoformat(), "daily", directory), days))
        cursor = stop
    return result


def minute_rows(paths, start, end):
    start_ms = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()) * 1000
    end_ms = int(datetime.combine(end, datetime.min.time(), timezone.utc).timestamp()) * 1000
    expected = start_ms
    for path in paths:
        with zipfile.ZipFile(path) as archive_file:
            members = [n for n in archive_file.namelist() if n.endswith(".csv")]
            if len(members) != 1:
                raise ValueError(f"Expected one CSV: {path}")
            with archive_file.open(members[0]) as raw:
                for row in csv.reader(io.TextIOWrapper(raw, encoding="utf-8")):
                    stamp = int(row[0])
                    # Binance spot switched from milliseconds to microseconds in 2025.
                    divisor = 1000 if stamp >= 10**14 else 1
                    if stamp % divisor:
                        raise ValueError("Non-millisecond timestamp")
                    stamp //= divisor
                    if not start_ms <= stamp < end_ms:
                        continue
                    if stamp != expected:
                        raise ValueError(f"Missing/duplicate/out-of-order minute: {stamp}; expected {expected}")
                    prices = list(map(float, row[1:5]))
                    volume = float(row[5])
                    trades = int(row[8])
                    if (not all(math.isfinite(p) and p > 0 for p in prices)
                            or not math.isfinite(volume) or volume < 0 or trades < 0
                            or prices[2] > min(prices[0], prices[3])
                            or prices[1] < max(prices[0], prices[3])
                            or int(row[6]) // divisor != stamp + 59999):
                        raise ValueError(f"Invalid candle at {stamp}")
                    label = datetime.fromtimestamp(stamp / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
                    yield [label, "BTC-USDT", *row[1:6], trades]
                    expected += 60000
    if expected != end_ms:
        raise ValueError(f"Incomplete history: stopped at {expected}, expected {end_ms}")


def materialize(inputs, start, end, root=ROOT):
    directory = root / "public/data/btc/intraday/binance_1m"
    directory.mkdir(parents=True, exist_ok=True)
    # Stage output so malformed or incomplete downloads cannot replace valid data.
    with tempfile.TemporaryDirectory(prefix="binance-stage-") as temporary:
        staged = Path(temporary) / "spot.csv.gz"
        count = 0
        with staged.open("wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream, lineterminator="\n")
                    writer.writerow(["timestamp", "symbol", "open", "high", "low", "close", "volume", "trade_count"])
                    for row in minute_rows([p for p, _ in inputs], start, end):
                        writer.writerow(row)
                        count += 1
        data = staged.read_bytes()
    manifest = {
        "schema_version": 1, "exchange": "Binance", "resolution": "1m",
        "symbol": "BTC-USDT", "quote_currency": "USDT",
        "strategy_symbol": "BTC-USD", "usd_conversion_rate_assumed": 1.0,
        "price_convention": "Trade OHLC; unconverted USDT price used as a USD proxy, not a bid/ask midpoint",
        "warning": "USDT/USD parity is assumed, not measured. Stablecoin and cross-venue basis can distort carry and returns.",
        "availability_convention": "Opening-minute label; close available only at t + 1 minute",
        "from_timestamp": f"{start}T00:00Z", "to_timestamp_exclusive": f"{end}T00:00Z",
        "coverage": {"bars": count, "missing_minutes": 0, "continuous": True},
        "inputs": [meta for _, meta in inputs],
        "output": {"path": "spot.csv.gz", "sha256": sha256(data), "bytes": len(data)},
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "https://github.com/binance/binance-public-data",
    }
    (directory / "spot.csv.gz").write_bytes(data)
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    repository_path = root / "public/data/manifest.json"
    repository = json.loads(repository_path.read_text())
    repository["btc_intraday_spot_binance"] = {
        "active_provider": "binance_1m", "resolution": "1m",
        "source": "Binance BTC/USDT trade candles; USD proxy assuming USDT/USD=1",
        "coverage": manifest["coverage"],
        "from_timestamp": manifest["from_timestamp"],
        "to_timestamp_exclusive": manifest["to_timestamp_exclusive"],
        "manifest_sha256": sha256((directory / "manifest.json").read_bytes()),
    }
    config_path = root / "public/data/btc/intraday/config.json"
    if (config_path.exists() and json.loads(config_path.read_text()).get(
            "active_providers", {}).get("spot") == "binance_1m"):
        repository["btc_intraday_spot"] = repository["btc_intraday_spot_binance"]
    repository_path.write_text(json.dumps(repository, indent=2, sort_keys=True) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat, help="exclusive UTC date")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    futures = json.loads((ROOT / "public/data/btc/intraday/deribit_1m/manifest.json").read_text())
    start = args.start or date.fromisoformat(futures["from_timestamp"][:10])
    end = args.end or date.fromisoformat(futures["to_timestamp_exclusive"][:10])
    if start >= end:
        parser.error("start must precede end")
    with tempfile.TemporaryDirectory(prefix="binance-download-") as temporary:
        result = materialize(download(start, end, Path(temporary)), start, end)
    if args.activate:
        path = ROOT / "public/data/btc/intraday/config.json"
        config = json.loads(path.read_text())
        config["providers"]["binance_1m"] = {
            "format": "binance_spot_candles", "path": "binance_1m", "resolution": "1m"}
        config["active_providers"]["spot"] = "binance_1m"
        path.write_text(json.dumps(config, indent=2) + "\n")
        path = ROOT / "public/data/manifest.json"
        inventory = json.loads(path.read_text())
        inventory["btc_intraday_spot"] = inventory["btc_intraday_spot_binance"]
        path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
