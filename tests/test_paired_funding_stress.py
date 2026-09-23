"""Independent self-financing checks across the execution/ledger boundary."""
import json
import unittest
from unittest.mock import patch

from paired_transfer import PairedConfig, PairedTransferAccount
from trade_replay import Trade


DAY_US = 86400 * 1_000_000


def print_at(us, symbol, price=100000, btc=.1, side="buy"):
    return Trade(us, symbol, price, btc, side, f"{symbol}:{us}:{side}")


def initialized(**overrides):
    values = dict(max_unpaired_btc=.01, max_transfer_fraction=1,
                          cash_reserve_fraction=0, max_quote_age_seconds=1_000_000,
                          max_quote_skew_seconds=1_000_000, max_legging_seconds=1000,
                          spot_fixed_fee_usd=5, futures_fixed_fee_usd=5)
    config = PairedConfig(**{**values, **overrides})
    ledger = PairedTransferAccount(100000, config=config,
                                    expiries={"F": 30 * DAY_US, "G": 60 * DAY_US})
    ledger.initialize_spot(print_at(0, "SPOT"))
    ledger.on_trade(print_at(1, "F"))
    ledger.on_trade(print_at(2, "G"))
    return ledger


def start(account, us, source, target, source_qty, target_qty):
    return account.start_transfer(us, dict(accepted=True, source_symbol=source,
        target_symbol=target, source_quantity_btc=source_qty, target_quantity_btc=target_qty))


def fill_loop(account, us, source, target, source_price=100000, target_price=100000, count=100):
    for _ in range(count):
        us += 10
        account.on_trade(print_at(us, source, source_price, side="sell"))
        us += 10
        account.on_trade(print_at(us, target, target_price))
        if account.active_pair_id is None:
            break
    return us


class PairedFundingStressTests(unittest.TestCase):
    def assert_reconciles(self, account):
        self.assertAlmostEqual(account.reconstruction_error(), 0, places=7)
        self.assertAlmostEqual(account.ledger.reconstruction_error(), 0, places=7)
        self.assertAlmostEqual(account.market_pnl, account.ledger.market_pnl, places=7)
        self.assertGreaterEqual(account.ledger.cash, 0)
        self.assertGreaterEqual(account.ledger.margin_excess, -1e-7)

    def test_tiny_source_chunks_with_upfront_fixed_tickets_complete_feasible_pair(self):
        account = initialized()
        # Aggregate funding: $25,000 sale - $5 source fee supports $24,990
        # future notional + $5 target fee. First .01 chunk cannot afford the
        # full proportional target while paying both first-fill ticket fees.
        pair = start(account, 3, "SPOT", "F", .25, .2499)
        fill_loop(account, 3, "SPOT", "F")
        self.assertEqual(pair.status, "completed")
        self.assertAlmostEqual(pair.source_filled_btc, .25)
        self.assertAlmostEqual(pair.target_filled_btc, .2499)
        self.assertLessEqual(pair.max_unpaired_btc, .01 + 1e-12)
        self.assertAlmostEqual(account.fees, 10)
        self.assert_reconciles(account)

    def test_partial_fixed_fee_pair_resume_matches_uninterrupted(self):
        uninterrupted = initialized()
        start(uninterrupted, 3, "SPOT", "F", .25, .2499)
        uninterrupted.on_trade(print_at(10, "SPOT", side="sell"))
        uninterrupted.on_trade(print_at(20, "F"))
        restored = PairedTransferAccount.restore(json.loads(json.dumps(uninterrupted.snapshot())))
        for account in (uninterrupted, restored):
            fill_loop(account, 20, "SPOT", "F")
            self.assert_reconciles(account)
        self.assertEqual(uninterrupted.snapshot(), restored.snapshot())
        self.assertIsNone(restored.active_pair_id)
        self.assertAlmostEqual(restored.fees, 10)

    def test_roll_then_reverse_after_vm_keeps_funding_and_reconstruction(self):
        account = initialized(settlement_interval_seconds=1)
        first = start(account, 3, "SPOT", "F", .25, .24)
        fill_loop(account, 3, "SPOT", "F")
        self.assertEqual(first.status, "completed")
        account.on_trade(print_at(1_000_000, "F", 110000))
        account.on_trade(print_at(2_000_000, "G", 110000))
        self.assertEqual(account.ledger.unrealized_pnl_usd(), 0)
        roll = start(account, 2_000_001, "F", "G", .24, .23)
        us = fill_loop(account, 2_000_001, "F", "G", 110000, 110000)
        self.assertEqual(roll.status, "completed")
        self.assertAlmostEqual(account.units["SPOT"], .75)
        reverse = start(account, us + 1, "G", "SPOT", .23, .25)
        fill_loop(account, us + 1, "G", "SPOT", 110000, 100000)
        self.assertEqual(reverse.status, "completed")
        self.assertAlmostEqual(account.units["SPOT"], 1)
        self.assertAlmostEqual(account.collateral, 0)
        self.assertAlmostEqual(account.fees, 30)
        self.assert_reconciles(account)

    def test_spread_cost_and_fixed_fee_reduce_nav_exactly_once(self):
        account = initialized(half_spread_bps=10)
        pair = start(account, 3, "SPOT", "F", .1, .09)
        fill_loop(account, 3, "SPOT", "F")
        self.assertEqual(pair.status, "completed")
        self.assertAlmostEqual(account.fees, 10)
        self.assertAlmostEqual(account.nav, 100000 - 10 - 19)
        self.assert_reconciles(account)

    def test_delayed_observation_cannot_see_actual_unsettled_price_gain(self):
        from paired_transfer_economics import TransferDecision

        account = initialized()
        first = start(account, 3, "SPOT", "F", .25, .24)
        fill_loop(account, 3, "SPOT", "F")
        self.assertEqual(first.status, "completed")
        account.config.futures_feed_delay_seconds = 1
        account.on_trade(print_at(10000, "F", 110000))
        self.assertAlmostEqual(account.ledger.unrealized_pnl_usd("F"), 2400)
        inspected = []

        def inspect(us, source, target, spot, **kwargs):
            inspected.append(source)
            return TransferDecision(False, "inspection", source.quote.symbol, target.symbol)

        with patch("paired_transfer_economics.evaluate_transfer", side_effect=inspect):
            account.decide(20000)
        futures = [source for source in inspected if source.quote.symbol == "F"]
        self.assertTrue(futures)
        for source in futures:
            self.assertEqual(source.quote.price, 100000)
            self.assertAlmostEqual(source.unsettled_pnl_usd, 0)
            self.assertAlmostEqual(source.cash_usd, 24000)

    def test_source_ticket_larger_than_allowed_chunk_rejects_before_trading(self):
        account = initialized(spot_fixed_fee_usd=1001)
        pair = start(account, 3, "SPOT", "F", .25, .2299)
        self.assertIsNone(pair)
        self.assertEqual(account.last_reason, "first_chunk_unfunded")
        self.assertEqual(account.fees, 0)
        self.assertEqual(account.units["SPOT"], 1)
        self.assert_reconciles(account)

    def test_funding_residue_age_does_not_reset_with_next_source_chunk(self):
        account = initialized(max_legging_seconds=.001)
        pair = start(account, 3, "SPOT", "F", .25, .2499)
        for us, symbol, side in ((10, "SPOT", "sell"), (20, "F", "buy"),
                                  (500, "SPOT", "sell"), (600, "F", "buy")):
            account.on_trade(print_at(us, symbol, side=side))
        self.assertGreater(pair.unpaired_btc, 0)
        self.assertEqual(pair.first_unpaired_us, 10)
        account.accrue(1011)
        self.assertEqual(pair.status, "timed_out")
        self.assert_reconciles(account)


if __name__ == "__main__":
    unittest.main()
