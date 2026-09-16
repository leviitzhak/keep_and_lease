"""Adversarial execution cases independent of the implementation's unit suite."""
import json
import unittest

from paired_transfer import PairedConfig, PairedTransferAccount
from paired_transfer_economics import effective_lease_rate
from trade_replay import Trade


DAY_US = 86400 * 1_000_000
YEAR_US = 365 * DAY_US


def print_at(us, symbol="SPOT", price=100, quantity=1, side="buy"):
    return Trade(us, symbol, price, quantity, side, f"{symbol}:{us}", True)


class AdaptiveAdversarialReviewTests(unittest.TestCase):
    def make_account(self, **settings):
        audit = []
        config = dict(repricing_mode="adaptive", max_unpaired_btc=1,
                      max_quote_age_seconds=1000, max_quote_skew_seconds=1000)
        config.update(settings)
        account = PairedTransferAccount(1000, config=PairedConfig(**config),
            expiries={"F": 30 * DAY_US}, sink=audit.append)
        account.marks["F"] = print_at(0, "F", 50)
        account.initialize_spot(print_at(0))
        return account, audit

    @staticmethod
    def submit(account, us=1):
        return account.start_transfer(us, dict(accepted=True, source_symbol="SPOT",
            target_symbol="F", source_quantity_btc=1, target_quantity_btc=1,
            horizon_us=30 * DAY_US, cash_rate=0))

    def test_front_loaded_target_fee_preserves_completed_lot_lease_and_cash_reserve(self):
        for fee_setting in ("futures_fixed_fee_usd", "futures_min_fee_usd"):
            with self.subTest(fee_setting=fee_setting):
                account, _ = self.make_account(**{fee_setting: 5})
                pair = self.submit(account)
                account.on_trade(print_at(2, side="sell"))
                first_cap = account.orders["F"].limit_price
                account.on_trade(print_at(3, "F", first_cap, .1))
                # The tiny first fill pays the entire ticket charge. The next
                # cap must retain that actual cost in the whole lot's budget.
                remaining_cap = account.orders["F"].limit_price
                account.on_trade(print_at(4, "F", remaining_cap, .9))
                self.assertEqual(pair.status, "completed")
                net_rate = effective_lease_rate(
                    pair.matched_source_value_usd / pair.matched_source_btc,
                    pair.target_value_usd / pair.target_filled_btc,
                    cash_rate=0, remaining_years=(30 * DAY_US - 4) / YEAR_US,
                    spot_quantity_btc=pair.matched_source_btc,
                    futures_quantity_btc=pair.target_filled_btc,
                    spot_fee_usd=pair.matched_source_fee_usd,
                    futures_fee_usd=account.fees - pair.matched_source_fee_usd)
                self.assertGreaterEqual(net_rate + 1e-8, pair.target_effective_lease)
                self.assertGreaterEqual(account.funding_equity - account.collateral,
                                        100 * account.config.cash_reserve_fraction - 1e-8)
                self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)

    def test_duplicate_in_flight_price_update_does_not_reset_live_eligibility(self):
        account, _ = self.make_account(order_delay_seconds=.0001)
        self.submit(account)
        # Both observations request the same economic price while the first
        # replacement is still in transport. Its later duplicate must not turn
        # an already live resting order into a newly ineligible order again.
        account.on_trade(print_at(10, "F", 51))
        account.on_trade(print_at(20, "F", 51))
        account.accrue(110)
        applied_limit = account.orders["SPOT"].limit_price
        first_eligibility = account.orders["SPOT"].eligible_us
        account.accrue(120)
        self.assertAlmostEqual(account.orders["SPOT"].limit_price, applied_limit, places=8)
        self.assertEqual(account.orders["SPOT"].eligible_us, first_eligibility)

    def test_tiny_source_print_cannot_deadlock_first_target_ticket_funding(self):
        account, _ = self.make_account(futures_fixed_fee_usd=5)
        self.submit(account)
        # One dollar of source proceeds cannot pay a five-dollar target ticket.
        # Skipping that print or bounded accumulation are both valid; taking it
        # and then prohibiting every further source fill leaves a permanent
        # unfillable position despite later sufficient liquidity.
        account.on_trade(print_at(2, quantity=.01, side="sell"))
        account.on_trade(print_at(3, quantity=.99, side="sell"))
        account.on_trade(print_at(4, "F", 50))
        self.assertGreater(account.units.get("F", 0), .9)
        self.assertGreaterEqual(account.funding_equity + 1e-9, account.collateral)
        self.assertAlmostEqual(account.fees, 5)

    def test_frozen_repricing_snapshot_and_mixed_latency_checkpoint(self):
        account, audit = self.make_account(observation_delay_seconds=.00001,
            decision_delay_seconds=.00001, order_delay_seconds=.00001)
        account.accrue(10)
        self.submit(account, 20)
        account.on_trade(print_at(25, price=200))
        account.on_trade(print_at(26, "F", 80))
        account.accrue(40)
        pair = account.pairs[account.active_pair_id]
        # Initial decision began before either new exchange print was visible.
        self.assertEqual(pair.decision["quote_snapshots"]["SPOT"]["price"], 100)
        self.assertEqual(pair.decision["quote_snapshots"]["F"]["price"], 50)
        self.assertTrue(account.decision_queue)
        restored_audit = []
        restored = PairedTransferAccount.restore(
            json.loads(json.dumps(account.snapshot())), sink=restored_audit.append)
        audit.clear()
        for instance in (account, restored):
            instance.accrue(60)
        self.assertEqual(account.snapshot(), restored.snapshot())
        self.assertEqual(audit, restored_audit)
        source_arrivals = [row for row in audit if row["kind"] == "order_replace_arrival"
                           and row["symbol"] == "SPOT" and row["applied"]]
        self.assertTrue(source_arrivals)
        first = source_arrivals[0]
        # Spot's observation at 35 starts a decision using the old future;
        # the future's observation at 36 cannot enter that frozen decision.
        self.assertEqual(first["decision_started_us"], 35)
        self.assertEqual(first["decision_ready_us"], 45)
        self.assertEqual(first["eligible_after_us"], 55)
        self.assertAlmostEqual(first["counterpart_price"], 50 * 1.001)


if __name__ == "__main__":
    unittest.main()
