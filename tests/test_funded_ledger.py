import json
import math
import unittest

from funded_ledger import ContractSpec, FeeEngine, FeeSchedule, FundedLedger, FundingError, YEAR_SECONDS


def account(capital=1000, **kwargs):
    ledger = FundedLedger(capital, **kwargs)
    ledger.register_contract(ContractSpec("F"))
    return ledger


class FundedLedgerTests(unittest.TestCase):
    def assert_reconciles(self, ledger):
        self.assertAlmostEqual(ledger.reconstruction_error(), 0, places=8)
        self.assertGreaterEqual(ledger.free_cash_usd, -1e-9)
        self.assertGreaterEqual(ledger.posted_cash_usd, -1e-9)

    def test_native_inverse_non_usd_and_short_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "inverse"):
            ContractSpec("I", payoff="inverse")
        with self.assertRaises(ValueError):
            ContractSpec("I", currency="BTC")
        ledger = account()
        with self.assertRaises(FundingError):
            ledger.fill_future("F", -1, 100, "short")
        with self.assertRaises(FundingError):
            ledger.fill_spot(-1, 100, "shortspot")
        self.assertEqual(ledger.cash, 1000)

    def test_spot_endowment_sale_funds_future_without_principal_nav(self):
        ledger = account(100)
        ledger.initialize_spot(1, 100)
        before = ledger.snapshot()
        with self.assertRaises(FundingError):
            ledger.fill_future("F", 1, 100, "premature")
        self.assertEqual(ledger.snapshot(), before)
        ledger.fill_spot(-1, 100, "spot")
        ledger.fill_future("F", 1, 100, "future")
        self.assertEqual(ledger.cash, 100)
        self.assertEqual(ledger.free_cash_usd, 0)
        self.assertEqual(ledger.posted_cash_usd, 100)
        self.assertEqual(ledger.nav, 100)
        self.assertEqual(ledger.collateral, 100)
        self.assert_reconciles(ledger)

    def test_mark_then_vm_preserve_nav_and_no_duplicate_pnl_or_fee(self):
        rows = []
        ledger = account(110, fee_schedules={"futures": FeeSchedule(fixed=2)}, sink=rows.append)
        ledger.fill_future("F", 1, 100, "open")
        ledger.mark("F", 120, source="official mark")
        self.assertEqual(ledger.cash, 108)
        self.assertEqual(ledger.unrealized_pnl_usd(), 20)
        self.assertEqual(ledger.nav, 128)
        before = ledger.nav
        ledger.settle_variation("F", 120)
        self.assertEqual(ledger.nav, before)
        self.assertEqual(ledger.cash, 128)
        self.assertEqual(ledger.unrealized_pnl_usd(), 0)
        ledger.settle_variation("F", 120)
        self.assertEqual(ledger.fees, 2)
        self.assertEqual(ledger.fill_count, 1)
        self.assertEqual(len([r for r in rows if r["kind"] == "commission_charge"]), 1)
        self.assert_reconciles(ledger)

    def test_partial_lots_multiplier_and_fill_around_settlement(self):
        ledger = FundedLedger(1000)
        ledger.register_contract(ContractSpec("F", multiplier=2))
        ledger.fill_future("F", 1, 100, "a")
        ledger.fill_future("F", 2, 110, "b")
        self.assertEqual(ledger.unrealized_pnl_usd(), 20)
        ledger.fill_future("F", -1.5, 120, "c")
        self.assertEqual(ledger.cash, 1050)  # FIFO: 1*2*20 + .5*2*10
        self.assertEqual(ledger.unrealized_pnl_usd(), 30)
        ledger.settle_variation("F", 125)
        self.assertEqual(ledger.cash, 1095)
        ledger.fill_future("F", .5, 130, "d")
        ledger.fill_future("F", -2, 90, "e")
        self.assertEqual(ledger.cash, 950)
        self.assertEqual(ledger.units["F"], 0)
        self.assert_reconciles(ledger)

    def test_net_zero_settlement_resets_all_lot_references_and_consolidates(self):
        ledger = account(1000)
        ledger.fill_future("F", 1, 100, "a")
        ledger.fill_future("F", 1, 120, "b")
        self.assertEqual(len(ledger.lots["F"]), 2)
        ledger.settle_variation("F", 110)
        self.assertEqual(ledger.cash, 1000)
        self.assertEqual(len(ledger.lots["F"]), 1)
        self.assertEqual(ledger.lots["F"][0].reference_price, 110)
        ledger.fill_future("F", -1, 110, "c")
        self.assertEqual(ledger.cash, 1000)
        self.assertEqual(ledger.unrealized_pnl_usd(), 0)
        self.assert_reconciles(ledger)

    def test_same_price_partial_entries_keep_single_fifo_reference(self):
        ledger = account(1000)
        for _ in range(100):
            ledger.fill_future("F", .01, 100, "one-order")
        self.assertEqual(len(ledger.lots["F"]), 1)
        self.assertAlmostEqual(ledger.units["F"], 1)
        self.assert_reconciles(ledger)

    def test_small_commodity_lot_is_not_erased_by_usd_tolerance(self):
        ledger = account(1)
        ledger.fill_future("F", 1e-10, 1_000_000, "a")
        ledger.settle_variation("F", 2_000_000)
        self.assertEqual(ledger.units["F"], 1e-10)
        self.assertAlmostEqual(ledger.cash, 1.0001)
        ledger.fill_future("F", -1e-10, 3_000_000, "close")
        self.assertAlmostEqual(ledger.cash, 1.0002)
        self.assert_reconciles(ledger)

    def test_full_funding_cash_plus_unsettled_equals_notional_through_losses(self):
        ledger = account(100)
        ledger.fill_future("F", 1, 100, "a")
        for price in (80, 20, 0, 50, 130):
            ledger.mark("F", price)
            self.assertAlmostEqual(ledger.cash + ledger.unrealized_pnl_usd(), price)
            self.assertAlmostEqual(ledger.margin_excess, 0)
            ledger.settle_variation("F", price)
            self.assertAlmostEqual(ledger.cash, price)
            self.assert_reconciles(ledger)

    def test_pending_variation_is_equity_but_not_spendable(self):
        ledger = account(100)
        ledger.fill_future("F", 1, 100, "a")
        ledger.settle_variation("F", 120, available=False, payment_id="delayed")
        self.assertEqual(ledger.nav, 120)
        self.assertEqual(ledger.cash, 100)
        self.assertEqual(ledger.available_cash, 0)
        self.assertTrue(ledger.funding_blocked)
        with self.assertRaises(FundingError):
            ledger.fill_future("F", .1, 120, "cannot_spend_receivable")
        ledger.pay_variation("delayed")
        self.assertEqual(ledger.nav, 120)
        self.assertFalse(ledger.funding_blocked)
        with self.assertRaises(ValueError):
            ledger.pay_variation("delayed")
        self.assert_reconciles(ledger)

    def test_expiry_delivery_only_once_no_trade_commission(self):
        ledger = account(120, fee_schedules={"futures": FeeSchedule(fixed=2), "delivery": FeeSchedule(fixed=3)})
        ledger.fill_future("F", 1, 100, "a")
        ledger.settle_variation("F", 110)
        ledger.settle_expiry("F", 120)
        self.assertEqual(ledger.cash, 135)
        self.assertEqual(ledger.fees, 5)
        self.assertEqual(ledger.fill_count, 1)
        with self.assertRaises(ValueError):
            ledger.settle_expiry("F", 120)
        with self.assertRaises(ValueError):
            ledger.fill_future("F", 1, 120, "after_expiry")
        self.assert_reconciles(ledger)

    def test_reservations_prevent_double_use_and_are_consumed_once(self):
        ledger = account(200)
        ledger.reserve("transfer-a", 150)
        with self.assertRaises(FundingError):
            ledger.reserve("transfer-b", 100)
        with self.assertRaises(FundingError):
            ledger.fill_future("F", 1, 100, "b")
        ledger.fill_future("F", 1, 100, "a", reservation_id="transfer-a")
        self.assertEqual(ledger.reservations, {"transfer-a": 50})
        self.assertEqual(ledger.available_cash, 50)
        ledger.fill_spot(.5, 100, "a-spot", reservation_id="transfer-a")
        self.assertEqual(ledger.reservations, {})
        self.assertEqual(ledger.available_cash, 50)
        ledger.release("transfer-a")
        self.assert_reconciles(ledger)

    def test_failed_fee_or_funding_fill_is_atomic(self):
        ledger = account(100, fee_schedules={"futures": FeeSchedule(minimum=5)})
        before = ledger.snapshot()
        with self.assertRaises(FundingError):
            ledger.fill_future("F", 1, 100, "a")
        self.assertEqual(ledger.snapshot(), before)
        ledger.fill_future("F", .9, 100, "a")
        self.assertEqual(ledger.fees, 5)
        self.assert_reconciles(ledger)

    def test_treasury_sale_finances_vm_and_reduces_future_interest(self):
        ledger = account(101, fee_schedules={"treasury": FeeSchedule(fixed=1)})
        ledger.buy_treasury("bond", 105, YEAR_SECONDS, .05)
        ledger.fill_future("F", .99, 100, "a")
        ledger.settle_variation("F", 80)
        self.assertAlmostEqual(ledger.treasuries["bond"].face, 83.16)
        self.assertAlmostEqual(ledger.treasury_value, 79.2)
        self.assertEqual(ledger.funding_sale_count, 1)
        self.assertEqual(ledger.fees, 2)  # purchase and actual funding sale
        self.assert_reconciles(ledger)
        ledger.accrue(YEAR_SECONDS, .05)
        self.assertAlmostEqual(ledger.cash, 83.16)
        self.assertAlmostEqual(ledger.interest, 3.96)
        self.assertEqual(ledger.fees, 2)  # redemption has no sale commission
        self.assert_reconciles(ledger)

    def test_economic_collateral_can_lack_cash_due_to_bond_settlement_lag(self):
        ledger = account(100)
        ledger.buy_treasury("bond", 105, YEAR_SECONDS, .05, settlement_lag_seconds=86400)
        ledger.fill_future("F", 1, 100, "a")
        with self.assertRaises(FundingError):
            ledger.settle_variation("F", 80, payment_id="due")
        self.assertEqual(ledger.cash, 0)
        self.assertAlmostEqual(ledger.nav, 80)
        self.assertEqual(ledger.pending_variation["due"]["amount_usd"], -20)
        self.assertTrue(ledger.funding_blocked)
        self.assertEqual(ledger.liabilities_usd, 0)  # payable is separately counted
        self.assert_reconciles(ledger)

    def test_haircut_is_funding_not_nav_and_blocks_new_risk(self):
        ledger = account(100)
        ledger.buy_treasury("bond", 105, YEAR_SECONDS, .05)
        ledger.fill_future("F", 1, 100, "a")
        ledger.set_treasury_haircut("bond", .1)
        self.assertEqual(ledger.nav, 100)
        self.assertEqual(ledger.margin_excess, -10)
        with self.assertRaises(FundingError):
            ledger.fill_future("F", .1, 100, "b")
        ledger.fill_future("F", -.1, 100, "risk_reduction")
        self.assertFalse(ledger.funding_blocked)
        self.assert_reconciles(ledger)

    def test_cash_proxy_is_explicit_and_split_invariant_excludes_unsettled(self):
        no_proxy = account(100)
        no_proxy.accrue(YEAR_SECONDS, .1)
        self.assertEqual(no_proxy.cash, 100)
        whole = account(100, cash_interest_proxy=True)
        parts = account(100, cash_interest_proxy=True)
        for ledger in (whole, parts):
            ledger.fill_future("F", 1, 100, "a")
            ledger.mark("F", 200)
        whole.accrue(YEAR_SECONDS, .1)
        for _ in range(100):
            parts.accrue(YEAR_SECONDS / 100, .1)
        self.assertAlmostEqual(whole.cash, 100 * math.exp(.1))
        self.assertAlmostEqual(parts.cash, whole.cash)
        self.assertAlmostEqual(whole.unrealized_pnl_usd(), 100)
        self.assert_reconciles(whole)
        self.assert_reconciles(parts)

    def test_roll_does_not_sell_spot_or_treasury(self):
        rows = []
        ledger = account(110, sink=rows.append)
        ledger.register_contract(ContractSpec("G"))
        ledger.buy_treasury("bond", 105, YEAR_SECONDS, .05)
        ledger.fill_future("F", 1, 100, "first")
        ledger.fill_future("F", -1, 100, "close")
        ledger.fill_future("G", 1, 100, "open")
        self.assertEqual(ledger.treasuries["bond"].face, 105)
        self.assertEqual(ledger.funding_sale_count, 0)
        self.assertEqual(len([row for row in rows if row["kind"] == "treasury_fill"]), 1)
        self.assert_reconciles(ledger)

    def test_cash_interest_after_treasury_maturity_is_split_invariant(self):
        whole = account(100, cash_interest_proxy=True)
        parts = account(100, cash_interest_proxy=True)
        for ledger in (whole, parts):
            ledger.buy_treasury("bond", 105, YEAR_SECONDS / 2, .1)
        whole.accrue(YEAR_SECONDS, .1)
        parts.accrue(YEAR_SECONDS / 2, .1)
        parts.accrue(YEAR_SECONDS / 2, .1)
        self.assertAlmostEqual(whole.cash, 105 * math.exp(.05))
        self.assertAlmostEqual(whole.cash, parts.cash)
        self.assert_reconciles(whole)

    def test_treasury_yield_repricing_and_real_sale_reconcile(self):
        ledger = account(110)
        ledger.buy_treasury("bond", 105, YEAR_SECONDS, .05)
        ledger.mark_treasury("bond", .1)
        self.assertAlmostEqual(ledger.treasury_value, 105 / 1.1)
        before = ledger.nav
        ledger.sell_treasury("bond", 52.5, "sale")
        self.assertAlmostEqual(ledger.nav, before)
        self.assertAlmostEqual(ledger.treasury_value, 52.5 / 1.1)
        self.assert_reconciles(ledger)

    def test_spot_custody_expense_paid_in_units_once_and_not_futures(self):
        ledger = account(200)
        ledger.initialize_spot(1, 100)
        ledger.fill_future("F", 1, 100, "f")
        before = ledger.cash
        expense = ledger.accrue_spot_expense(YEAR_SECONDS, .02)
        self.assertAlmostEqual(ledger.spot_quantity, math.exp(-.02))
        self.assertEqual(ledger.cash, before)
        self.assertEqual(ledger.units["F"], 1)
        self.assertAlmostEqual(expense, 100 * (1 - math.exp(-.02)))
        self.assertEqual(expense, ledger.custody_expenses)
        self.assert_reconciles(ledger)

    def test_checkpoint_restores_lots_pending_reservations_and_ticket_fees(self):
        ledger = account(1000, fee_schedules={"futures": FeeSchedule(fixed=5, fee_bps=10)}, cash_interest_proxy=True)
        ledger.fill_future("F", 1, 100, "same-ticket")
        ledger.settle_variation("F", 120, available=False, payment_id="pending")
        ledger.reserve("waiting", 30)
        restored = FundedLedger.restore(json.loads(json.dumps(ledger.snapshot())))
        for item in (ledger, restored):
            item.pay_variation("pending")
            item.fill_future("F", .5, 120, "same-ticket")
            item.accrue(300, .04)
            item.fill_future("F", -.5, 125, "close")
        self.assertEqual(ledger.snapshot(), restored.snapshot())
        self.assert_reconciles(restored)


class FeeEngineTests(unittest.TestCase):
    def test_additive_fixed_minimum_cap_and_zero_fills(self):
        schedule = FeeSchedule(fee_bps=10, per_unit=2, fixed=5, minimum=10, cap=20)
        self.assertEqual(schedule.total_fee(0, 0), 0)
        self.assertEqual(schedule.total_fee(1, 100), 10)
        self.assertEqual(schedule.total_fee(5, 1000), 16)
        self.assertEqual(schedule.total_fee(100, 10000), 20)

    def test_many_partial_fills_restart_charge_single_ticket(self):
        engine = FeeEngine({"futures": FeeSchedule(fixed=5, minimum=10, per_unit=2, fee_bps=10)})
        total = 0
        for i in range(100):
            total += engine.charge("futures", "order", .1, 10)
            if i == 50:
                engine = FeeEngine.restore(json.loads(json.dumps(engine.snapshot())))
        self.assertAlmostEqual(total, 26)
        self.assertAlmostEqual(engine.tickets["order"]["charged"], 26)
        self.assertEqual(engine.charge("futures", "no-fill-cancel", 0, 0), 0)
        self.assertNotIn("no-fill-cancel", engine.tickets)
        # Replacement retains the same ticket if tariff preserves it; a new
        # ticket charges its own minimum rather than erasing old history.
        self.assertAlmostEqual(engine.charge("futures", "order", .1, 10), .21)
        self.assertEqual(engine.charge("futures", "replacement-new-ticket", .1, 10), 10)

    def test_ticket_schedule_and_currency_cannot_silently_change(self):
        engine = FeeEngine({"spot": FeeSchedule(fixed=1)})
        engine.charge("spot", "x", 1, 100)
        with self.assertRaises(ValueError):
            engine.charge("futures", "x", 1, 100)
        engine.schedules["spot"] = FeeSchedule(fixed=2)
        with self.assertRaises(ValueError):
            engine.charge("spot", "x", 1, 100)
        with self.assertRaises(ValueError):
            FeeSchedule(currency="BTC")


if __name__ == "__main__":
    unittest.main()
