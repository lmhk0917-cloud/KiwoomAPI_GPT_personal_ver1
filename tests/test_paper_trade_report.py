import os
import sys
import tempfile
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from data_store import TickStore
from paper_trade_report import build_report, build_window_comparison, parse_windows


class PaperTradeReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = TickStore(db_path=self.tmp.name)

    def tearDown(self):
        self.store.close()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_report_separates_profit_direction_and_sample_labels(self):
        for index, return_60m in enumerate([0.8, 0.7, 0.6], start=1):
            signal_id = self._save_signal(index, "AVOID_DOWNTREND")
            self.store.save_paper_trade_result({
                "signal_id": signal_id,
                "evaluated_at": "2026-06-25 11:{:02d}:00.000000".format(index),
                "code": "000660",
                "entry_time": "2026-06-25 10:{:02d}:00.000000".format(index),
                "entry_price": 100.0,
                "return_5m_pct": return_60m / 4,
                "return_10m_pct": return_60m / 3,
                "return_30m_pct": return_60m / 2,
                "return_60m_pct": return_60m,
                "max_gain_30m_pct": return_60m / 2,
                "max_loss_30m_pct": 0.0,
                "max_gain_60m_pct": return_60m,
                "max_loss_60m_pct": 0.0,
                "target_1_hit": True,
                "target_2_hit": True,
                "stop_loss_hit": False,
                "outcome_label": "target_1_before_stop",
            })

        report = build_report(self.store.conn, min_sample=2, recent_limit=3)
        by_action = {row["group_name"]: row for row in report["by_action"]}
        row = by_action["AVOID_DOWNTREND"]

        self.assertEqual("full_60m_sample", report["sample_summary"]["sample_label"])
        self.assertEqual("positive_net_expectancy", row["profit_label"])
        self.assertEqual("direction_contra", row["directional_label"])
        self.assertEqual("caution_missed_upside", row["interpretation_hint"])

    def test_window_comparison_summarizes_multiple_periods(self):
        signal_id = self._save_signal(1, "WATCH_SUPPORT")
        self.store.save_paper_trade_result({
            "signal_id": signal_id,
            "evaluated_at": "2026-06-25 11:01:00.000000",
            "code": "000660",
            "entry_time": "2026-06-25 10:01:00.000000",
            "entry_price": 100.0,
            "return_5m_pct": 0.1,
            "return_10m_pct": 0.2,
            "return_30m_pct": 0.3,
            "return_60m_pct": 0.6,
            "max_gain_30m_pct": 0.3,
            "max_loss_30m_pct": 0.0,
            "max_gain_60m_pct": 0.6,
            "max_loss_60m_pct": 0.0,
            "target_1_hit": True,
            "target_2_hit": False,
            "stop_loss_hit": False,
            "outcome_label": "target_1_before_stop",
        })

        report = build_window_comparison(
            self.store.conn,
            windows=[7, 30],
            min_sample=1,
        )

        self.assertEqual([7, 30], report["filters"]["windows"])
        self.assertEqual(2, len(report["windows"]))
        self.assertEqual(1, report["windows"][0]["overview"]["evaluated_60m_count"])
        self.assertIn("long_candidate", report["windows"][0])

    def test_parse_windows_deduplicates_and_validates(self):
        self.assertEqual([7, 30, 60], parse_windows("7,30,30,60"))
        with self.assertRaises(Exception):
            parse_windows("7,0")

    def _save_signal(self, index, action_hint):
        return self.store.save_signal_log(
            signal={
                "action_hint": action_hint,
                "confidence_score": 60,
                "risk_level": "medium",
                "current_price": 100.0,
                "stop_loss": 99.0,
                "target_1": 101.0,
                "target_2": 102.0,
                "reasons": ["test"],
            },
            summary={
                "code": "000660",
                "name": "SK hynix",
                "timeframes": {},
            },
            detected_at="2026-06-25 10:{:02d}:00.000000".format(index),
        )


if __name__ == "__main__":
    unittest.main()
