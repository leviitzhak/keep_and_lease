"""Financial/audit identity at a real UTC day boundary, including pending fills."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backtest_audit import AuditCollection, MemoryAuditStore, read_chunk
import btc_trade_backtest as replay
from replay_checkpoints import DirectoryCheckpoints
from trade_replay import Trade
from tests.test_btc_trade_backtest import payload, FakeStore

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def scenario(self):
        p = payload()
        p.update(backtest_start="2026-06-25T23:59:58", backtest_end="2026-06-26T00:00:03")
        p["commodity_parameters"]["btc"].update(execution_delay_seconds=1, long_allocation_half_life_days=.001)
        store = FakeStore()
        store.source_manifest["end"] = "2026-06-27T00:00:00"
        base = replay.us_time(p["backtest_start"])
        store.events = [Trade(base+i*100_000, symbol, 100+i*.001, .01,
                              "sell" if symbol == "SPOT" else "buy", f"{symbol}-{i}")
                        for i in range(50) for symbol in ("F", "SPOT")]
        coverage = dict(replay.catalog(), end=store.source_manifest["end"])
        return p, store, coverage

    def run_case(self, audit_store, journal, interrupt=False):
        p, store, coverage = self.scenario()
        audit = AuditCollection(audit_store)
        audit.checkpoints = journal
        def progress(stage, detail):
            if interrupt and stage == "trade_checkpoint":
                raise RuntimeError("forced interruption")
        with patch.object(replay.strategy, "read_rates", return_value={}), patch.object(replay.strategy, "usd_rate", return_value=.05):
            return replay.run(p, ROOT, audit, progress, store=store, coverage=coverage)

    def test_day_boundary_recovery_preserves_every_financial_and_audit_row(self):
        with tempfile.TemporaryDirectory() as root:
            full_store, resumed_store = MemoryAuditStore(), MemoryAuditStore()
            full = self.run_case(full_store, DirectoryCheckpoints(Path(root)/"full"))
            journal = DirectoryCheckpoints(Path(root)/"resume")
            with self.assertRaisesRegex(RuntimeError, "forced interruption"):
                self.run_case(resumed_store, journal, True)
            state = journal.latest()
            self.assertTrue(state["account"]["orders"])
            self.assertEqual(state["source_cursor_exclusive_us"], replay.us_time("2026-06-26"))
            resumed = self.run_case(resumed_store, journal)
            self.assertEqual(full["summary"], resumed["summary"])
            self.assertEqual(full["series"], resumed["series"])
            for product in full["audit"]["datasets"]:
                self.assertEqual(full["audit"]["datasets"][product], resumed["audit"]["datasets"][product])
            self.assertEqual(full_store.objects, resumed_store.objects)
            self.assertEqual(resumed["trade_replay"]["resumed_after_us"], state["source_cursor_exclusive_us"])

    def test_wrong_checkpoint_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            journal = DirectoryCheckpoints(root)
            journal.save(1, {"identity": "wrong"})
            with self.assertRaisesRegex(ValueError, "differ"):
                self.run_case(MemoryAuditStore(), journal)

    def test_account_snapshot_is_detached_and_json_roundtrip_exact(self):
        from trade_replay import TapeAccount
        account = TapeAccount(1000, .1, 1000, 1)
        account.initialize_spot(Trade(0, "SPOT", 100, 1, "buy", "initial"))
        account.submit_targets(1000, {"SPOT": 5})
        saved = json.loads(json.dumps(account.snapshot()))
        restored = TapeAccount.restore(saved)
        event = Trade(3000, "SPOT", 101, 1, "sell", "fill")
        account.on_trade(event); restored.on_trade(event)
        self.assertEqual(account.snapshot(), restored.snapshot())
        self.assertNotEqual(saved, restored.snapshot())

    def test_expiry_is_settled_at_its_timestamp_between_decisions(self):
        p, store, coverage = self.scenario()
        p["commodity_parameters"]["btc"].update(long_allocation_half_life_days=0,
            min_days=1, execution_delay_seconds=0)
        expiry = "2026-06-26T00:00:00.250000"
        store.source_manifest["futures"]["F"].update(expiry=expiry,
            settlement=dict(time=expiry, price=103, source="verified-fixture"))
        # Hold the near-expiry future despite a lease signal that would otherwise exclude it.
        def target(*args, **kwargs):
            return {"base_treasury": 1, "base_longs": {"F": 1}, "slv": 0} if args[0] else None
        audit = AuditCollection(MemoryAuditStore())
        with patch.object(replay.strategy, "read_rates", return_value={}), patch.object(replay.strategy, "usd_rate", return_value=.05), patch.object(replay.strategy, "positions_for_day", side_effect=target):
            result = replay.run(p, ROOT, audit, store=store, coverage=coverage)
        rows = [r for e in result["audit"]["datasets"]["btc_trade_events"]["chunks"] for r in read_chunk(audit.store, e)]
        settlements = [r for r in rows if r["kind"] == "settlement"]
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0]["us"], replay.us_time(expiry))
        self.assertEqual(settlements[0]["price"], 103)
        self.assertLess(result["trade_replay"]["max_nav_reconstruction_error_usd"], 1e-7)

class RangeManifestTests(unittest.TestCase):
    def manifest(self, days=90):
        from datetime import datetime, timedelta
        start = datetime(2026, 6, 6)
        entries = [dict(start=(start+timedelta(days=i)).isoformat(),
                        end=(start+timedelta(days=i+1)).isoformat(),
                        manifest_sha256=f'{i:064x}', local_path=f'days/{i}') for i in range(days)]
        return dict(source_manifest=dict(start=entries[0]['start'], end=entries[-1]['end'], futures={}),
                    daily_datasets=entries, partitions=[])

    def validate(self, value):
        from trade_data_store import ParquetTradeStore
        store = object.__new__(ParquetTradeStore)
        store.manifest, store.source_manifest = value, value['source_manifest']
        store._validate_range()

    def test_exact_ninety_utc_days_and_gap_rejection(self):
        self.validate(self.manifest())
        for mutation in ('gap', 'overlap', 'bad_digest', 'non_midnight'):
            value = self.manifest()
            if mutation == 'gap': del value['daily_datasets'][1]
            elif mutation == 'overlap': value['daily_datasets'][1] = value['daily_datasets'][0]
            elif mutation == 'bad_digest': value['daily_datasets'][1]['manifest_sha256'] = '../'+'x'*61
            else: value['daily_datasets'][1]['start'] = '2026-06-07T00:00:00.001'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.validate(value)

    def test_90_days_at_500ms_uses_deployment_catalog_limit(self):
        p = payload()
        p.update(backtest_start='2026-06-06', backtest_end='2026-09-04')
        coverage = dict(id='fixture', start=p['backtest_start'], end=p['backtest_end'], maximum_decisions=16_000_000)
        validated = replay.validate(p, coverage=coverage)
        self.assertEqual((validated[2]-validated[1])//validated[3], 15_552_000)
        p['execution_interval_seconds'] = .1
        with self.assertRaisesRegex(ValueError, '16,000,000'): replay.validate(p, coverage=coverage)
