"""Independent audit checks catch early limit changes and mismatched entry rates."""

import importlib.util
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import unittest


SPEC = importlib.util.spec_from_file_location(
    "paired_audit_checker", Path(__file__).parents[1] / "scripts/check-paired-replay-audit.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)
YEAR_US = 365 * 86400 * 1_000_000


class PairedAuditCheckerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.checks = CHECKER.Checks()
        args = SimpleNamespace(capital=1000, fee_bps=10, participation=1,
                               max_unpaired_btc=3, interval_seconds=.5)
        self.audit = CHECKER.Audit(args, SimpleNamespace(checks=self.checks), self.db)
        self.audit.event(dict(kind="initial_holding", us=0, btc=10, price=100))

    def pair(self, source_quantity=2, target_quantity=2):
        self.audit.event(dict(kind="paired_transfer", us=1, pair_id="pair-1",
            source_symbol="SPOT", target_symbol="F", source_quantity_btc=source_quantity,
            target_quantity_btc=target_quantity, source_order_id=1, target_order_id=2,
            decision={}))
        for role, symbol, identifier, signed, limit in (
                ("source", "SPOT", 1, -source_quantity, 99),
                ("target", "F", 2, target_quantity, 95)):
            self.audit.event(dict(kind="order", us=1, order_id=identifier, pair_id="pair-1",
                role=role, symbol=symbol, signed_btc=signed, limit_price=limit,
                eligible_after_us=1, conditional=role == "target"))

    def fill(self, us, role, quantity, price):
        symbol, identifier, signed = ("SPOT", 1, -quantity) if role == "source" else ("F", 2, quantity)
        pair = self.audit.get("pairs", "pair-1")
        ratio = pair["target_quantity_btc"] / pair["source_quantity_btc"]
        source = pair["source_filled"] + (quantity if role == "source" else 0)
        target = pair["target_filled"] + (quantity if role == "target" else 0)
        self.audit.event(dict(kind="fill", us=us, order_id=identifier, pair_id="pair-1",
            role=role, symbol=symbol, signed_btc=signed, price=price,
            fee_usd=quantity * price * .001, side="sell" if role == "source" else "buy",
            trade_id=str(us), observed_btc=quantity, unpaired_btc=max(0, source-target/ratio)))

    def ack(self, fill_us, quantity):
        self.audit.event(dict(kind="fill_acknowledgement", us=fill_us+1,
            exchange_fill_us=fill_us, order_id=1, pair_id="pair-1", signed_btc=-quantity))
        self.audit.event(dict(kind="order_activation", us=fill_us+1,
                             order_id=2, eligible_after_us=fill_us+1))

    def replacement(self, kind="order_replace_requested", applied=True, **overrides):
        row = dict(kind=kind, us=15 if kind == "order_replace_requested" else 30,
            order_id=2, pair_id="pair-1", role="target", symbol="F", revision=1,
            limit_price=97, observation_us=12, decision_started_us=12,
            decision_ready_us=15, submitted_us=15, eligible_after_us=30,
            previous_limit_price=95, applied=applied)
        row.update(overrides)
        self.audit.event(row)

    def test_requested_limit_is_not_active_before_arrival(self):
        self.pair()
        self.fill(10, "source", 2, 100)
        self.ack(10, 2)
        self.replacement()
        self.assertEqual(self.audit.get("orders", 2)["limit_price"], 95)
        self.fill(20, "target", .5, 96)
        self.assertEqual(self.checks.failures, {"fill_limit": 1})

    def test_old_limit_then_arrived_limit_accept_valid_fills(self):
        self.pair()
        self.fill(10, "source", 2, 100)
        self.ack(10, 2)
        self.replacement()
        self.fill(20, "target", .5, 94)
        self.replacement("order_replace_arrival")
        self.fill(31, "target", .5, 96)
        self.assertFalse(self.checks.failures, self.checks.report())

    def test_rejected_arrival_preserves_live_limit(self):
        self.pair()
        self.fill(10, "source", 2, 100)
        self.ack(10, 2)
        self.replacement()
        self.replacement("order_replace_arrival", applied=False)
        self.assertEqual(self.audit.get("orders", 2)["limit_price"], 95)
        self.fill(31, "target", .5, 96)
        self.assertEqual(self.checks.failures, {"fill_limit": 1})

    def test_forged_arrival_or_impossible_clock_is_reported(self):
        self.pair()
        self.replacement(decision_started_us=11)
        self.replacement("order_replace_arrival", limit_price=98)
        self.assertEqual(self.checks.failures["replacement_clocks_causal"], 1)
        self.assertEqual(self.checks.failures["replacement_arrival_matches_request"], 2)

    def test_fill_at_exact_arrival_is_not_later_market_evidence(self):
        self.pair()
        self.fill(10, "source", 2, 100)
        self.ack(10, 2)
        self.replacement()
        self.replacement("order_replace_arrival")
        self.fill(30, "target", .5, 96)
        self.assertEqual(self.checks.failures, {"fill_after_eligibility": 1})

    def test_cancellation_request_does_not_stop_live_order_early(self):
        self.pair()
        request = dict(kind="order_cancel_requested", us=5, pair_id="pair-1", order_id=1,
            symbol="SPOT", role="source", reason="surplus_disappeared",
            decision_started_us=3, decision_ready_us=5, submitted_us=5, eligible_after_us=20)
        self.audit.event(request)
        self.fill(10, "source", .5, 100)
        self.audit.event({**request, "kind": "order_cancel_arrival", "us": 20, "applied": True})
        self.assertFalse(self.checks.failures, self.checks.report())
        self.fill(21, "source", .5, 100)
        self.assertEqual(self.checks.failures, {"fill_order_active": 1})

    def test_applied_replacement_cannot_ignore_intervening_fill(self):
        self.pair()
        self.fill(10, "source", 2, 100)
        self.ack(10, 2)
        self.replacement(fill_revision=1)
        self.fill(20, "target", .5, 94)
        self.replacement("order_replace_arrival", fill_revision=1)
        self.assertEqual(self.checks.failures, {"replacement_based_on_current_fills": 1})

    def test_effective_lease_uses_fifo_matched_source_fees_and_quantity(self):
        self.pair(source_quantity=2, target_quantity=1)
        self.fill(10, "source", 1, 100)
        self.ack(10, 1)
        self.fill(12, "source", 1, 200)
        self.ack(12, 1)
        self.fill(14, "target", .5, 90)
        pair = self.audit.get("pairs", "pair-1")
        expected = .04 - ((90 + .045/.5) / (100 - .1/1) - 1)
        row = dict(pair_id="pair-1", us=200, executed_effective_lease=expected,
            target_effective_lease=.2, effective_lease_shortfall=.2-expected,
            effective_lease_expiry_us=YEAR_US+150, effective_lease_rate_time_us=150,
            effective_lease_cash_rate=.04, matched_source_fees_usd=.1,
            target_fees_usd=.045, source_vwap=100, target_vwap=90)
        self.audit.effective_entry(row, pair, 1)
        self.assertFalse(self.checks.failures, self.checks.report())
        row["executed_effective_lease"] += .001
        self.audit.effective_entry(row, pair, 1)
        self.assertEqual(self.checks.failures, {"executed_effective_lease_from_matched_fills": 1})

    def test_old_fixed_archive_requires_no_effective_lease_fields(self):
        self.pair()
        self.audit.effective_entry(dict(pair_id="pair-1", us=100),
                                   self.audit.get("pairs", "pair-1"), 0)
        self.assertFalse(self.checks.failures)

    def test_actual_adaptive_events_reconcile_with_independent_checker(self):
        from paired_transfer import PairedConfig, PairedTransferAccount
        from trade_replay import Trade

        rows = []
        account = PairedTransferAccount(1000, fee_bps=10, sink=rows.append,
            config=PairedConfig(repricing_mode="adaptive", max_unpaired_btc=1,
                               max_quote_age_seconds=1000, max_quote_skew_seconds=1000),
            expiries={"F": 30 * 86400 * 1_000_000})
        account.marks["F"] = Trade(0, "F", 90, 1, "buy", "F:0", True)
        account.initialize_spot(Trade(0, "SPOT", 100, 1, "buy", "SPOT:0", True))
        account.rate = .04
        account.decide(1)
        for us in range(2, 8):
            symbol, price, side = ("SPOT", 100, "sell") if us % 2 == 0 else ("F", 90, "buy")
            account.on_trade(Trade(us, symbol, price, 1, side, f"{symbol}:{us}", True))
        account.cancel(100, "end_of_window")
        # setUp already provides the identical initial endowment.
        for row in rows:
            if row["kind"] != "initial_holding":
                self.audit.event(row)
        self.assertGreater(self.checks.counts["replacement_arrival_matches_request"], 0)
        self.assertGreater(self.checks.counts["executed_effective_lease_from_matched_fills"], 0)
        self.assertFalse(self.checks.failures, self.checks.report())

    def empirical_events(self, complete):
        from paired_transfer import PairedConfig, PairedTransferAccount
        from trade_replay import Trade
        rows=[]
        account=PairedTransferAccount(1000,fee_bps=10,sink=rows.append,
            config=PairedConfig(repricing_mode="empirical",waiting_seconds=1,max_unpaired_btc=.01),
            expiries={"F":30*86400e6})
        def trade(us,symbol="SPOT",price=100,quantity=.01,side="buy"):
            return Trade(us,symbol,price,quantity,side,f"{symbol}:{us}",True)
        account.marks["F"]=trade(0,"F",98)
        account.initialize_spot(trade(0))
        account.start_transfer(1,dict(accepted=True,source_symbol="SPOT",target_symbol="F",
            source_quantity_btc=.01,target_quantity_btc=.01,cash_rate=.04,horizon_us=30*86400e6,
            diagnostics=dict(source_sale_limit=99.9,target_buy_limit=99,
                             execution_budget_bps=100,execution_joint_success_probability=.95)))
        account.on_trade(trade(2,quantity=.01 if complete else .004,side="sell"))
        account.on_trade(trade(3,"F",98))
        account.accrue(1_000_001)
        account.on_trade(trade(1_000_002))
        account.cancel(2_000_001,"end_of_window")
        return account,[row for row in rows if row["kind"] != "initial_holding"]

    def test_empirical_completion_reconciles_exchange_fills(self):
        account,rows=self.empirical_events(True)
        for row in rows:self.audit.event(row)
        self.assertEqual(self.audit.empirical_statuses["completed"],1)
        self.assertEqual(self.audit.kinds["cash_restore_fill"],0)
        self.assertAlmostEqual(self.audit.fees.value,account.fees)
        self.assertFalse(self.checks.failures,self.checks.report())

    def test_partial_instruction_restoration_counts_cash_units_fees_without_new_pair(self):
        account,rows=self.empirical_events(False)
        for row in rows:self.audit.event(row)
        self.assertEqual(self.audit.kinds["cash_restore_fill"],1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM pairs").fetchone()[0],1)
        self.assertAlmostEqual(self.audit.units["SPOT"],account.units["SPOT"])
        self.assertAlmostEqual(self.audit.turnover.value,account.turnover)
        self.assertAlmostEqual(self.audit.fees.value,account.fees)
        self.assertFalse(self.checks.failures,self.checks.report())

    def test_lossless_study_checks_cutoff_and_all_failures(self):
        from dataclasses import asdict
        from paired_execution_study import StudyConfig,runnerstudy
        from tests.test_paired_execution_study import Store,seeds,t
        rows=[]
        cfg=StudyConfig(quantity_grid_btc=(.01,),waiting_seconds=(.5,1))
        runnerstudy(Store(seeds()+[t(100_000,btc=.005)]),0,2_000_000,{"F":30*86400e6},cfg,sink=rows.append)
        metadata=dict(label_cutoff_us=2_000_000,study_config=asdict(cfg))
        for row in rows:self.audit.study_outcome(row,metadata)
        self.assertEqual(self.audit.study_counts["partial"],2)
        self.assertEqual(self.audit.study_counts["completed"],0)
        for group in self.audit.study_groups.values():
            self.assertEqual(group["histogram"][-1],group["samples"])
        self.assertFalse(self.checks.failures,self.checks.report())
        forged={**rows[0],"decision_us":60_000_000,"label_available_us":60_500_000}
        self.audit.study_outcome(forged,metadata)
        self.assertEqual(self.checks.failures["study_label_before_cutoff"],1)
        self.assertEqual(self.checks.failures["study_complete_window_before_cutoff"],1)

    def test_pending_decision_end_window_censor_requires_no_pair_or_execution(self):
        row=dict(kind="empirical_instruction_result",us=100,pair_id=None,
            status="end_window_censored",reason="decision_not_completed_before_window_end",
            decision_started_us=1,deadline_us=1_000_001,completed_by_deadline=False,
            actual_source_btc=0,actual_target_btc=0,unmatched_source_btc=0,residual_cash_usd=0)
        self.audit.event(row)
        self.assertFalse(self.checks.failures,self.checks.report())
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM pairs").fetchone()[0],0)
        self.assertEqual(self.audit.empirical_statuses["end_window_censored"],1)
        self.audit.event({**row,"actual_source_btc":.001})
        self.assertEqual(self.checks.failures,{"empirical_unsubmitted_censor_has_no_execution":1})

    @staticmethod
    def near_expiry_study_row():
        # Recorded four-minute-to-expiry cohort: algebraically equivalent
        # price-ratio forms differ by 1.07e-12 bp before annualization.
        return dict(kind="execution_outcome", symbol="BTC-12JUN26",
            decision_us=1781250960000000, expiry_us=1781251200000000,
            label_available_us=1781250962000000, wait_seconds=2,
            requested_source_btc=.001, source_fill_fraction=1,
            target_fill_fraction=1, completed=True,
            source_observed_price=63053.62, target_observed_price=62950,
            source_vwap=63053.61, target_vwap=62950,
            source_completed_seconds=.36784, target_completed_seconds=1.841,
            raw_basis_slip_bps=.0015833457233850748,
            annualized_slip_bps=208.05162805279883,
            max_adverse_budget_bps=.0015859517665806067)

    def test_near_expiry_study_annualization_accepts_float_cancellation(self):
        row = self.near_expiry_study_row()
        self.audit.study_outcome(row, dict(label_cutoff_us=row["expiry_us"]))
        self.assertFalse(self.checks.failures, self.checks.report())
        self.assertGreater(self.checks.max_errors["study_basis_from_vwaps"], 0)
        self.assertEqual(self.checks.max_errors["study_annualization_original_maturity"], 0)

    def test_near_expiry_study_rejects_incorrect_annualized_value(self):
        row = self.near_expiry_study_row()
        row["annualized_slip_bps"] += .01
        self.audit.study_outcome(row, dict(label_cutoff_us=row["expiry_us"]))
        self.assertEqual(self.checks.failures, {"study_annualization_original_maturity": 1})

    def test_near_expiry_study_still_independently_checks_raw_basis(self):
        row = self.near_expiry_study_row()
        row["raw_basis_slip_bps"] += .001
        row["annualized_slip_bps"] = row["raw_basis_slip_bps"] / (
            (row["expiry_us"] - row["decision_us"]) / YEAR_US)
        self.audit.study_outcome(row, dict(label_cutoff_us=row["expiry_us"]))
        self.assertEqual(self.checks.failures, {"study_basis_from_vwaps": 1})


if __name__ == "__main__":
    unittest.main()
