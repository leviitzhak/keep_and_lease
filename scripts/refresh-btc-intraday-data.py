#!/usr/bin/env python3
"""Materialize bounded Deribit one-minute BTC dated-futures candles.

The downloader is resumable at the contract-file level, requests at most 5,000
one-minute candles per API call, writes deterministic gzip CSVs atomically, and
records every file hash in a coverage manifest. ``--to-date`` is exclusive so
the default invocation contains complete UTC days only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import gzip
import hashlib
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "public" / "data" / "btc" / "intraday" / "deribit_1m"
CONFIG = TARGET.parent / "config.json"
DERIBIT = "https://history.deribit.com/api/v2/public"
USER_AGENT = "KeepAndLeaseIntradayDataRefresh/1.0"
INTERVAL_MS = 60_000
MAX_CANDLES_PER_REQUEST = 5_000
FIELDS = ("ticks", "open", "high", "low", "close", "volume")


def request_json(url: str, attempts: int = 6):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(min(12.0, 0.75 * 2**attempt))


def deribit(method: str, **params):
    payload = request_json(f"{DERIBIT}/{method}?{urllib.parse.urlencode(params)}")
    if payload.get("error"):
        raise RuntimeError(f"Deribit {method}: {payload['error']}")
    return payload["result"]


def utc_midnight_ms(day: date) -> int:
    return int(datetime.combine(
        day, datetime.min.time(), timezone.utc).timestamp() * 1000)


def iso_minute(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(
        timestamp_ms / 1000, timezone.utc).isoformat(timespec="minutes").replace(
            "+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_instruments(start_ms: int, end_ms: int):
    expired = deribit(
        "get_instruments", currency="BTC", kind="future", expired="true")
    active = deribit(
        "get_instruments", currency="BTC", kind="future", expired="false")
    instruments = {}
    for instrument in expired + active:
        name = instrument["instrument_name"]
        if name == "BTC-PERPETUAL":
            continue
        if (instrument["creation_timestamp"] < end_ms and
                instrument["expiration_timestamp"] >= start_ms):
            instruments[name] = instrument
    return sorted(instruments.values(), key=lambda row: (
        row["expiration_timestamp"], row["instrument_name"]))


def expected_bounds(instrument, start_ms: int, end_ms: int):
    first = max(start_ms, instrument["creation_timestamp"])
    first = (first // INTERVAL_MS) * INTERVAL_MS
    last = min(end_ms - INTERVAL_MS, instrument["expiration_timestamp"])
    last = (last // INTERVAL_MS) * INTERVAL_MS
    return first, last


def inspect_existing(path: Path, expected_first: int, expected_last: int):
    if not path.exists():
        return None
    count = synthetic = 0
    first = last = None
    try:
        with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != [
                    "timestamp", "open", "high", "low", "close", "volume"]:
                return None
            for row in reader:
                timestamp = int(datetime.fromisoformat(
                    row["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
                if float(row["close"]) <= 0:
                    return None
                first = timestamp if first is None else first
                last = timestamp
                count += 1
                if float(row.get("volume") or 0) == 0:
                    synthetic += 1
    except (OSError, EOFError, KeyError, TypeError, ValueError):
        return None
    continuous = count == ((last - first) // INTERVAL_MS + 1) if count else False
    if (count and expected_first <= first <= expected_last and
            last == expected_last and continuous):
        return {
            "rows": count,
            "first_timestamp": iso_minute(first),
            "last_timestamp": iso_minute(last),
            "synthetic_rows": synthetic,
        }
    return None


def candle_chunks(instrument, start_ms: int, end_ms: int):
    first, last = expected_bounds(instrument, start_ms, end_ms)
    cursor = first
    while cursor <= last:
        chunk_end = min(
            last, cursor + (MAX_CANDLES_PER_REQUEST - 1) * INTERVAL_MS)
        result = deribit(
            "get_tradingview_chart_data",
            instrument_name=instrument["instrument_name"],
            start_timestamp=cursor,
            end_timestamp=chunk_end,
            resolution="1",
        )
        lengths = {field: len(result.get(field, [])) for field in FIELDS}
        if len(set(lengths.values())) != 1:
            raise ValueError(
                f"{instrument['instrument_name']} has inconsistent arrays: {lengths}")
        if lengths["ticks"] > MAX_CANDLES_PER_REQUEST:
            raise ValueError(
                f"{instrument['instrument_name']} exceeded request cap: {lengths}")
        for values in zip(*(result.get(field, []) for field in FIELDS)):
            timestamp, opened, high, low, closed, volume = values
            if not cursor <= timestamp <= chunk_end:
                continue
            if closed is None or float(closed) <= 0:
                continue
            yield timestamp, opened, high, low, closed, volume
        cursor = chunk_end + INTERVAL_MS


def deterministic_gzip_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with temporary.open("wb") as raw:
        with gzip.GzipFile(
                fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
            with io.TextIOWrapper(
                    compressed, encoding="utf-8", newline="") as text:
                writer = csv.writer(text, lineterminator="\n")
                writer.writerow(
                    ("timestamp", "open", "high", "low", "close", "volume"))
                writer.writerows(rows)
    temporary.replace(path)


def download_contract(instrument, start_ms: int, end_ms: int, target: Path):
    name = instrument["instrument_name"]
    path = target / "futures" / f"{name}.csv.gz"
    expected_first, expected_last = expected_bounds(instrument, start_ms, end_ms)
    cached = inspect_existing(path, expected_first, expected_last)
    if cached is not None:
        return name, path, cached, True
    count = synthetic = 0
    first = last = None

    def normalized_rows():
        nonlocal count, synthetic, first, last
        previous = None
        for timestamp, opened, high, low, closed, volume in candle_chunks(
                instrument, start_ms, end_ms):
            if previous is not None and timestamp <= previous:
                if timestamp == previous:
                    continue
                raise ValueError(f"{name} returned non-monotonic timestamps")
            previous = timestamp
            first = timestamp if first is None else first
            last = timestamp
            count += 1
            if float(volume or 0) == 0:
                synthetic += 1
            yield (iso_minute(timestamp), opened, high, low, closed, volume)

    deterministic_gzip_csv(path, normalized_rows())
    continuous = count == ((last - first) // INTERVAL_MS + 1) if count else False
    if (not count or first < expected_first or first > expected_last or
            last != expected_last or not continuous):
        path.unlink(missing_ok=True)
        raise ValueError(
            f"{name} incomplete: expected no earlier than "
            f"{iso_minute(expected_first)} through {iso_minute(expected_last)}, "
            f"received {iso_minute(first) if first else None} through "
            f"{iso_minute(last) if last else None}")
    return name, path, {
        "rows": count,
        "synthetic_rows": synthetic,
        "first_timestamp": iso_minute(first),
        "last_timestamp": iso_minute(last),
    }, False


def write_config():
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    # A futures refresh must not reset independently chosen spot/tick providers.
    if CONFIG.exists():
        return
    payload = {
        "schema_version": 2,
        "active_provider": "deribit_1m",
        "active_providers": {
            "futures": "deribit_1m",
            "spot": "kraken_1m",
        },
        "providers": {
            "deribit_1m": {
                "format": "deribit_candles",
                "path": "deribit_1m",
                "resolution": "1m",
            },
            "kraken_1m": {
                "format": "kraken_spot_candles",
                "path": "kraken_1m",
                "resolution": "1m",
            },
            "tardis_quotes": {
                "format": "tardis_quotes",
                "path": "tardis_quotes",
                "resolution": "tick",
            },
        },
    }
    CONFIG.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def refresh(start: date, end: date, workers: int):
    if start >= end:
        raise ValueError("--from-date must precede exclusive --to-date")
    start_ms, end_ms = utc_midnight_ms(start), utc_midnight_ms(end)
    instruments = load_instruments(start_ms, end_ms)
    if not instruments:
        raise RuntimeError("Deribit returned no dated BTC futures for the interval")
    TARGET.mkdir(parents=True, exist_ok=True)
    write_config()
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        jobs = {
            executor.submit(
                download_contract, instrument, start_ms, end_ms, TARGET): instrument
            for instrument in instruments
        }
        completed = 0
        for job in concurrent.futures.as_completed(jobs):
            instrument = jobs[job]
            name, path, summary, cached = job.result()
            results[name] = {
                **summary,
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
                "creation_timestamp": iso_minute(
                    instrument["creation_timestamp"]),
                "expiration_timestamp": iso_minute(
                    instrument["expiration_timestamp"]),
                "instrument_type": instrument.get("instrument_type"),
                "contract_size": instrument.get("contract_size"),
                "settlement_currency": instrument.get(
                    "settlement_currency", "BTC"),
            }
            completed += 1
            state = "reused" if cached else "downloaded"
            print(
                f"{state} {completed}/{len(jobs)}: {name} "
                f"({summary['rows']:,} rows)", flush=True)
    manifest = {
        "schema_version": 1,
        "source": DERIBIT,
        "source_method": "public/get_tradingview_chart_data",
        "resolution": "1m",
        "from_timestamp": f"{start.isoformat()}T00:00Z",
        "to_timestamp_exclusive": f"{end.isoformat()}T00:00Z",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "price_convention": "Deribit TradingView candle close",
        "synthetic_convention": (
            "Rows with zero volume are retained for as-of valuation and marked "
            "observed=false by the loader; Deribit fills no-trade intervals."),
        "contracts": dict(sorted(results.items())),
        "coverage": {
            "contract_count": len(results),
            "rows": sum(row["rows"] for row in results.values()),
            "synthetic_rows": sum(
                row.get("synthetic_rows", 0) for row in results.values()),
            "compressed_bytes": sum(row["bytes"] for row in results.values()),
        },
    }
    manifest_path = TARGET / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    repository_manifest_path = ROOT / "public" / "data" / "manifest.json"
    repository_manifest = json.loads(
        repository_manifest_path.read_text(encoding="utf-8"))
    repository_manifest["btc_intraday"] = {
        "active_provider": "deribit_1m",
        "coverage": manifest["coverage"],
        "from_timestamp": manifest["from_timestamp"],
        "to_timestamp_exclusive": manifest["to_timestamp_exclusive"],
        "manifest_sha256": sha256(manifest_path),
        "resolution": "1m",
        "source": DERIBIT,
    }
    repository_manifest_path.write_text(
        json.dumps(repository_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main():
    today = datetime.now(timezone.utc).date()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--from-date", type=date.fromisoformat,
        default=today - timedelta(days=90))
    parser.add_argument(
        "--to-date", type=date.fromisoformat, default=today,
        help="exclusive UTC end date; defaults to today")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("--workers must be between 1 and 12")
    result = refresh(args.from_date, args.to_date, args.workers)
    print(json.dumps(result["coverage"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
