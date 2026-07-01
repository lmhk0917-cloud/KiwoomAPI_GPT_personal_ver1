import os
import sys
import tempfile
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from data_store import TickStore
from quant_feedback import build_feedback_snapshot, save_feedback_snapshots


class QuantFeedbackTests(unittest.TestCase):
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

    def test_feedback_snapshot_computes_quant_metrics_and_guidance(self):
        signal_ids = []
        for index, return_60m in enumerate([1.2, 0.9, 0.7, -0.1, -0.1], start=1):
            signal_id = self._save_signal(index)
            signal_ids.append(signal_id)
            self.store.save_paper_trade_result({
                "signal_id": signal_id,
                "evaluated_at": "2026-06-22 11:{:02d}:00.000000".format(index),
                "code": "005930",
                "entry_time": "2026-06-22 10:{:02d}:00.000000".format(index),
                "entry_price": 100.0,
                "return_5m_pct": return_60m / 4,
                "return_10m_pct": return_60m / 3,
                "return_30m_pct": return_60m / 2,
                "return_60m_pct": return_60m,
                "max_gain_30m_pct": max(return_60m, 0),
                "max_loss_30m_pct": min(return_60m, 0),
                "max_gain_60m_pct": max(return_60m, 0),
                "max_loss_60m_pct": min(return_60m, 0),
                "target_1_hit": return_60m > 0,
                "target_2_hit": return_60m > 0.5,
                "stop_loss_hit": return_60m < 0,
                "outcome_label": "target_1_before_stop" if return_60m > 0 else "stop_before_target",
            })

        snapshot = build_feedback_snapshot(
            conn=self.store.conn,
            days=30,
            min_sample=3,
            code="005930",
        )

        self.assertEqual(snapshot["overview"]["signal_count"], 5)
        self.assertEqual(snapshot["overview"]["evaluated_count"], 5)
        self.assertGreater(snapshot["overview"]["profit_factor_60m"], 1)
        self.assertIn(snapshot["guidance"]["label"], ["positive_expectancy", "neutral_expectancy"])

    def test_save_feedback_snapshots_persists_latest_snapshot(self):
        signal_id = self._save_signal(1)
        self.store.save_paper_trade_result({
            "signal_id": signal_id,
            "evaluated_at": "2026-06-22 11:00:00.000000",
            "code": "005930",
            "entry_time": "2026-06-22 10:00:00.000000",
            "entry_price": 100.0,
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

        snapshots = save_feedback_snapshots(self.store, days=30, min_sample=1, codes=["005930"])
        latest = self.store.get_latest_quant_feedback_snapshot(code="005930")

        self.assertEqual(len(snapshots), 2)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["scope"], "code")
        self.assertEqual(latest["code"], "005930")

    def test_caution_action_positive_return_is_missed_upside_not_prefer(self):
        for index, return_60m in enumerate([0.8, 0.7, 0.6], start=1):
            signal_id = self._save_signal(index, action_hint="AVOID_DOWNTREND")
            self.store.save_paper_trade_result({
                "signal_id": signal_id,
                "evaluated_at": "2026-06-22 11:{:02d}:00.000000".format(index),
                "code": "005930",
                "entry_time": "2026-06-22 10:{:02d}:00.000000".format(index),
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
                "target_2_hit": False,
                "stop_loss_hit": False,
                "outcome_label": "target_1_before_stop",
            })

        snapshot = build_feedback_snapshot(
            conn=self.store.conn,
            days=30,
            min_sample=3,
            code="005930",
        )

        guidance = snapshot["guidance"]
        self.assertEqual([], guidance["prefer_actions"])
        self.assertEqual("AVOID_DOWNTREND", guidance["missed_upside_actions"][0]["action_hint"])
        self.assertIn("missed upside", guidance["summary"])

    def test_feedback_snapshot_includes_cluster_metrics(self):
        for minute, return_60m in [(1, 0.8), (4, 0.6), (20, -0.4)]:
            signal_id = self._save_signal(minute, action_hint="WATCH_SUPPORT")
            self.store.save_paper_trade_result({
                "signal_id": signal_id,
                "evaluated_at": "2026-06-22 11:{:02d}:00.000000".format(minute),
                "code": "005930",
                "entry_time": "2026-06-22 10:{:02d}:00.000000".format(minute),
                "entry_price": 100.0,
                "return_5m_pct": return_60m / 4,
                "return_10m_pct": return_60m / 3,
                "return_30m_pct": return_60m / 2,
                "return_60m_pct": return_60m,
                "max_gain_30m_pct": max(return_60m, 0),
                "max_loss_30m_pct": min(return_60m, 0),
                "max_gain_60m_pct": max(return_60m, 0),
                "max_loss_60m_pct": min(return_60m, 0),
                "target_1_hit": return_60m > 0,
                "target_2_hit": False,
                "stop_loss_hit": return_60m < 0,
                "outcome_label": "target_1_before_stop" if return_60m > 0 else "stop_before_target",
            })

        snapshot = build_feedback_snapshot(
            conn=self.store.conn,
            days=30,
            min_sample=1,
            code="005930",
        )

        self.assertEqual(3, snapshot["overview"]["signal_count"])
        self.assertEqual(2, snapshot["overview"]["cluster_count"])
        self.assertEqual(2, snapshot["overview"]["evaluated_cluster_60m_count"])
        self.assertEqual(50.0, snapshot["overview"]["cluster_win_rate_60m_pct"])

    def _save_signal(self, index, action_hint="WATCH_SUPPORT"):
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
                "code": "005930",
                "name": "Samsung Electronics",
                "timeframes": {},
            },
            detected_at="2026-06-22 10:{:02d}:00.000000".format(index),
        )


if __name__ == "__main__":
    unittest.main()
