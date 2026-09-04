"""Canonical materialized-market readers with an optional SQLite cache.

Daily readers retain their historical return types. Intraday readers expose a
provider-neutral observation stream: strategy code consumes
``MarketObservation`` and ``MarketSnapshot`` whether the source files contain
Deribit candles or Tardis best quotes.
"""

from __future__ import annotations

import csv
import gzip
import heapq
import json
import os
try:
    import sqlite3
except ModuleNotFoundError:  # Pyodide omits the optional SQLite module.
    sqlite3 = None
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Iterator, Protocol, TextIO


ASSET_BY_PREFIX = {"SI": "silver", "GC": "gold", "SP": "sp500", "BTC": "btc"}


@dataclass(frozen=True)
class MarketObservation:
    """One normalized, point-in-time market observation."""

    timestamp: datetime
    symbol: str
    reference_price: float
    source: str
    source_kind: str
    available_at: datetime | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    volume: float | None = None
    observed: bool = True

    @property
    def effective_time(self) -> datetime:
        """First timestamp at which a strategy may know this observation."""

        return self.available_at or self.timestamp

    def execution_price(self, action: str) -> float:
        """Return ask for a buy, bid for a sell, or the reference fallback."""

        action = action.lower()
        if action == "buy":
            return self.ask_price or self.reference_price
        if action == "sell":
            return self.bid_price or self.reference_price
        if action in {"mark", "reference"}:
            return self.reference_price
        raise ValueError("action must be buy, sell, mark, or reference")


@dataclass(frozen=True)
class MarketSnapshot:
    """Latest known observation per symbol at a strategy decision timestamp."""

    timestamp: datetime
    observations: dict[str, MarketObservation]

    def reference_prices(self) -> dict[str, float]:
        return {
            symbol: observation.reference_price
            for symbol, observation in self.observations.items()
        }

    def execution_prices(self, action: str) -> dict[str, float]:
        return {
            symbol: observation.execution_price(action)
            for symbol, observation in self.observations.items()
        }


class IntradayObservationProvider(Protocol):
    """Adapter boundary implemented by candle and quote file providers."""

    name: str

    def streams(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        symbols: set[str] | None = None,
    ) -> Iterable[Iterator[MarketObservation]]:
        ...


def _open_csv_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", newline="", encoding="utf-8")
    return path.open("r", newline="", encoding="utf-8")


def _utc_timestamp(value: str | int | float) -> datetime:
    """Parse ISO timestamps plus the second/ms/us/ns epochs used by vendors."""

    text = str(value).strip()
    try:
        numeric = float(text)
    except ValueError:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    magnitude = abs(numeric)
    if magnitude >= 1e17:
        numeric /= 1e9
    elif magnitude >= 1e14:
        numeric /= 1e6
    elif magnitude >= 1e11:
        numeric /= 1e3
    return datetime.fromtimestamp(numeric, timezone.utc)


class DeribitCandleCsvProvider:
    """Read normalized one-minute Deribit candle files, one stream per symbol."""

    name = "deribit_candles_1m"

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @staticmethod
    def _symbol(path: Path) -> str:
        name = path.name
        return name[:-7] if name.endswith(".csv.gz") else path.stem

    def _stream(
        self, path: Path, start: datetime | None, end: datetime | None
    ) -> Iterator[MarketObservation]:
        symbol = self._symbol(path).upper()
        with _open_csv_text(path) as stream:
            for row in csv.DictReader(stream):
                try:
                    timestamp = _utc_timestamp(row["timestamp"])
                    if start is not None and timestamp < start:
                        continue
                    if end is not None and timestamp >= end:
                        break
                    close = float(row["close"])
                    volume = float(row.get("volume") or 0.0)
                    if close <= 0:
                        continue
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                yield MarketObservation(
                    timestamp=timestamp,
                    # A bar timestamp labels its opening minute. Its close is
                    # not knowable until the following minute boundary.
                    available_at=timestamp + timedelta(minutes=1),
                    symbol=symbol,
                    reference_price=close,
                    volume=volume,
                    source="deribit",
                    source_kind="candle_1m",
                    # Deribit fills no-trade intervals with the preceding close.
                    observed=volume > 0,
                )

    def streams(self, start=None, end=None, symbols=None):
        paths = sorted({
            path
            for pattern in ("*.csv", "*.csv.gz")
            for path in (self.directory / "futures").glob(pattern)
        })
        for path in paths:
            symbol = self._symbol(path).upper()
            if symbols is None or symbol in symbols:
                yield self._stream(path, start, end)


class TardisQuoteCsvProvider:
    """Read timestamp-sorted Tardis normalized quote CSVs."""

    name = "tardis_quotes"

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _stream(self, path, start, end, symbols):
        with _open_csv_text(path) as stream:
            for row in csv.DictReader(stream):
                try:
                    timestamp = _utc_timestamp(row["timestamp"])
                    if start is not None and timestamp < start:
                        continue
                    if end is not None and timestamp >= end:
                        break
                    symbol = row["symbol"].upper()
                    if symbols is not None and symbol not in symbols:
                        continue
                    bid = float(row["bid_price"])
                    ask = float(row["ask_price"])
                    if bid <= 0 or ask <= 0 or ask < bid:
                        continue
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                yield MarketObservation(
                    timestamp=timestamp,
                    symbol=symbol,
                    reference_price=(bid + ask) / 2,
                    bid_price=bid,
                    ask_price=ask,
                    source=row.get("exchange") or "tardis",
                    source_kind="quote",
                )

    def streams(self, start=None, end=None, symbols=None):
        paths = sorted({
            path
            for pattern in ("**/*.csv", "**/*.csv.gz")
            for path in self.directory.glob(pattern)
        })
        for path in paths:
            yield self._stream(path, start, end, symbols)


class IntradayMarketData:
    """Merge provider streams and create no-look-ahead as-of snapshots."""

    def __init__(self, provider: IntradayObservationProvider):
        self.provider = provider

    def iter_observations(self, start=None, end=None, symbols=None):
        heap = []
        serial = 0
        for source in self.provider.streams(start, end, symbols):
            iterator = iter(source)
            observation = next(iterator, None)
            if observation is None:
                continue
            heapq.heappush(
                heap, (observation.effective_time, serial, observation, iterator))
            serial += 1
        while heap:
            _, order, observation, iterator = heapq.heappop(heap)
            yield observation
            following = next(iterator, None)
            if following is not None:
                heapq.heappush(
                    heap, (following.effective_time, order, following, iterator))

    def iter_snapshots(
        self,
        timestamps: Iterable[datetime],
        symbols: set[str] | None = None,
        max_age: timedelta | None = None,
    ) -> Iterator[MarketSnapshot]:
        schedule = iter(timestamps)
        decision_time = next(schedule, None)
        if decision_time is None:
            return
        if decision_time.tzinfo is None:
            raise ValueError("intraday decision timestamps must be timezone-aware")
        events = iter(self.iter_observations(symbols=symbols))
        following = next(events, None)
        latest: dict[str, MarketObservation] = {}
        previous_time = None
        while True:
            decision_time = decision_time.astimezone(timezone.utc)
            if previous_time is not None and decision_time <= previous_time:
                raise ValueError(
                    "intraday decision timestamps must be strictly increasing")
            while following is not None and following.effective_time <= decision_time:
                latest[following.symbol] = following
                following = next(events, None)
            available = latest
            if max_age is not None:
                available = {
                    symbol: observation
                    for symbol, observation in latest.items()
                    if decision_time - observation.effective_time <= max_age
                }
            yield MarketSnapshot(decision_time, dict(available))
            previous_time = decision_time
            decision_time = next(schedule, None)
            if decision_time is None:
                return


def load_intraday_market(
    root: Path, asset: str = "btc", provider: str | None = None
) -> IntradayMarketData:
    """Load the configured provider without changing strategy callers."""

    directory = data_directory(Path(root)) / asset / "intraday"
    config = json.loads(
        (directory / "config.json").read_text(encoding="utf-8"))
    selected = provider or os.getenv(
        "KEEP_AND_LEASE_INTRADAY_PROVIDER", config["active_provider"])
    try:
        specification = config["providers"][selected]
    except KeyError as exc:
        raise ValueError(f"Unknown intraday provider: {selected}") from exc
    source = directory / specification["path"]
    format_name = specification["format"]
    if format_name == "deribit_candles":
        adapter = DeribitCandleCsvProvider(source)
    elif format_name == "tardis_quotes":
        adapter = TardisQuoteCsvProvider(source)
    else:
        raise ValueError(f"Unsupported intraday provider format: {format_name}")
    return IntradayMarketData(adapter)


def parse_observation(value: str) -> date | datetime:
    value = value.strip().strip('"')
    if "T" in value or " " in value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return date.fromisoformat(value)


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
                    timestamp = row.get("timestamp") or row["date"]
                    result[parse_observation(timestamp)] = value
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
                    try:
                        day = parse_observation(raw_day)
                    except ValueError:
                        for date_format in ("%m/%d/%Y", "%y%m%d"):
                            try:
                                day = datetime.strptime(
                                    raw_day, date_format).date()
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
                spot[parse_observation(day)] = value
            for symbol, day, close, volume in connection.execute(
                    "SELECT symbol, day, close, volume FROM future "
                    "WHERE asset=? ORDER BY symbol, day", (asset,)):
                parsed_day = parse_observation(day)
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
