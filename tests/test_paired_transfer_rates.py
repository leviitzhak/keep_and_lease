from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from paired_transfer_rates import (CausalTreasuryRates, EPOCH,
                                   normalize_bill_discount, rate_available_at)


class BillNormalizationTests(unittest.TestCase):
    def test_discount_quote_prices_actual_91_day_benchmark_before_converting(self):
        price, rate = normalize_bill_discount(.0371)
        self.assertAlmostEqual(price, .9906219444444444)
        self.assertAlmostEqual(rate, .03797137544623342)
        self.assertAlmostEqual(price * (1 + rate * 91 / 365), 1)
        self.assertNotEqual(rate, .0371)

    def test_zero_and_negative_discount_quotes(self):
        self.assertEqual(normalize_bill_discount(0), (1, 0))
        price, rate = normalize_bill_discount(-.01)
        self.assertGreater(price, 1)
        self.assertLess(rate, 0)
        self.assertAlmostEqual(price * (1 + rate * 91 / 365), 1)

    def test_invalid_rate_cannot_enter_cash_accrual_or_json(self):
        for value in (float("inf"), float("nan"), 4):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_bill_discount(value)


class CausalRateTests(unittest.TestCase):
    def test_next_business_release_following_midnight_not_observation_midnight(self):
        rates = CausalTreasuryRates.from_series({91: [(date(2026, 7, 13), .0376),
                                                     (date(2026, 7, 14), .0371)]})
        self.assertIsNone(rates.rate_at(datetime(2026, 7, 14, 23, 59, 59)))
        self.assertEqual(rates.rate_at(datetime(2026, 7, 15)).raw_discount_rate, .0376)
        self.assertEqual(rates.rate_at(datetime(2026, 7, 16)).raw_discount_rate, .0371)
        self.assertEqual(rates.rate_at(datetime(2026, 7, 16)).tenor_days, 91)

    def test_weekend_and_federal_holiday_release_lag(self):
        cases = [
            (date(2026, 6, 12), datetime(2026, 6, 16)),  # Friday -> Monday release
            (date(2026, 6, 18), datetime(2026, 6, 23)),  # Juneteenth, then weekend
            (date(2026, 7, 2), datetime(2026, 7, 7)),  # observed July 4 on Friday
            (date(2026, 9, 4), datetime(2026, 9, 9)),  # Labor Day
            (date(2027, 12, 30), datetime(2028, 1, 4)),  # next New Year observed Dec31
        ]
        for observed, expected in cases:
            with self.subTest(observed=observed):
                self.assertEqual(rate_available_at(observed), expected)

    def test_explicit_timestamp_honors_utc_time_and_cannot_look_ahead(self):
        observation = datetime(2026, 6, 1, 15, 15, tzinfo=timezone(timedelta(hours=-5)))
        rates = CausalTreasuryRates.from_series({91: [(observation, .04)]})
        self.assertIsNone(rates.rate_at(datetime(2026, 6, 1, 20, 14, 59)))
        quote = rates.rate_at(datetime(2026, 6, 1, 20, 15))
        self.assertEqual(quote.age_days, 0)
        self.assertEqual(quote.publication_assumption, "explicit-source-timestamp")

    def test_stale_quote_cannot_authorize_but_remains_available_for_funding(self):
        rates = CausalTreasuryRates.from_series({91: [(date(2026, 7, 14), .0371)]}, max_age_days=7)
        fresh = rates.rate_at(datetime(2026, 7, 21))
        stale = rates.rate_at(datetime(2026, 7, 21, 0, 0, 0, 1))
        self.assertTrue(fresh.allows_new_transfers)
        self.assertFalse(stale.allows_new_transfers)
        self.assertTrue(stale.stale)
        self.assertEqual(fresh.annual_rate, stale.annual_rate)
        self.assertEqual(stale.source_latest_observation, "2026-07-14")
        json.dumps(stale.as_dict(), allow_nan=False)

    def test_integer_microsecond_query_and_interval_boundaries(self):
        days = [(date(2026, 7, day), .04) for day in (13, 14, 15)]
        rates = CausalTreasuryRates.from_series({91: days})
        def microseconds(day):
            return int((datetime(2026, 7, day) - EPOCH).total_seconds()) * 1_000_000
        self.assertEqual(rates.rate_at(microseconds(16)).observation_date, "2026-07-14")
        self.assertEqual(rates.boundaries_us(microseconds(15), microseconds(17)),
                         (microseconds(16), microseconds(17)))

    def test_later_raw_observations_do_not_change_earlier_yield(self):
        existing = [(date(2026, 7, 13), .0376)]
        first = CausalTreasuryRates.from_series({91: existing})
        extended = CausalTreasuryRates.from_series({91: existing + [(date(2026, 7, 14), .09)]})
        query = datetime(2026, 7, 15, 20)
        self.assertEqual(first.rate_at(query).annual_rate, extended.rate_at(query).annual_rate)
        self.assertNotEqual(first.data_version, extended.data_version)

    def test_reproducible_source_hashes_without_rewriting_legacy_files(self):
        from backtest_silver_lease_strategy import TENORS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = {}
            for _, name in TENORS:
                originals[name] = f"observation_date,{name}\n2026-07-14,3.71\n".encode()
                (root / f"{name}.csv").write_bytes(originals[name])
            first = CausalTreasuryRates.from_root(root)
            second = CausalTreasuryRates.from_root(root)
            self.assertEqual(first.data_version, second.data_version)
            provenance = first.provenance()
            self.assertFalse(provenance["source_refresh_performed"])
            self.assertFalse(provenance["historical_publication_times_verified"])
            for name, value in originals.items():
                self.assertEqual(provenance["source_sha256"][name], hashlib.sha256(value).hexdigest())
                self.assertEqual((root / f"{name}.csv").read_bytes(), value)

    def test_same_assumed_publication_boundary_chooses_latest_observation(self):
        # Old source histories can contain dates that modern calendars treat as
        # holidays. Their publication lag is a labeled approximation, not a crash.
        rates = CausalTreasuryRates.from_series({91: [(date(2026, 6, 18), .04),
                                                     (date(2026, 6, 19), .03)]})
        self.assertEqual(rates.rate_at(datetime(2026, 6, 23)).raw_discount_rate, .03)

    def test_refreshed_snapshot_has_causal_nonstale_quotes_through_full_window(self):
        root = Path(__file__).resolve().parents[1]
        rates = CausalTreasuryRates.from_root(root)
        provenance = rates.provenance()
        self.assertTrue(provenance["source_refresh_performed"])
        self.assertFalse(provenance["historical_publication_times_verified"])
        self.assertEqual(provenance["coverage"]["91"]["latest_observation"], "2026-09-04")
        day = datetime(2026, 6, 6)
        while day < datetime(2026, 9, 4):
            quote = rates.rate_at(day)
            self.assertIsNotNone(quote)
            self.assertFalse(quote.stale, day.isoformat())
            self.assertLessEqual(datetime.fromisoformat(quote.available_at), day)
            day += timedelta(hours=6)
        json.dumps(provenance, allow_nan=False)

    def test_snapshot_checksum_tampering_fails_closed(self):
        source = Path(__file__).resolve().parents[1] / "public/data/paired-rates"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "data/paired-rates"
            shutil.copytree(source, base)
            first = CausalTreasuryRates.from_root(directory)
            self.assertTrue(first.provenance()["source_refresh_performed"])
            snapshot = json.loads((base / "current.json").read_text())["snapshot"]
            path = base / snapshot / "DTB3.csv"
            path.write_bytes(path.read_bytes().replace(b"3.63", b"9.99", 1))
            with self.assertRaisesRegex(ValueError, "DTB3 checksum mismatch"):
                CausalTreasuryRates.from_root(directory)


if __name__ == "__main__":
    unittest.main()
