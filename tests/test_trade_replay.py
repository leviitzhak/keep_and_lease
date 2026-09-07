import unittest

from trade_replay import TapeAccount, Trade


def trade(us, symbol="F", price=100, btc=1, side="buy", identifier=None):
    return Trade(us, symbol, price, btc, side, identifier or str(us))


class TradeReplayTests(unittest.TestCase):
    def test_non_lit_print_cannot_fill(self):
        account = TapeAccount(1000)
        account.submit_targets(10, {"F": 1})
        account.on_trade(Trade(11, "F", 100, 1, "buy", "block", False))
        self.assertEqual(account.fill_count, 0)

    def test_partial_last_print_vwap_and_regular_cash_accounting(self):
        audit = []
        account = TapeAccount(1000, sink=audit.append)
        account.submit_targets(10, {"F": 1.5})
        account.on_trade(trade(11, price=100))
        self.assertEqual(account.units["F"], 1)
        self.assertEqual(account.cash, 1000)  # futures principal is collateral, not expenditure
        account.on_trade(trade(12, price=110))
        account.cancel(13)
        self.assertEqual(account.units["F"], 1.5)
        self.assertAlmostEqual(audit[-1]["vwap"], 155 / 1.5)
        self.assertEqual(account.cash, 1010)  # only the already-held unit gained $10
        self.assertAlmostEqual(account.reconstruction_error(), 0)
        fills = [r for r in audit if r["kind"] == "fill"]
        self.assertEqual([r["signed_btc"] for r in fills], [1, .5])

    def test_delay_same_timestamp_wrong_side_and_participation(self):
        account = TapeAccount(1000, participation=.1, delay_us=5)
        account.submit_targets(10, {"F": 1})
        for event in [trade(10), trade(15), trade(16, side="sell")]:
            account.on_trade(event)
        self.assertEqual(account.fill_count, 0)
        account.on_trade(trade(17, btc=2))
        self.assertAlmostEqual(account.units["F"], .2)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            account.on_trade(trade(17, btc=2))

    def test_spot_must_fund_future_and_pending_remainder_is_cancelled(self):
        account = TapeAccount(100, participation=.5)
        account.initialize_spot(trade(0, "SPOT"))
        account.submit_targets(1, {"F": 1, "SPOT": 0})
        account.on_trade(trade(2))
        self.assertEqual(account.fill_count, 0)
        account.on_trade(trade(3, "SPOT", side="sell"))
        self.assertEqual(account.cash, 50)
        account.on_trade(trade(4))
        self.assertEqual(account.units, {"SPOT": .5, "F": .5})
        self.assertEqual(account.collateral, 50)
        account.submit_targets(5, {"SPOT": .5, "F": .5})
        account.on_trade(trade(6))
        self.assertEqual(account.units["F"], .5)
        self.assertEqual(account.cancellation_count, 2)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_future_must_release_collateral_before_spot_purchase(self):
        account = TapeAccount(100)
        account.submit_targets(1, {"F": 1})
        account.on_trade(trade(2))
        account.submit_targets(3, {"SPOT": 1})
        account.on_trade(trade(4, "SPOT"))
        self.assertEqual(account.units.get("SPOT", 0), 0)
        account.on_trade(trade(5, side="sell"))
        account.on_trade(trade(6, "SPOT"))
        self.assertEqual(account.units["SPOT"], 1)
        self.assertEqual(account.cash, 0)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_fees_interest_and_later_prices_reconcile_without_early_credit(self):
        audit = []
        account = TapeAccount(1000, fee_bps=1, sink=audit.append)
        account.rate = .04
        account.submit_targets(0, {"F": 1})
        account.on_trade(trade(1_000_000))
        first_nav = account.nav
        earlier_fill = dict(audit[-1])
        account.on_trade(trade(2_000_000, price=200))
        self.assertEqual(audit[-1], earlier_fill)
        self.assertAlmostEqual(earlier_fill["nav_usd"], first_nav)
        self.assertGreater(account.nav, first_nav + 100)
        self.assertAlmostEqual(account.fees, .01)
        self.assertAlmostEqual(account.reconstruction_error(), 0)


if __name__ == "__main__":
    unittest.main()
