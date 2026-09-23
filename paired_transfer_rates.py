"""Versioned, causal DTB3 normalization for funded paired-transfer research.

The output is a 91-day benchmark investment-yield CASH PROXY, not an observed
one-day bill or an actual security. Legacy readers and source files are never
changed. Dated H.15/FRED rows have no historical publication timestamps: allow
the next federal business day's release, then wait until the following UTC
midnight. This is an explicit calendar assumption, not point-in-time data.
"""
from bisect import bisect_right
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

NORMALIZATION_VERSION = "dtb3-investment-yield-v1"
AVAILABILITY_VERSION = "next-us-federal-business-release-following-utc-midnight-v1"
RATE_MODEL = "91-day-DTB3-investment-yield-cash-interest-proxy"
EPOCH = datetime(1970, 1, 1)
DAY_US = 86_400_000_000
DEFAULT_MAX_RATE_AGE_DAYS = 7.0


def _utc(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, int) and not isinstance(value, bool):
        return EPOCH + timedelta(microseconds=value)
    raise TypeError("Treasury time must be a date, datetime or integer epoch microseconds")


def _us(value):
    delta = _utc(value) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _nth_weekday(year, month, weekday, occurrence):
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + (occurrence - 1) * 7)


def _observed(day):
    return day + timedelta(days=-1 if day.weekday() == 5 else 1 if day.weekday() == 6 else 0)


@lru_cache(maxsize=256)
def _federal_holidays(year):
    """Modern US federal office holiday model; no claim of exact past releases."""
    days = set()
    # Include next New Year's observation when it falls on December 31.
    for y in (year - 1, year, year + 1):
        for month, day in ((1, 1), (7, 4), (11, 11), (12, 25)):
            days.add(_observed(date(y, month, day)))
        if y >= 2021:
            days.add(_observed(date(y, 6, 19)))
        if y >= 1986:
            days.add(_nth_weekday(y, 1, 0, 3))
        days.update((_nth_weekday(y, 2, 0, 3), _nth_weekday(y, 9, 0, 1),
                     _nth_weekday(y, 10, 0, 2), _nth_weekday(y, 11, 3, 4)))
        last_may = date(y, 5, 31)
        days.add(last_may - timedelta(days=last_may.weekday()))
        # The Board's Washington offices also observe inauguration day.
        if y >= 1965 and (y - 1965) % 4 == 0:
            inauguration = date(y, 1, 20)
            days.add(inauguration + timedelta(days=1 if inauguration.weekday() == 6 else 0))
    return days


def rate_available_at(observation):
    """Known timestamped records are available then; dated rows use the model."""
    if isinstance(observation, datetime):
        return _utc(observation)
    release_day = observation + timedelta(days=1)
    holidays = _federal_holidays(release_day.year)
    while release_day.weekday() >= 5 or release_day in holidays:
        release_day += timedelta(days=1)
    return datetime.combine(release_day + timedelta(days=1), time.min)


def normalize_bill_discount(discount_rate, tenor_days=91):
    """Return (price per $1 face, annual simple ACT/365 investment yield).

    Input is the decimal bank-discount quote, annualized on face and ACT/360.
    The 91-day price is implied by the benchmark; it is not a security quote.
    """
    discount_rate = float(discount_rate)
    if not math.isfinite(discount_rate) or not math.isfinite(tenor_days) or tenor_days <= 0:
        raise ValueError("Bill discount rate must be finite and tenor must be positive")
    price = 1 - discount_rate * tenor_days / 360
    if price <= 0 or not math.isfinite(price):
        raise ValueError("Bill discount rate implies a nonpositive benchmark price")
    return price, discount_rate * 365 / (360 * price)


@dataclass(frozen=True)
class RateQuote:
    annual_rate: float
    raw_discount_rate: float
    benchmark_price_per_face: float
    observation_date: str
    available_at: str
    age_days: float
    availability_age_days: float
    max_age_days: float
    stale: bool
    data_version: str
    source_latest_observation: str
    source_latest_available_at: str
    series: str = "DTB3"
    tenor_days: int = 91
    rate_model: str = RATE_MODEL
    normalization_version: str = NORMALIZATION_VERSION
    publication_assumption: str = AVAILABILITY_VERSION

    @property
    def allows_new_transfers(self):
        return not self.stale

    def as_dict(self):
        return {**asdict(self), "allows_new_transfers": self.allows_new_transfers}


class CausalTreasuryRates:
    """Immutable normalized snapshot; stale quotes still value existing funding."""

    def __init__(self, series, *, max_age_days=DEFAULT_MAX_RATE_AGE_DAYS, source_hashes=None):
        self.max_age_days = float(max_age_days)
        if not math.isfinite(self.max_age_days) or self.max_age_days < 0:
            raise ValueError("Maximum Treasury rate age must be finite and nonnegative")
        self._rows = tuple(sorted(((observation, float(rate)) for observation, rate
                                   in series.get(91, ())),
                                 key=lambda row: (_us(rate_available_at(row[0])), _us(row[0]))))
        self._available = tuple(_us(rate_available_at(observation)) for observation, _ in self._rows)
        if len({_us(day) for day, _ in self._rows}) != len(self._rows):
            raise ValueError("Treasury observations require unique observation times")
        self._boundaries = tuple(sorted(set(self._available)))
        self._normalized = tuple(normalize_bill_discount(rate) for _, rate in self._rows)
        self._source_hashes = dict(source_hashes or {})
        self._snapshot_manifest = None
        self._snapshot_manifest_sha256 = None
        canonical = {str(tenor): [[day.isoformat(), float(rate)] for day, rate in rows]
                     for tenor, rows in sorted(series.items())}
        source_content = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
        self._content_sha = hashlib.sha256(source_content.encode()).hexdigest()
        version_identity = {"normalization": NORMALIZATION_VERSION,
                            "availability": AVAILABILITY_VERSION,
                            "normalized_input_sha256": self._content_sha,
                            "source_sha256": self._source_hashes}
        self.data_version = hashlib.sha256(json.dumps(version_identity, sort_keys=True,
                                                   separators=(",", ":")).encode()).hexdigest()
        self._coverage = {}
        for tenor, rows in sorted(series.items()):
            ordered = sorted(rows, key=lambda row: _us(row[0]))
            self._coverage[str(tenor)] = {
                "count": len(ordered),
                "first_observation": ordered[0][0].isoformat() if ordered else None,
                "latest_observation": ordered[-1][0].isoformat() if ordered else None,
                "latest_available_at": rate_available_at(ordered[-1][0]).isoformat() if ordered else None,
                "used_for_cash_proxy": tenor == 91,
            }

    @classmethod
    def from_series(cls, series, *, max_age_days=DEFAULT_MAX_RATE_AGE_DAYS):
        return cls(series, max_age_days=max_age_days)

    @classmethod
    def from_root(cls, root, *, max_age_days=DEFAULT_MAX_RATE_AGE_DAYS):
        from backtest_silver_lease_strategy import TENORS, read_rates
        root = Path(root)
        # The web/worker image copies public/data to /app/data. Tests and old
        # deployments with no new snapshot retain the old, explicitly aged data.
        for base in (root / "public/data/paired-rates", root / "data/paired-rates"):
            if (base / "current.json").is_file():
                return cls.from_snapshot(base, max_age_days=max_age_days)
        hashes = {name: hashlib.sha256((root / f"{name}.csv").read_bytes()).hexdigest()
                  for _, name in TENORS}
        return cls(read_rates(root), max_age_days=max_age_days, source_hashes=hashes)

    @classmethod
    def from_snapshot(cls, base, *, max_age_days=DEFAULT_MAX_RATE_AGE_DAYS):
        """Load a content-verified NEW snapshot; never update legacy rate files."""
        from backtest_silver_lease_strategy import TENORS, read_rates
        base = Path(base)
        pointer = json.loads((base / "current.json").read_text())
        snapshot = pointer["snapshot"]
        if not isinstance(snapshot, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", snapshot):
            raise ValueError("Invalid paired-transfer Treasury snapshot path")
        root = base / snapshot
        manifest_bytes = (root / "manifest.json").read_bytes()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        if manifest_sha != pointer["manifest_sha256"]:
            raise ValueError("Paired-transfer Treasury manifest checksum mismatch")
        manifest = json.loads(manifest_bytes)
        if manifest.get("snapshot_id") != snapshot or manifest.get("schema_version") != 1:
            raise ValueError("Unsupported paired-transfer Treasury snapshot")
        if manifest.get("normalization_version") != NORMALIZATION_VERSION:
            raise ValueError("Paired-transfer Treasury normalization version mismatch")
        if manifest.get("publication_assumption") != AVAILABILITY_VERSION:
            raise ValueError("Paired-transfer Treasury availability version mismatch")
        hashes = {}
        for _, name in TENORS:
            body = (root / f"{name}.csv").read_bytes()
            hashes[name] = hashlib.sha256(body).hexdigest()
            if hashes[name] != manifest["series"][name]["sha256"]:
                raise ValueError(f"Paired-transfer Treasury {name} checksum mismatch")
        snapshot_hash = hashlib.sha256(json.dumps(hashes, sort_keys=True,
                                                 separators=(",", ":")).encode()).hexdigest()
        if snapshot_hash != manifest.get("content_sha256"):
            raise ValueError("Paired-transfer Treasury snapshot content checksum mismatch")
        result = cls(read_rates(root), max_age_days=max_age_days, source_hashes=hashes)
        result._snapshot_manifest = manifest
        result._snapshot_manifest_sha256 = manifest_sha
        result.data_version = hashlib.sha256((result.data_version + manifest_sha).encode()).hexdigest()
        return result

    def rate_at(self, when):
        query = _us(when)
        index = bisect_right(self._available, query) - 1
        if index < 0:
            return None
        observation, discount = self._rows[index]
        price, annual_rate = self._normalized[index]
        age = (query - _us(observation)) / DAY_US
        latest = self._coverage["91"]
        return RateQuote(
            annual_rate=annual_rate, raw_discount_rate=discount,
            benchmark_price_per_face=price, observation_date=observation.isoformat(),
            available_at=(EPOCH + timedelta(microseconds=self._available[index])).isoformat(),
            age_days=age, availability_age_days=(query - self._available[index]) / DAY_US,
            max_age_days=self.max_age_days, stale=age > self.max_age_days,
            data_version=self.data_version,
            source_latest_observation=latest["latest_observation"],
            source_latest_available_at=latest["latest_available_at"],
            publication_assumption=("explicit-source-timestamp" if isinstance(observation, datetime)
                                    else AVAILABILITY_VERSION))

    def boundaries_us(self, start_us, end_us):
        """Availability boundaries in (start, end], for causal accrual segments."""
        lo, hi = _us(start_us), _us(end_us)
        if hi < lo:
            raise ValueError("Treasury boundary end precedes start")
        return self._boundaries[bisect_right(self._boundaries, lo):bisect_right(self._boundaries, hi)]

    def provenance(self):
        result = {
            "data_version": self.data_version,
            "normalization_version": NORMALIZATION_VERSION,
            "availability_version": AVAILABILITY_VERSION,
            "source_sha256": dict(self._source_hashes),
            "normalized_input_sha256": self._content_sha,
            "rate_model": RATE_MODEL,
            "tenor_days": 91,
            "max_age_days": self.max_age_days,
            "coverage": {tenor: dict(value) for tenor, value in self._coverage.items()},
            "source": "https://fred.stlouisfed.org/series/DTB3",
            "publication_reference": "https://www.federalreserve.gov/releases/h15/",
            "pricing_reference": "https://www.treasurydirect.gov/marketable-securities/understanding-pricing/",
            "historical_publication_times_verified": False,
            "source_refresh_performed": self._snapshot_manifest is not None,
            "actual_security_prices": False,
            "notes": "Date-only publication uses modeled next federal business release day then UTC midnight. "
                     "Calendar does not establish historical release exceptions or revision vintages. "
                     "A stale quote continues funding valuation but cannot authorize a new discretionary transfer. "
                     "DGS constant-maturity rows are provenance only, not zero-coupon or actual-security yields.",
        }
        if self._snapshot_manifest is not None:
            # Round trip copies the nested manifest so callers cannot mutate the
            # pinned identity while building an audit response.
            result["snapshot_manifest"] = json.loads(json.dumps(self._snapshot_manifest))
            result["snapshot_manifest_sha256"] = self._snapshot_manifest_sha256
        return result
