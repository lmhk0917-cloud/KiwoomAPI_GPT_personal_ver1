import os
import sys
import tempfile
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from data_store import TickStore
from quant_gpt_score_report import build_report
from quant_signal_score import build_quant_signal_score


class QuantSignalScoreTests(unittest.TestCase):
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

    def test_build_quant_signal_score_uses_feedback_and_risk(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 60,
                "risk_level": "high",
                "current_price": 100,
            },
            summary={
                "code": "005930",
                "events": [{"type": "MARKET_FOREIGN_SELL_PRESSURE"}],
                "historical_signal_stats": {
                    "learning_feedback": {
                        "quant_snapshot": {
                            "overview": {
                                "avg_net_return_60m_pct": -0.5,
                                "profit_factor_60m": 0.5,
                            },
                            "guidance": {"label": "negative_expectancy"},
                        }
                    }
                },
                "timeframes": {"1m": {"latest": {"return_1bar_pct": 0.1}}},
            },
            signal_id=10,
            scored_at="2026-06-22 10:00:00.000000",
        )

        self.assertEqual("005930", score["code"])
        self.assertEqual("long_candidate", score["decision_side"])
        self.assertLess(score["expected_value_score"], 50)
        self.assertGreater(score["market_risk_score"], 70)

    def test_store_and_report_quant_signal_scores(self):
        signal_id = self.store.save_signal_log(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 65,
                "risk_level": "medium",
                "current_price": 100,
                "stop_loss": 99,
                "target_1": 101,
                "target_2": 102,
                "reasons": ["test"],
            },
            summary={"code": "005930", "name": "Samsung", "timeframes": {}},
            detected_at="2026-06-22 10:00:00.000000",
        )
        score = build_quant_signal_score(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 65,
                "risk_level": "medium",
                "current_price": 100,
            },
            summary={"code": "005930", "events": [], "timeframes": {}},
            signal_id=signal_id,
            scored_at="2026-06-22 10:00:00.000000",
        )
        self.store.save_quant_signal_score(score)
        self.store.save_paper_trade_result({
            "signal_id": signal_id,
            "evaluated_at": "2026-06-22 11:00:00.000000",
            "code": "005930",
            "entry_time": "2026-06-22 10:00:00.000000",
            "entry_price": 100,
            "return_5m_pct": 0.1,
            "return_10m_pct": 0.2,
            "return_30m_pct": 0.3,
            "return_60m_pct": 0.4,
            "max_gain_30m_pct": 0.3,
            "max_loss_30m_pct": -0.1,
            "max_gain_60m_pct": 0.4,
            "max_loss_60m_pct": -0.1,
            "target_1_hit": True,
            "target_2_hit": False,
            "stop_loss_hit": False,
            "outcome_label": "target_1_before_stop",
        })

        report = build_report(self.store.conn, days=30, code="005930", limit=5)
        self.assertEqual(1, report["overview"]["quant_count"])
        self.assertEqual(4, len(report["horizon_summary"]))
        self.assertEqual(5, report["horizon_summary"][0]["horizon_min"])
        self.assertEqual(1, report["horizon_summary"][0]["evaluated_count"])
        self.assertGreaterEqual(len(report["target_exit_scenarios"]), 1)
        self.assertEqual(1, len(report["recent"]))
        self.assertEqual("WATCH_SUPPORT", report["recent"][0]["action_hint"])


if __name__ == "__main__":
    unittest.main()
