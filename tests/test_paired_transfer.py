import json
import unittest
from unittest.mock import patch
from dataclasses import replace

from paired_transfer import PairedConfig, PairedTransferAccount
from trade_replay import Trade


DAY = 86400 * 1_000_000


def trade(us, symbol="SPOT", price=100, btc=1, side="buy", identifier=None, executable=True):
    return Trade(us, symbol, price, btc, side, identifier or f"{symbol}:{us}", executable)


def decision(source="SPOT", target="F", q=1, target_q=None):
    return dict(accepted=True, source_symbol=source, target_symbol=target,
                source_quantity_btc=q, target_quantity_btc=q if target_q is None else target_q,
                keep_btc=q, swap_btc=q+0.01, edge_btc=.01, horizon_us=DAY,
                cash_rate=.04, reason="net_surplus")


class PairedTransferTests(unittest.TestCase):
    def account(self, **kwargs):
        cfg = dict(max_unpaired_btc=1, max_quote_age_seconds=1000,
                   max_quote_skew_seconds=1000, price_limit_bps=1000)
        cfg.update(kwargs)
        audit = []
        account = PairedTransferAccount(1000, config=PairedConfig(**cfg), sink=audit.append,
                                        expiries={"F": 30*DAY, "G": 60*DAY})
        account.marks["F"] = trade(0, "F")
        account.marks["G"] = trade(0, "G")
        account.initialize_spot(trade(0))
        return account, audit

    def open_future(self, account, q=1):
        account.start_transfer(1, decision(q=q))
        account.on_trade(trade(2, side="sell", btc=q))
        account.on_trade(trade(3, "F", btc=q))

    def test_spot_sale_precedes_funded_future_and_only_actual_fills_count(self):
        account, audit = self.account()
        pair = account.start_transfer(1, decision(q=2))
        account.on_trade(trade(2, "F"))
        self.assertEqual(account.fill_count, 0)
        account.on_trade(trade(3, side="sell", btc=.3))
        self.assertAlmostEqual(account.cash, 30)
        self.assertAlmostEqual(account.ledger.available_cash, 0)
        account.on_trade(trade(4, "F", btc=.1))
        self.assertAlmostEqual(account.units["F"], .1)
        self.assertAlmostEqual(pair.unpaired_btc, .2)
        self.assertAlmostEqual(account.reconstruction_error(), 0)
        self.assertEqual(len([r for r in audit if r["kind"] == "fill"]), 2)

    def test_reverse_does_not_release_collateral_on_unfilled_exit(self):
        account, _ = self.account()
        self.open_future(account)
        account.start_transfer(4, decision("F", "SPOT"))
        account.on_trade(trade(5, "SPOT"))
        self.assertEqual(account.units["SPOT"], 9)
        self.assertEqual(account.units["F"], 1)
        account.on_trade(trade(6, "F", side="sell", btc=.4))
        self.assertAlmostEqual(account.units["F"], .6)
        account.on_trade(trade(7, "SPOT", btc=.4))
        self.assertAlmostEqual(account.units["SPOT"], 9.4)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_roll_reuses_funding_without_spot_orders(self):
        account, audit = self.account()
        self.open_future(account)
        audit.clear()
        account.start_transfer(4, decision("F", "G"))
        account.on_trade(trade(5, "F", side="sell"))
        account.on_trade(trade(6, "G"))
        self.assertEqual(account.units["SPOT"], 9)
        self.assertEqual(account.units["F"], 0)
        self.assertEqual(account.units["G"], 1)
        self.assertFalse(any(r.get("symbol") == "SPOT" and r["kind"] in ("fill", "order") for r in audit))

    def test_pending_pair_survives_opposite_signal_and_restart(self):
        account, _ = self.account()
        pair = account.start_transfer(1, decision(q=2))
        account.on_trade(trade(2, side="sell", btc=.2))
        self.assertIsNone(account.start_transfer(3, decision("F", "SPOT")))
        self.assertEqual(account.active_pair_id, pair.pair_id)
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        for other in (account, restored):
            other.on_trade(trade(4, "F", btc=.2))
            other.on_trade(trade(5, side="sell", btc=.8))
        self.assertEqual(account.snapshot(), restored.snapshot())

    def test_feed_delay_uses_availability_and_keeps_inventory(self):
        account, _ = self.account(futures_feed_delay_seconds=2)
        self.assertNotIn("F", account.observed_quotes())
        account.accrue(2_000_000)
        self.assertIn("F", account.observed_quotes())
        account.on_trade(trade(3_000_000, "F", price=200))
        self.assertEqual(account.marks["F"].price, 200)
        self.assertEqual(account.observed_quotes()["F"].price, 100)
        account.accrue(5_000_000)
        self.assertEqual(account.observed_quotes()["F"].price, 200)
        self.assertEqual(account.units["SPOT"], 10)
        self.assertIsNone(account.observed_quotes()["F"].size_btc)

    def test_delayed_ack_preserves_actual_funding_and_blocks_next_action(self):
        account, _ = self.account(response_delay_seconds=2)
        account.start_transfer(1, decision())
        account.on_trade(trade(2, side="sell"))
        self.assertEqual(account.units["SPOT"], 9)
        self.assertEqual(account.known_units["SPOT"], 10)
        self.assertEqual(account.ledger.available_cash, 0)
        account.on_trade(trade(3, "F"))
        self.assertEqual(account.units.get("F", 0), 0)
        account.on_trade(trade(2_000_003, "F"))
        self.assertEqual(account.units["F"], 1)
        self.assertEqual(account.known_units.get("F", 0), 0)
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        for other in (account, restored):
            other.accrue(4_000_003)
        self.assertEqual(account.snapshot(), restored.snapshot())
        self.assertEqual(account.known_units["F"], 1)

    def test_unpaired_cap_and_timeout_preserve_unresolved_source_sale(self):
        account, _ = self.account(max_unpaired_btc=.2, max_legging_seconds=1)
        pair = account.start_transfer(1, decision(q=1))
        account.on_trade(trade(2, side="sell"))
        account.on_trade(trade(3, side="sell"))
        self.assertAlmostEqual(pair.source_filled_btc, .2)
        account.accrue(1_000_003)
        self.assertEqual(pair.status, "timed_out")
        self.assertAlmostEqual(account.units["SPOT"], 9.8)
        self.assertAlmostEqual(account.cash, 20)
        account.cancel(1_000_004, "end_of_window")
        self.assertEqual(account.summary()["unresolved"], 1)
        self.assertAlmostEqual(account.ledger.reservations[pair.pair_id], 20)

    def test_stale_observation_neither_sells_inventory_nor_replaces_pair(self):
        account, _ = self.account(max_quote_age_seconds=.01)
        self.open_future(account)
        account.decide(100_000)
        self.assertEqual(account.units["F"], 1)
        self.assertEqual(account.units["SPOT"], 9)
        self.assertEqual(account.fill_count, 2)

    def test_daily_vm_moves_unsettled_pnl_without_new_profit_or_trade(self):
        account, _ = self.account()
        self.open_future(account)
        account.on_trade(trade(10, "F", price=120))
        self.assertEqual(account.cash, 100)
        self.assertEqual(account.ledger.unrealized_pnl_usd(), 20)
        value = account.nav
        account.accrue(DAY)
        self.assertEqual(account.cash, 120)
        self.assertEqual(account.ledger.unrealized_pnl_usd(), 0)
        self.assertEqual(account.nav, value)
        self.assertEqual(account.fill_count, 2)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_actual_spread_slippage_and_custody_expense_reconcile(self):
        account, _ = self.account(half_spread_bps=10, slippage_bps=10, proxy_expense_rate=.01)
        account.start_transfer(1, decision(q=1, target_q=.98))
        account.on_trade(trade(2, side="sell"))
        account.on_trade(trade(3, "F", btc=.98))
        self.assertAlmostEqual(account.ledger.marks["F"], 100)
        self.assertAlmostEqual(account.marks["F"].price, 100)
        self.assertLess(account.nav, 1000)
        account.accrue(DAY)
        self.assertLess(account.units["SPOT"], 9)
        self.assertGreater(account.fees, 0)
        self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)

    def test_first_partial_fills_pay_fixed_ticket_once(self):
        account, audit = self.account(spot_fixed_fee_usd=1, futures_fixed_fee_usd=1)
        account.start_transfer(1, decision(q=1, target_q=.97))
        account.on_trade(trade(2, side="sell", btc=.1))
        account.on_trade(trade(3, "F", btc=.01))
        account.on_trade(trade(4, side="sell", btc=.9))
        account.on_trade(trade(5, "F", btc=1))
        self.assertAlmostEqual(account.fees, 2)
        self.assertAlmostEqual(account.units["F"], .97)
        self.assertEqual(account.summary()["completed"], 1)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_no_fill_and_wrong_side_do_not_charge_fee(self):
        account, _ = self.account(spot_fixed_fee_usd=5)
        account.start_transfer(1, decision())
        account.on_trade(trade(2, side="buy"))
        account.on_trade(trade(3, side="sell", executable=False))
        account.cancel(4)
        self.assertEqual(account.fees, 0)
        self.assertEqual(account.fill_count, 0)

    def test_expiry_requires_verified_settlement_preserves_nav(self):
        account, _ = self.account()
        self.open_future(account)
        account.settle("F", 30*DAY, 110, "fixture official delivery")
        self.assertEqual(account.units["F"], 0)
        self.assertEqual(account.cash, 110)
        self.assertAlmostEqual(account.reconstruction_error(), 0)

    def test_unknown_and_negative_configuration_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            PairedConfig.from_payload({"paired_leverage": 2})
        with self.assertRaises(ValueError):
            PairedConfig(spot_feed_delay_seconds=-1)

    def test_hidden_futures_mark_does_not_enter_economic_input(self):
        from paired_transfer_economics import TransferDecision
        account, _ = self.account()
        self.open_future(account)
        account.config.futures_feed_delay_seconds = 2
        other = PairedTransferAccount.restore(account.snapshot())
        account.on_trade(trade(10, "F", price=101))
        other.on_trade(trade(10, "F", price=150))
        inputs = []
        def capture(now, source, target, spot, **kwargs):
            inputs.append((source, target, spot, kwargs["cash_rate"]))
            return TransferDecision(False, "fixture_keep", source.quote.symbol, target.symbol)
        with patch("paired_transfer_economics.evaluate_transfer", side_effect=capture):
            account.decide(11)
            first = list(inputs)
            inputs.clear()
            other.decide(11)
        self.assertEqual(first, inputs)
        self.assertNotEqual(account.nav, other.nav)

    def test_pending_recheck_uses_remaining_ticket_fee_and_keeps_recovery(self):
        from paired_transfer_economics import TransferDecision
        account, audit = self.account(spot_fixed_fee_usd=1, futures_fixed_fee_usd=1)
        pair = account.start_transfer(1, decision(q=2, target_q=1.95))
        account.on_trade(trade(2, side="sell", btc=.2))
        calls = []
        def reject(now, source, target, spot, **kwargs):
            calls.append((source, kwargs))
            return TransferDecision(False, "no_net_gain", source.quote.symbol, target.symbol)
        with patch("paired_transfer_economics.evaluate_transfer", side_effect=reject):
            account.decide(3)
        source, options = calls[0]
        self.assertAlmostEqual(source.quantity_btc, 1.8)
        self.assertEqual(options["horizon_limit_us"], DAY)
        self.assertEqual(options["comparison_horizon_us"], DAY)
        self.assertAlmostEqual(options["target_quantity_btc"], 1.8*1.95/2)
        self.assertEqual(options["execution_price_overrides"], {
            "source": account.orders["SPOT"].limit_price,
            "target": account.orders["F"].limit_price})
        self.assertEqual(options["entry_fees"]["source"].total_fee(1, 100), 0)
        self.assertEqual(options["entry_fees"]["target"].total_fee(1, 100), 1)
        self.assertFalse(account.orders["SPOT"].active)
        self.assertTrue(account.orders["F"].active)
        self.assertAlmostEqual(pair.unpaired_btc, .2)

    def test_expiry_risk_overrides_negative_edge_and_stale_rate_only_to_spot(self):
        from paired_transfer_economics import TransferDecision
        account, _ = self.account()
        self.open_future(account)
        account.expiries["F"] = DAY
        def costly(now, source, target, spot, **kwargs):
            return TransferDecision(False, "insufficient_surplus", source.quote.symbol, target.symbol,
                source_quantity_btc=source.quantity_btc, target_quantity_btc=source.quantity_btc*.9,
                horizon_us=DAY, keep_btc=1, swap_btc=.9, edge_btc=-.1,
                diagnostics={"swap": {"funding_feasible": True}})
        with patch("paired_transfer_economics.evaluate_transfer", side_effect=costly):
            pair = account.decide(4, rate_snapshot={"stale": True, "allows_new_transfers": False})
        self.assertEqual(pair.reason, "forced_expiry_exit")
        self.assertEqual(pair.source_symbol, "F")
        self.assertEqual(pair.target_symbol, "SPOT")
        self.assertEqual(pair.source_quantity_btc, 1)

    def test_matched_fill_vwap_excludes_unmatched_source_tail(self):
        account, audit = self.account()
        pair = account.start_transfer(1, decision(q=1))
        account.on_trade(trade(2, price=100, side="sell", btc=.2))
        account.on_trade(trade(3, "F", btc=.2))
        account.on_trade(trade(4, price=110, side="sell", btc=.3))
        account.cancel(5, "end_of_window")
        result = [r for r in audit if r["kind"] == "paired_transfer_result"][-1]
        self.assertAlmostEqual(result["matched_source_value_usd"], 20)
        self.assertAlmostEqual(result["executed_price_only_lease"], .04)
        self.assertAlmostEqual(pair.unpaired_btc, .3)

    def test_completed_pairs_and_tickets_are_audited_then_compacted(self):
        account, audit = self.account()
        self.open_future(account)
        self.assertEqual(account.pairs, {})
        self.assertEqual(account.ledger.fee_engine.tickets, {})
        self.assertEqual(account.summary()["completed"], 1)
        self.assertTrue(any(r["kind"] == "paired_transfer_result" for r in audit))
        state = account.snapshot()
        restored = PairedTransferAccount.restore(state)
        restored.known_units["SPOT"] = 0
        self.assertNotEqual(restored.known_units, state["known_units"])

    def test_non_executable_observation_may_mark_but_cannot_authorize(self):
        account, _ = self.account()
        account.on_trade(trade(1, "F", price=99, executable=False))
        self.assertEqual(account.marks["F"].price, 99)
        self.assertIsNone(account.start_transfer(2, decision()))
        self.assertEqual(account.last_reason, "non_executable_observation")
        self.assertEqual(account.units["SPOT"], 10)

    def test_additional_source_fills_do_not_reset_legging_deadline(self):
        account, _ = self.account(max_legging_seconds=1)
        pair = account.start_transfer(1, decision(q=1))
        account.on_trade(trade(2, side="sell", btc=.2))
        account.on_trade(trade(500_000, side="sell", btc=.2))
        account.accrue(1_000_003)
        self.assertEqual(pair.status, "timed_out")
        self.assertEqual(pair.first_unpaired_us, 2)


class AdaptivePairedTransferTests(unittest.TestCase):
    def account(self, *, fee_bps=0, **kwargs):
        config = dict(repricing_mode="adaptive", price_limit_bps=10,
                      max_unpaired_btc=1, max_quote_age_seconds=1000,
                      max_quote_skew_seconds=1000)
        config.update(kwargs)
        audit = []
        account = PairedTransferAccount(1000, fee_bps=fee_bps,
            config=PairedConfig(**config), sink=audit.append, expiries={"F": 30*DAY})
        account.marks["F"] = trade(0, "F", 98)
        account.initialize_spot(trade(0))
        account.rate = .04
        return account, audit

    def test_economic_limit_recovers_fill_missed_by_fixed_ten_basis_points(self):
        fixed, _ = self.account(repricing_mode="fixed")
        adaptive, audit = self.account()
        for account in (fixed, adaptive):
            account.decide(1)
            account.on_trade(trade(2, side="sell", btc=.1))
            account.on_trade(trade(3, "F", 98.5, btc=.1))
        self.assertEqual(fixed.fill_count, 1)
        self.assertEqual(adaptive.fill_count, 2)
        self.assertAlmostEqual(adaptive.units["F"], .1)
        pair = adaptive.pairs[adaptive.active_pair_id]
        self.assertAlmostEqual(pair.unpaired_btc, 0)
        self.assertGreater(pair.target_effective_lease, 0)
        self.assertTrue(any(r["kind"] == "order_replace_arrival" and r["applied"] for r in audit))
        self.assertAlmostEqual(adaptive.reconstruction_error(), 0)

    def test_initial_decision_freezes_prices_and_observation_delay_is_additive(self):
        account, audit = self.account(observation_delay_seconds=.2,
            futures_feed_delay_seconds=.1, decision_delay_seconds=.3, order_delay_seconds=.4)
        self.assertNotIn("SPOT", account.observed_quotes())
        account.accrue(200_000)
        self.assertIn("SPOT", account.observed_quotes())
        self.assertNotIn("F", account.observed_quotes())
        account.accrue(300_000)
        self.assertIsNone(account.decide(300_000))
        self.assertTrue(account.pending_initial_decision)
        account.on_trade(trade(310_000, "F", 101))
        account.accrue(610_000)
        self.assertEqual(account.observed_marks["F"].price, 101)
        pair = account.pairs[account.active_pair_id]
        self.assertEqual(pair.decision["quote_snapshots"]["F"]["price"], 98)
        self.assertEqual(pair.submitted_us, 600_000)
        self.assertEqual(account.orders["SPOT"].eligible_us, 1_000_000)
        initial = next(r for r in audit if r["kind"] == "order")
        self.assertEqual(initial["decision_started_us"], 300_000)
        self.assertEqual(initial["decision_ready_us"], 600_000)
        self.assertEqual(initial["observation_us"], 300_000)

    def test_recovery_waits_for_ack_decision_and_transport(self):
        account, audit = self.account(decision_delay_seconds=.2, order_delay_seconds=.3,
                                      response_delay_seconds=.4)
        account.decide(1)
        account.accrue(500_001)
        account.on_trade(trade(500_002, side="sell", btc=.1))
        self.assertEqual(account.fill_count, 1)
        self.assertFalse(account.orders["F"].active)
        account.on_trade(trade(800_000, "F", 98, btc=.1))
        self.assertEqual(account.fill_count, 1)
        account.accrue(1_400_002)
        self.assertTrue(account.orders["F"].active)
        self.assertEqual(account.orders["F"].eligible_us, 1_400_002)
        account.on_trade(trade(1_400_002, "F", 98.5, btc=.1))
        self.assertEqual(account.fill_count, 1)
        account.on_trade(trade(1_400_003, "F", 98.5, btc=.1))
        self.assertEqual(account.fill_count, 2)
        arrived = [r for r in audit if r["kind"] == "order_replace_arrival" and r["applied"]]
        self.assertTrue(any(r["decision_started_us"] == 900_002 and r["decision_ready_us"] == 1_100_002
                            and r["eligible_after_us"] == 1_400_002 for r in arrived))

    def test_actual_source_fill_anchors_recovery_despite_later_spot_rise(self):
        account, _ = self.account()
        account.decide(1)
        account.on_trade(trade(2, side="sell", price=100, btc=.1))
        cap = account.orders["F"].limit_price
        account.on_trade(trade(3, price=120, side="buy"))
        self.assertAlmostEqual(account.orders["F"].limit_price, cap, places=7)
        account.on_trade(trade(4, "F", price=110, btc=.1))
        self.assertEqual(account.fill_count, 1)
        self.assertAlmostEqual(account.pairs[account.active_pair_id].source_filled_btc, .1)
        account.on_trade(trade(5, side="sell", price=120, btc=1))
        self.assertEqual(account.fill_count, 1, "A new source lot waits for its funded target")

    def test_old_source_limit_remains_live_until_replacement_arrives(self):
        account, _ = self.account(order_delay_seconds=.5)
        account.decide(1)
        account.accrue(500_001)
        old = account.orders["SPOT"].limit_price
        account.on_trade(trade(600_000, "F", price=98.5))
        self.assertEqual(account.orders["SPOT"].limit_price, old)
        account.on_trade(trade(700_000, side="sell", price=100, btc=.1))
        self.assertEqual(account.fill_count, 1)
        account.accrue(1_100_000)
        self.assertEqual(account.orders["SPOT"].limit_price, old,
                         "A stale fill revision must not overwrite the live source")
        self.assertFalse(account.orders["F"].active,
                         "Recovery must wait for its executed-price instruction")

    def test_restart_preserves_queued_decision_replacement_and_partial_fee_lot(self):
        account, _ = self.account(order_delay_seconds=.3, decision_delay_seconds=.2,
                                 futures_fixed_fee_usd=.1)
        account.decide(1)
        first = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        for item in (account, first):
            item.accrue(500_001)
            item.on_trade(trade(500_002, side="sell", btc=.2))
            item.accrue(700_002)
        self.assertEqual(account.snapshot(), first.snapshot())
        restored = PairedTransferAccount.restore(json.loads(json.dumps(account.snapshot())))
        for item in (account, restored):
            item.on_trade(trade(1_000_003, "F", price=98, btc=.05))
            item.accrue(1_500_003)
            item.on_trade(trade(1_500_004, "F", price=98, btc=.15))
        self.assertEqual(account.snapshot(), restored.snapshot())
        self.assertAlmostEqual(account.reconstruction_error(), 0, places=8)

    def test_economic_cancel_delays_but_exchange_timeout_remains_standing_guard(self):
        account, audit = self.account(decision_delay_seconds=.2, order_delay_seconds=.3)
        account.decide(1)
        account.accrue(500_001)
        pair = account.pairs[account.active_pair_id]
        account.decide(600_000, rate_snapshot={"allows_new_transfers": False})
        self.assertTrue(account.orders["SPOT"].active)
        self.assertEqual(pair.status, "pending")
        account.on_trade(trade(900_000, side="sell", btc=.1))
        self.assertEqual(account.fill_count, 1)
        account.accrue(1_100_000)
        self.assertFalse(account.orders["SPOT"].active)
        self.assertEqual(pair.status, "cancelled")
        arrival = next(r for r in audit if r["kind"] == "order_cancel_arrival")
        self.assertEqual(arrival["decision_started_us"], 600_000)
        self.assertEqual(arrival["decision_ready_us"], 800_000)
        self.assertEqual(arrival["us"], 1_100_000)

    def test_repricing_queue_coalesces_during_transport(self):
        account, _ = self.account(order_delay_seconds=1)
        account.decide(1)
        account.accrue(1_000_001)
        account.on_trade(trade(1_000_002, side="sell", btc=.1))
        for offset in range(1, 501):
            account.on_trade(trade(1_000_002+offset, price=100+offset/1000))
        self.assertLessEqual(len(account.command_queue), 1)
        self.assertLessEqual(len(account.decision_queue), 1)
        account.accrue(2_000_002)
        self.assertTrue(account.orders["F"].active)
        self.assertEqual(account.orders["F"].eligible_us, 2_000_002)
        self.assertLessEqual(len(account.command_queue), 1)

    def test_explicit_order_delay_overrides_legacy_and_config_round_trips(self):
        absent = PairedConfig.from_payload({"paired_repricing_mode": "adaptive"})
        legacy = PairedTransferAccount(1000, delay_us=4_000_000, config=absent)
        explicit = PairedConfig.from_payload({"paired_repricing_mode": "adaptive", "paired_order_delay_seconds": .3})
        override = PairedTransferAccount(1000, delay_us=4_000_000, config=explicit)
        self.assertEqual(legacy.delay_us, 4_000_000)
        self.assertEqual(override.delay_us, 300_000)
        for bad in ("dynamic", None, 7):
            with self.assertRaises(ValueError):
                PairedConfig(repricing_mode=bad)
        with self.assertRaises(ValueError):
            PairedConfig(order_delay_seconds=-.1)


if __name__ == "__main__":
    unittest.main()
