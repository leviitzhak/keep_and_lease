#!/usr/bin/env python3
"""Materialize free Kraken quote samples as one-minute midpoint candles.

Tardis publishes normalized Kraken quotes for the first UTC day of each month.
Kraken renamed its exchange symbol from XBT/USD to BTC/USD on 2026-07-10;
both aliases are normalized to BTC-USD here. Raw quote files are transient and
the checked-in artifact is a compact, deterministic gzip candle file.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "public" / "data" / "btc" / "intraday" / "kraken_1m"
OUTPUT = TARGET / "spot.csv.gz"
DEFAULT_SAMPLE_DAYS = (
    date(2026, 7, 1),
    date(2026, 8, 1),
    date(2026, 9, 1),
)
SYMBOL_CHANGE = date(2026, 7, 10)


def source_symbol(day: date) -> str:
    return "XBT-USD" if day < SYMBOL_CHANGE else "BTC-USD"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iso_minute(epoch_minute: int) -> str:
    return datetime.fromtimestamp(
        epoch_minute * 60, timezone.utc).isoformat(timespec="minutes").replace(
            "+00:00", "Z")


def compact_price(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


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
                writer.writerow((
                    "timestamp", "symbol", "open", "high", "low", "close",
                    "quote_count"))
                writer.writerows(rows)
    temporary.replace(path)


def midpoint_candles(paths, statistics):
    """Yield minute OHLC rows while retaining only valid two-sided quotes."""

    current_minute = None
    opened = high = low = closed = None
    quote_count = 0

    def completed_row():
        if current_minute is None:
            return None
        statistics["bars"] += 1
        statistics["quote_updates"] += quote_count
        day = datetime.fromtimestamp(
            current_minute * 60, timezone.utc).date().isoformat()
        statistics["bars_by_day"][day] = (
            statistics["bars_by_day"].get(day, 0) + 1)
        return (
            iso_minute(current_minute), "BTC-USD", compact_price(opened),
            compact_price(high), compact_price(low), compact_price(closed),
            quote_count)

    for path in sorted(paths):
        with gzip.open(path, "rt", newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                try:
                    timestamp_us = int(row["timestamp"])
                    bid = float(row["bid_price"])
                    ask = float(row["ask_price"])
                    if bid <= 0 or ask <= 0 or ask < bid:
                        statistics["rejected_quotes"] += 1
                        continue
                except (KeyError, TypeError, ValueError, OverflowError):
                    statistics["rejected_quotes"] += 1
                    continue
                minute = timestamp_us // 60_000_000
                midpoint = (bid + ask) / 2
                if current_minute is not None and minute < current_minute:
                    raise ValueError(f"Non-monotonic quote timestamp in {path}")
                if minute != current_minute:
                    row_out = completed_row()
                    if row_out is not None:
                        yield row_out
                    current_minute = minute
                    opened = high = low = closed = midpoint
                    quote_count = 1
                else:
                    high = max(high, midpoint)
                    low = min(low, midpoint)
                    closed = midpoint
                    quote_count += 1
    row_out = completed_row()
    if row_out is not None:
        yield row_out


def download_samples(days, directory: Path):
    try:
        from tardis_dev import download_datasets
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the optional downloader with `python -m pip install "
            "tardis-dev`, or pass downloaded files with --input") from exc

    paths = []
    for day in days:
        symbol = source_symbol(day)
        download_datasets(
            exchange="kraken",
            data_types=["quotes"],
            symbols=[symbol],
            from_date=day.isoformat(),
            to_date=(day + timedelta(days=1)).isoformat(),
            download_dir=str(directory),
            concurrency=1,
        )
        path = directory / f"kraken_quotes_{day.isoformat()}_{symbol}.csv.gz"
        if not path.exists():
            raise FileNotFoundError(f"Tardis did not materialize {path.name}")
        paths.append(path)
    return paths


def materialize(paths):
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError("At least one Kraken quote file is required")
    statistics = {
        "bars": 0,
        "quote_updates": 0,
        "rejected_quotes": 0,
        "bars_by_day": {},
    }
    deterministic_gzip_csv(OUTPUT, midpoint_candles(paths, statistics))
    if not statistics["bars"]:
        OUTPUT.unlink(missing_ok=True)
        raise ValueError("Kraken quote files contained no valid two-sided quotes")

    days = sorted(statistics["bars_by_day"])
    sessions = [{
        "date": day,
        "from_timestamp": f"{day}T00:00Z",
        "to_timestamp_exclusive": (
            date.fromisoformat(day) + timedelta(days=1)).isoformat() + "T00:00Z",
        "bars": statistics["bars_by_day"][day],
        "missing_minutes": 1440 - statistics["bars_by_day"][day],
    } for day in days]
    manifest = {
        "schema_version": 1,
        "exchange": "Kraken",
        "delivery_vendor": "Tardis.dev free normalized CSV samples",
        "source": "https://docs.tardis.dev/historical-data-details/kraken",
        "resolution": "1m",
        "symbol": "BTC-USD",
        "source_symbol_aliases": ["XBT/USD", "BTC/USD"],
        "price_convention": (
            "OHLC of the Kraken best-bid/best-ask midpoint during each UTC minute"),
        "availability_convention": (
            "A candle timestamp labels its opening minute; close is usable at "
            "the following minute boundary"),
        "sample_sessions": sessions,
        "coverage": {
            **{key: value for key, value in statistics.items()
               if key != "bars_by_day"},
            "session_count": len(sessions),
            "missing_minutes": sum(row["missing_minutes"] for row in sessions),
            "compressed_bytes": OUTPUT.stat().st_size,
        },
        "output": {
            "path": OUTPUT.name,
            "sha256": sha256(OUTPUT),
        },
        "inputs": [{
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        } for path in paths],
        "materialized_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = TARGET / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    repository_manifest_path = ROOT / "public" / "data" / "manifest.json"
    repository_manifest = json.loads(
        repository_manifest_path.read_text(encoding="utf-8"))
    repository_manifest["btc_intraday_spot"] = {
        "active_provider": "kraken_1m",
        "coverage": manifest["coverage"],
        "manifest_sha256": sha256(manifest_path),
        "resolution": "1m",
        "sample_days": days,
        "source": "Kraken via Tardis.dev free normalized CSV samples",
    }
    repository_manifest_path.write_text(
        json.dumps(repository_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-day", action="append", type=date.fromisoformat,
        help="free Tardis sample day; repeat for multiple days")
    parser.add_argument(
        "--input", action="append", type=Path,
        help="already-downloaded normalized Kraken quote .csv.gz")
    args = parser.parse_args()
    if args.input:
        manifest = materialize(args.input)
    else:
        days = args.sample_day or list(DEFAULT_SAMPLE_DAYS)
        with tempfile.TemporaryDirectory(prefix="kraken-quotes-") as directory:
            manifest = materialize(download_samples(days, Path(directory)))
    print(json.dumps(manifest["coverage"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
