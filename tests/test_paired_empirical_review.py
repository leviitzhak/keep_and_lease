"""Independent cross-checks of the calibration and actual execution clocks."""
import json
import unittest

from paired_execution_study import DAY_US, StudyConfig, runnerstudy
from paired_transfer import PairedConfig, PairedTransferAccount
from trade_replay import Trade


def trade(us, symbol="SPOT", price=100, quantity=.01, side="sell", suffix=""):
    return Trade(us, symbol, price, quantity, side, f"{symbol}:{us}:{suffix}", True)


class OrderedTape:
    manifest_bytes = b"independent-study-live-clock-fixture"
    policy = "sequence"

    def __init__(self, events):
        self.events = sorted(events, key=lambda event: event.us)

    def trades(self, start_us, end_us):
        return (event for event in self.events if start_us <= event.us < end_us)


class EmpiricalExecutionReviewTests(unittest.TestCase):
    def fixture(self, events, target_quantity=.01):
        seeds = [trade(-1_000_000), trade(-1_000_000, "F", 90, side="buy")]
        shared = dict(max_quote_age_seconds=10, max_quote_skew_seconds=1,
                      observation_delay_seconds=.1, decision_delay_seconds=.1,
                      order_delay_seconds=.1, response_delay_seconds=.15,
                      half_spread_bps=5, slippage_bps=10)
        report = runnerstudy(OrderedTape(seeds + events), 0, 3_000_000,
            {"F": 30 * DAY_US}, StudyConfig(quantity_grid_btc=(.01,),
                waiting_seconds=(2,), **shared))
        group = next(group for group in report["model"]["groups"]
                     if group["scope"] == "contract")
        study = group["outcomes"][0]
        audit = []
        account = PairedTransferAccount(1000, fee_bps=10,
            config=PairedConfig(repricing_mode="empirical", max_unpaired_btc=.01,
                                waiting_seconds=2, **shared),
            expiries={"F": 30 * DAY_US}, sink=audit.append)
        account.marks["F"] = seeds[1]
        account.initialize_spot(seeds[0])
        account.start_transfer(0, dict(accepted=True, source_symbol="SPOT", target_symbol="F",
            source_quantity_btc=.01, target_quantity_btc=target_quantity,
            horizon_us=DAY_US, cash_rate=0, diagnostics={"source_sale_limit": 98,
                "target_buy_limit": 91.8, "execution_budget_bps": 200,
                "execution_joint_success_probability": .95}))
        return account, audit, study

    def test_study_and_live_share_continuous_partials_ack_clock_and_funded_prefix(self):
        events = [
            trade(200_000),  # Arrival itself cannot supply source liquidity.
            trade(210_000, quantity=.004),
            trade(220_000, price=101, quantity=.003),
            trade(250_000, price=99, quantity=.003),
            trade(600_000, "F", 90, side="buy"),  # Hedge arrival: also excluded.
            trade(610_000, "F", 90.5, .004, "buy"),
            trade(610_000, "F", 90, .002, "buy", "second"),
            trade(650_000, "F", 89.5, .004, "buy"),
        ]
        for target_quantity in (.01, .009):
            with self.subTest(target_quantity=target_quantity):
                account, audit, study = self.fixture(events, target_quantity)
                for event in events[:4]:
                    account.on_trade(event)
                # Snapshot before the final source acknowledgement and its
                # decision/transport stages. Resume must preserve that clock.
                restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
                for instance in (account, restored):
                    for event in events[4:]:
                        instance.on_trade(event)
                    instance.accrue(1_000_000)
                self.assertEqual(account.snapshot(), restored.snapshot())
                self.assertTrue(study["completed"])
                source_fills = [row for row in audit if row["kind"] == "fill" and row["role"] == "source"]
                target_fills = [row for row in audit if row["kind"] == "fill" and row["role"] == "target"]
                self.assertEqual([row["us"] for row in source_fills], [210_000, 220_000, 250_000])
                self.assertEqual([row["us"] for row in target_fills], [610_000, 610_000, 650_000])
                source_vwap = sum(-row["signed_btc"] * row["price"] for row in source_fills) / .01
                self.assertAlmostEqual(source_vwap, study["source_vwap"])
                self.assertAlmostEqual(account.units["F"], target_quantity)
                self.assertAlmostEqual(study["target_completed_seconds"], target_fills[-1]["us"] / 1e6)
                if target_quantity == .01:
                    actual_vwap = sum(row["signed_btc"] * row["price"] for row in target_fills) / target_quantity
                    self.assertAlmostEqual(actual_vwap, study["target_vwap"])
                self.assertEqual(account.summary()["empirical_execution"]["completed_by_deadline"], 1)
                self.assertGreaterEqual(account.funding_equity + 1e-9, account.collateral)
                self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)

    def test_study_and_live_both_exclude_exact_deadline_and_retain_source_cash(self):
        events = [trade(210_000), trade(2_000_000, "F", 90, side="buy")]
        account, audit, study = self.fixture(events)
        for event in events:
            account.on_trade(event)
        self.assertFalse(study["completed"])
        self.assertEqual(study["source_fill_fraction"], 1)
        self.assertEqual(study["target_fill_fraction"], 0)
        self.assertEqual(account.units.get("F", 0), 0)
        self.assertAlmostEqual(account.units["SPOT"], 9.99)
        self.assertGreater(account.cash, 0)
        self.assertIsNotNone(account.cash_recovery)
        stats = account.summary()["empirical_execution"]
        self.assertEqual(stats["completion_probability_denominator"], 1)
        self.assertEqual(stats["deadline_failed"], 1)
        self.assertEqual(stats["completion_probability"], 0)
        self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)
        self.assertFalse(any(row["kind"] == "fill" and row["role"] == "target" for row in audit))


if __name__ == "__main__":
    unittest.main()
