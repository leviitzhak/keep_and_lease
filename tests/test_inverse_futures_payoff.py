import unittest

from backtest_silver_lease_strategy import (
    InversePayoffAccount, inverse_futures_usd_payoff,
)


class InverseFuturesPayoffTests(unittest.TestCase):
    def test_long_native_payoff_is_converted_at_exit_spot(self):
        payoff = inverse_futures_usd_payoff(
            50_000, 55_000, 54_000, signed_usd_notional=1_000,
            conversion_fee_rate=0.002)
        expected_btc = 1_000 * (1 / 50_000 - 1 / 55_000)
        self.assertAlmostEqual(payoff["btc_payoff"], expected_btc)
        self.assertAlmostEqual(payoff["gross_usd_payoff"], expected_btc * 54_000)
        self.assertAlmostEqual(
            payoff["conversion_fee"], abs(expected_btc) * 54_000 * 0.002)
        self.assertAlmostEqual(
            payoff["net_usd_payoff"],
            expected_btc * 54_000 - abs(expected_btc) * 54_000 * 0.002)

    def test_short_direction_reverses_gross_payoff_but_fee_remains_a_cost(self):
        long = inverse_futures_usd_payoff(
            50_000, 45_000, 46_000, 1_000, 0.001)
        short = inverse_futures_usd_payoff(
            50_000, 45_000, 46_000, -1_000, 0.001)
        self.assertAlmostEqual(short["gross_usd_payoff"], -long["gross_usd_payoff"])
        self.assertAlmostEqual(short["conversion_fee"], long["conversion_fee"])
        self.assertAlmostEqual(
            short["net_usd_payoff"],
            short["gross_usd_payoff"] - short["conversion_fee"])

    def test_invalid_prices_and_fee_are_rejected(self):
        with self.assertRaises(ValueError):
            inverse_futures_usd_payoff(0, 50_000, 50_000)
        with self.assertRaises(ValueError):
            inverse_futures_usd_payoff(50_000, 50_000, 50_000,
                                       conversion_fee_rate=-0.01)

    def test_native_payoffs_accumulate_until_absolute_btc_threshold(self):
        account = InversePayoffAccount()
        first = account.settle(
            50_000, 50_500, 50_400, 1_000,
            conversion_fee_rate=0.002, minimum_conversion_btc=0.001)
        self.assertFalse(first["conversion_triggered"])
        self.assertEqual(first["recognized_usd_payoff"], 0)
        self.assertNotEqual(first["pending_btc"], 0)
        second = account.settle(
            50_500, 55_000, 54_000, 1_000,
            conversion_fee_rate=0.002, minimum_conversion_btc=0.001)
        self.assertTrue(second["conversion_triggered"])
        self.assertEqual(second["pending_btc"], 0)
        self.assertGreater(second["recognized_usd_payoff"], 0)
        self.assertGreater(second["conversion_fee_usd"], 0)

    def test_positive_and_negative_native_payoffs_net_before_conversion(self):
        account = InversePayoffAccount()
        gain = account.settle(
            50_000, 52_000, 51_000, 1_000, minimum_conversion_btc=1)
        loss = account.settle(
            52_000, 50_000, 50_500, 1_000, minimum_conversion_btc=1)
        expected = gain["interval_btc_payoff"] + loss["interval_btc_payoff"]
        self.assertFalse(loss["conversion_triggered"])
        self.assertAlmostEqual(loss["pending_btc"], expected)

    def test_pending_balance_can_be_force_converted_at_backtest_end(self):
        account = InversePayoffAccount()
        account.settle(50_000, 50_500, 50_400, 1_000,
                       minimum_conversion_btc=1)
        final = account.settle(
            50_500, 50_500, 50_600, 0,
            conversion_fee_rate=0.001, minimum_conversion_btc=1,
            force_conversion=True)
        self.assertTrue(final["conversion_triggered"])
        self.assertEqual(final["pending_btc"], 0)


if __name__ == "__main__":
    unittest.main()
