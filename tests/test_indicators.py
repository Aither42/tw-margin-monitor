import unittest

import pandas as pd

from indicators import build_risk_river, calculate_risk, risk_level


class RiskIndicatorTests(unittest.TestCase):
    def test_score_is_bounded_and_detects_pressure(self):
        dates = pd.date_range("2026-01-02", periods=30, freq="W-FRI")
        taiex = pd.DataFrame(
            {"date": dates, "taiex": [20_000 + index * 10 for index in range(29)] + [19_000]}
        )
        margin = pd.DataFrame(
            {"date": dates, "margin_balance": [5_000 + index * 10 for index in range(30)]}
        )

        result = calculate_risk(taiex, margin)

        self.assertGreater(result["score"], 0)
        self.assertLessEqual(result["score"], 100)
        self.assertGreater(result["components"]["價跌資增背離"], 0)

    def test_empty_margin_still_returns_index_risk(self):
        dates = pd.date_range("2026-01-01", periods=10, freq="D")
        taiex = pd.DataFrame({"date": dates, "taiex": range(100, 110)})

        result = calculate_risk(taiex, pd.DataFrame())

        self.assertEqual(result["margin_change_4w"], 0)
        self.assertEqual(result["components"]["融資增幅"], 0)

    def test_risk_level_boundaries(self):
        self.assertIn("低風險", risk_level(0))
        self.assertIn("留意", risk_level(20))
        self.assertIn("偏高", risk_level(40))
        self.assertIn("高風險", risk_level(60))
        self.assertIn("極高風險", risk_level(80))

    def test_risk_river_has_three_bounded_series(self):
        dates = pd.date_range("2025-12-01", periods=160, freq="B")
        taiex = pd.DataFrame({"date": dates, "taiex": range(20_000, 20_160)})
        tpex = pd.DataFrame({"date": dates, "tpex": [250 + index / 10 for index in range(160)]})
        weekly_dates = pd.date_range("2025-12-05", periods=30, freq="W-FRI")
        margin = pd.DataFrame(
            {"date": weekly_dates, "margin_balance": [5_000 + index * 5 for index in range(30)]}
        )

        river = build_risk_river(taiex, tpex, margin)

        self.assertEqual(set(river["series"]), {"上市風險", "上櫃風險", "融資風險"})
        self.assertTrue(river["risk"].between(0, 100).all())
        self.assertTrue({"date", "risk", "raw_value", "series"}.issubset(river.columns))


if __name__ == "__main__":
    unittest.main()
