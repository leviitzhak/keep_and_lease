"""Canonical materialized-market readers with an optional SQLite cache."""

from __future__ import annotations

import csv
try:
    import sqlite3
except ModuleNotFoundError:  # Pyodide omits the optional SQLite module.
    sqlite3 = None
from collections import Counter
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path


ASSET_BY_PREFIX = {"SI": "silver", "GC": "gold", "SP": "sp500", "BTC": "btc"}


def data_directory(root: Path) -> Path:
    for candidate in (root / "data", root / "public" / "data"):
        if candidate.is_dir():
            return candidate
    return root / "data"


def database_path(root: Path) -> Path:
    return data_directory(root) / "market.sqlite3"


def read_spot_csv(root: Path, asset: str) -> dict[date, float]:
    directory = data_directory(root) / asset
    legacy = directory / f"{asset}_price.csv"
    source = legacy if legacy.exists() else directory / "spot.csv"
    result: dict[date, float] = {}
    with source.open(encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            try:
                value = float(row.get("price") or row["close"])
                if value > 0:
                    result[date.fromisoformat(row["date"])] = value
            except (ValueError, TypeError, KeyError):
                pass
    return result


def read_contract_csvs(
    root: Path, asset: str, prefix: str, spot: dict[date, float] | None = None
) -> tuple[dict[str, dict[date, float]], dict[tuple[str, date], float]]:
    contracts: dict[str, dict[date, float]] = {}
    volumes: dict[tuple[str, date], float] = {}
    for source in sorted((data_directory(root) / asset / "futures").glob("*.csv")):
        symbol = source.stem.upper()
        if not symbol.startswith(prefix.upper()):
            continue
        parsed = []
        with source.open(encoding="utf-8-sig") as stream:
            for row in csv.reader(stream):
                if not row or row[0].strip('"').lower() == "date":
                    continue
                try:
                    raw_day = row[0].strip('"')
                    day = None
                    for date_format in ("%m/%d/%Y", "%Y-%m-%d", "%y%m%d"):
                        try:
                            day = datetime.strptime(raw_day, date_format).date()
                            break
                        except ValueError:
                            pass
                    if day is None:
                        raise ValueError(raw_day)
                    raw = float(row[4])
                    volume = float(row[5]) if len(row) > 5 and row[5] else 0.0
                    if raw > 0:
                        parsed.append((day, raw, volume))
                except (ValueError, TypeError, IndexError):
                    pass
        if not parsed:
            continue
        scale = 1
        if spot:
            candidates = []
            scales = (1, 10, 100, 1000, 10000)
            for day, raw, _ in parsed:
                physical = spot.get(day)
                if physical:
                    candidates.append(min(
                        scales, key=lambda candidate: abs(raw / candidate / physical - 1)))
            if candidates:
                scale = Counter(candidates).most_common(1)[0][0]
        contracts[symbol] = {day: raw / scale for day, raw, _ in parsed}
        volumes.update({(symbol, day): volume for day, _, volume in parsed})
    return contracts, volumes


@lru_cache(maxsize=None)
def read_cached_asset(root: Path, asset: str):
    if sqlite3 is None:
        return None
    path = database_path(root)
    if not path.exists():
        return None
    spot: dict[date, float] = {}
    contracts: dict[str, dict[date, float]] = {}
    volumes: dict[tuple[str, date], float] = {}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            for day, value in connection.execute(
                    "SELECT day, price FROM spot WHERE asset=? ORDER BY day", (asset,)):
                spot[date.fromisoformat(day)] = value
            for symbol, day, close, volume in connection.execute(
                    "SELECT symbol, day, close, volume FROM future "
                    "WHERE asset=? ORDER BY symbol, day", (asset,)):
                parsed_day = date.fromisoformat(day)
                contracts.setdefault(symbol, {})[parsed_day] = close
                volumes[(symbol, parsed_day)] = volume
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"Market SQLite cache is unreadable: {exc}") from exc
    if not spot or not contracts:
        return None
    return spot, contracts, volumes


def build_database(root: Path, target: Path | None = None) -> Path:
    if sqlite3 is None:
        raise RuntimeError("SQLite support is unavailable in this Python runtime")
    target = target or database_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.unlink(missing_ok=True)
    with sqlite3.connect(temporary) as connection:
        connection.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE spot(asset TEXT NOT NULL, day TEXT NOT NULL, price REAL NOT NULL,
                              PRIMARY KEY(asset, day)) WITHOUT ROWID;
            CREATE TABLE future(asset TEXT NOT NULL, symbol TEXT NOT NULL, day TEXT NOT NULL,
                                close REAL NOT NULL, volume REAL NOT NULL,
                                PRIMARY KEY(asset, symbol, day)) WITHOUT ROWID;
            CREATE INDEX future_asset_day ON future(asset, day);
        """)
        for prefix, asset in ASSET_BY_PREFIX.items():
            if not (data_directory(root) / asset).is_dir():
                continue
            spot = read_spot_csv(root, asset)
            contracts, volumes = read_contract_csvs(
                root, asset, prefix, spot if asset == "silver" else None)
            connection.executemany(
                "INSERT INTO spot VALUES(?,?,?)",
                ((asset, day.isoformat(), value) for day, value in spot.items()))
            connection.executemany(
                "INSERT INTO future VALUES(?,?,?,?,?)",
                ((asset, symbol, day.isoformat(), close,
                  volumes.get((symbol, day), 0.0))
                 for symbol, prices in contracts.items() for day, close in prices.items()))
        connection.execute("ANALYZE")
    temporary.replace(target)
    return target
