import json
import unittest

import silver_strategy_gui as gui


class BtcProductSemanticsTests(unittest.TestCase):
    def test_btc_uses_direct_holding_naming_without_an_etf(self):
        product = gui.PRODUCTS["btc"]
        self.assertEqual(product["holding_label"], "Direct holding")
        self.assertEqual(product["etf"], "Direct BTC holding")
        self.assertEqual(product["replication"], "direct holding")

    def test_btc_defaults_and_serialized_gui_profile(self):
        defaults = gui.product_payload(
            {"futures_contract_type": "regular"}, "btc")
        self.assertEqual(defaults["futures_contract_type"], "inverse")
        self.assertEqual(defaults["trading_calendar"], "all_days")
        self.assertEqual(defaults["slv_expense"], 0)
        payload = gui.product_payload({
            "commodity_parameters": json.dumps({
                "btc": {"futures_contract_type": "regular"}
            })
        }, "btc")
        self.assertEqual(payload["futures_contract_type"], "regular")


if __name__ == "__main__":
    unittest.main()
