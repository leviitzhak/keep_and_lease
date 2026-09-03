#!/usr/bin/env python3
"""Download and audit daily BTC spot and dated-futures history.

Futures come from Deribit's public history API. Spot comes from Yahoo's
BTC-USD composite daily chart, independently of Deribit's perpetual future.
Outputs are staged and only replace ``public/data/btc`` after the complete
refresh validates. The futures download cache survives a failed spot request.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "public" / "data" / "btc"
DERIBIT = "https://history.deribit.com/api/v2/public"
YAHOO = "https://query2.finance.yahoo.com/v8/finance/chart/BTC-USD"
USER_AGENT = "KeepAndLeaseDataRefresh/1.0"


def request_json(url: str, attempts: int = 5):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(min(8.0, 0.5 * 2**attempt))


def deribit(method: str, **params):
    query = urllib.parse.urlencode(params)
    payload = request_json(f"{DERIBIT}/{method}?{query}")
    if payload.get("error"):
        raise RuntimeError(f"Deribit {method}: {payload['error']}")
    return payload["result"]


def iso_day(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).date().isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_instruments():
    expired = deribit(
        "get_instruments", currency="BTC", kind="future", expired="true")
    active = deribit(
        "get_instruments", currency="BTC", kind="future", expired="false")
    by_name = {}
    for instrument in expired + active:
        name = instrument["instrument_name"]
        if name == "BTC-PERPETUAL":
            continue
        by_name[name] = instrument
    return sorted(by_name.values(), key=lambda row: (
        row["expiration_timestamp"], row["instrument_name"]))


def read_future_rows(target: Path):
    if not target.exists():
        return None
    with target.open(encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    if not rows or rows[0] != ["date", "open", "high", "low", "close", "volume"]:
        return None
    return [tuple(row) for row in rows[1:] if len(row) == 6 and float(row[4]) > 0]


def download_future(instrument, futures_dir: Path):
    name = instrument["instrument_name"]
    target = futures_dir / f"{name}.csv"
    cached = read_future_rows(target)
    if cached is not None:
        return name, cached, target
    result = deribit(
        "get_tradingview_chart_data",
        instrument_name=name,
        start_timestamp=instrument["creation_timestamp"],
        end_timestamp=min(
            instrument["expiration_timestamp"],
            int(datetime.now(timezone.utc).timestamp() * 1000)),
        resolution="1D",
    )
    fields = ("ticks", "open", "high", "low", "close", "volume")
    lengths = {field: len(result.get(field, [])) for field in fields}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"{name} has inconsistent candle arrays: {lengths}")
    rows = []
    for values in zip(*(result.get(field, []) for field in fields)):
        timestamp, opened, high, low, closed, volume = values
        if closed is None or float(closed) <= 0:
            continue
        rows.append((iso_day(timestamp), opened, high, low, closed, volume))
    rows.sort()
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("date", "open", "high", "low", "close", "volume"))
        writer.writerows(rows)
    return name, rows, target


def yahoo_spot_candles(start: date, end: date):
    params = urllib.parse.urlencode({
        "period1": int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()),
        "period2": int(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()),
        "interval": "1d",
        "events": "div,splits",
    })
    result = request_json(f"{YAHOO}?{params}")["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    rows = []
    for index, timestamp in enumerate(result.get("timestamp", [])):
        closed = quote["close"][index]
        if closed is None or float(closed) <= 0:
            continue
        day = datetime.fromtimestamp(timestamp, timezone.utc).date()
        rows.append((
            day.isoformat(), quote["open"][index], quote["high"][index],
            quote["low"][index], closed, closed, quote["volume"][index],
        ))
    return rows


def audit(instruments, futures_rows, spot_rows):
    spot_days = {date.fromisoformat(row[0]) for row in spot_rows}
    curve = defaultdict(list)
    contracts = []
    for instrument in instruments:
        name = instrument["instrument_name"]
        expiry = datetime.fromtimestamp(
            instrument["expiration_timestamp"] / 1000, timezone.utc).date()
        rows = futures_rows[name]
        for row in rows:
            day = date.fromisoformat(row[0])
            if day < expiry:
                curve[day].append((expiry - day).days)
        contracts.append({
            "instrument_name": name,
            "creation_date": iso_day(instrument["creation_timestamp"]),
            "expiration_date": expiry.isoformat(),
            "instrument_type": instrument.get("instrument_type"),
            "contract_size": instrument.get("contract_size"),
            "settlement_currency": instrument.get("settlement_currency", "BTC"),
            "candle_count": len(rows),
            "first_candle": rows[0][0] if rows else None,
            "last_candle": rows[-1][0] if rows else None,
        })
    common = sorted(day for day in curve if day in spot_days)
    all_days = list(range((max(common) - min(common)).days + 1)) if common else []
    common_set = set(common)
    missing_calendar_days = [
        (min(common) + timedelta(days=offset)).isoformat()
        for offset in all_days if min(common) + timedelta(days=offset) not in common_set
    ] if common else []
    earliest_by_contract_count = {}
    for minimum in (1, 2, 3):
        eligible = sorted(day for day, maturities in curve.items()
                          if day in spot_days and len(maturities) >= minimum)
        earliest_by_contract_count[str(minimum)] = (
            eligible[0].isoformat() if eligible else None)
    earliest_by_minimum_maturity = {}
    for minimum_days in (10, 30, 60, 90):
        eligible = sorted(day for day, maturities in curve.items()
                          if day in spot_days and any(
                              maturity >= minimum_days for maturity in maturities))
        earliest_by_minimum_maturity[str(minimum_days)] = (
            eligible[0].isoformat() if eligible else None)
    return {
        "source": {
            "futures": DERIBIT,
            "spot": YAHOO,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "daily_cutoff": "Yahoo BTC-USD daily candle; Deribit 1D archive candle",
        },
        "coverage": {
            "contracts": len(contracts),
            "contracts_with_candles": sum(row["candle_count"] > 0 for row in contracts),
            "contracts_without_candles": [
                row["instrument_name"] for row in contracts if not row["candle_count"]],
            "spot_observations": len(spot_rows),
            "first_common_curve_and_spot_date": common[0].isoformat() if common else None,
            "last_common_curve_and_spot_date": common[-1].isoformat() if common else None,
            "common_dates": len(common),
            "missing_calendar_dates_within_common_range": missing_calendar_days,
            "dates_by_available_contract_count": {
                str(count): sum(len(values) == count for values in curve.values())
                for count in sorted({len(values) for values in curve.values()})
            },
            "earliest_date_by_minimum_available_contracts": earliest_by_contract_count,
            "earliest_date_by_minimum_maturity_days": earliest_by_minimum_maturity,
        },
        "contracts": contracts,
    }


def refresh(workers: int):
    instruments = load_instruments()
    if not instruments:
        raise RuntimeError("Deribit returned no dated BTC futures")
    cache = TARGET.parent / ".btc-download-cache"
    cache.mkdir(parents=True, exist_ok=True)
    if (TARGET / "futures").is_dir():
        shutil.copytree(TARGET / "futures", cache, dirs_exist_ok=True)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for instrument in instruments:
            if instrument["expiration_timestamp"] >= now_ms:
                (cache / f"{instrument['instrument_name']}.csv").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="keep-lease-btc-") as directory:
        stage = Path(directory) / "btc"
        futures_dir = stage / "futures"
        shutil.copytree(cache, futures_dir, dirs_exist_ok=True)
        rows_by_name = {}
        paths = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            jobs = {
                executor.submit(download_future, instrument, futures_dir): instrument
                for instrument in instruments
            }
            completed = 0
            for job in concurrent.futures.as_completed(jobs):
                name, rows, path = job.result()
                rows_by_name[name] = rows
                cached_path = cache / path.name
                if not cached_path.exists():
                    shutil.copy2(path, cached_path)
                paths[name] = path
                completed += 1
                if completed == 1 or completed % 25 == 0 or completed == len(jobs):
                    print(
                        f"Downloaded {completed}/{len(jobs)} Deribit contracts",
                        flush=True,
                    )
        earliest = min(datetime.fromtimestamp(
            row["creation_timestamp"] / 1000, timezone.utc).date()
            for row in instruments)
        spot_rows = yahoo_spot_candles(earliest, datetime.now(timezone.utc).date())
        if not spot_rows:
            raise RuntimeError("Yahoo returned no BTC-USD spot candles")
        with (stage / "spot.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow((
                "date", "open", "high", "low", "close", "adjusted_close", "volume"))
            writer.writerows(spot_rows)
        report = audit(instruments, rows_by_name, spot_rows)
        report["files"] = {
            "spot.csv": sha256(stage / "spot.csv"),
            **{f"futures/{name}.csv": sha256(path) for name, path in sorted(paths.items())},
        }
        if not report["coverage"]["first_common_curve_and_spot_date"]:
            raise RuntimeError("BTC spot and dated futures have no overlapping dates")
        (stage / "coverage.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        backup = TARGET.with_name("btc.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if TARGET.exists():
            TARGET.replace(backup)
        shutil.copytree(stage, TARGET)
        if backup.exists():
            shutil.rmtree(backup)
        shutil.rmtree(cache)
    manifest_path = TARGET.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["btc"] = {
        "coverage": report["coverage"],
        "coverage_sha256": sha256(TARGET / "coverage.json"),
        "futures_source": DERIBIT,
        "spot_source": YAHOO,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("--workers must be between 1 and 12")
    print(json.dumps(refresh(args.workers)["coverage"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
