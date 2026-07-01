import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from data_store import TickStore
from paper_trade_simulator import (
    TickWindowCache,
    classify_decision_side,
    evaluate_signal,
    fetch_pending_signals,
)


class PaperTradeSimulatorTests(unittest.TestCase):
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

    def test_tick_window_cache_matches_direct_evaluation(self):
        signal_id = self.store.save_signal_log(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 70,
                "risk_level": "low",
                "current_price": 100.0,
                "stop_loss": 98.0,
                "target_1": 101.0,
                "target_2": 102.0,
                "reasons": ["test"],
            },
            summary={"code": "005930", "name": "Samsung", "timeframes": {}},
            detected_at="2026-06-24 09:00:00.000000",
        )

        start = datetime(2026, 6, 24, 9, 0)
        for minute in range(0, 66):
            price = 100.0 + (minute * 0.05)
            tick_time = start + timedelta(minutes=minute)
            self.store.save_tick({
                "code": "005930",
                "trade_time": tick_time.strftime("%H%M%S"),
                "price": price,
                "change_rate": 0.0,
                "acc_volume": minute,
                "tick_volume": 1,
                "open_price": 100.0,
                "high_price": price,
                "low_price": 100.0,
                "strength": 100.0,
                "received_at": tick_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            })

        signal = fetch_pending_signals(self.store, limit=1)[0]
        self.assertEqual(signal_id, signal["id"])

        direct = evaluate_signal(self.store, signal, allow_partial=True)
        cached = evaluate_signal(
            self.store,
            signal,
            allow_partial=True,
            tick_cache=TickWindowCache(self.store, [signal]),
        )

        self.assertEqual(direct["return_5m_pct"], cached["return_5m_pct"])
        self.assertEqual(direct["return_60m_pct"], cached["return_60m_pct"])
        self.assertEqual(direct["outcome_label"], cached["outcome_label"])

    def test_fetch_pending_includes_high_volatility_actions(self):
        expected = {
            "VOL_EXPANSION_MOMENTUM": "long_candidate",
            "HIGH_VOL_REVERSAL_WATCH": "long_candidate",
            "AVOID_VOLATILITY_TRAP": "avoid_or_caution",
        }

        for index, action_hint in enumerate(expected, start=1):
            self.store.save_signal_log(
                signal={
                    "action_hint": action_hint,
                    "confidence_score": 70,
                    "risk_level": "high",
                    "current_price": 100.0,
                    "stop_loss": 98.0,
                    "target_1": 101.0,
                    "target_2": 102.0,
                    "reasons": ["test"],
                },
                summary={"code": "005930", "name": "Samsung", "timeframes": {}},
                detected_at="2026-06-24 09:{:02d}:00.000000".format(index),
            )

        rows = fetch_pending_signals(self.store, limit=10)
        actions = {row["action_hint"] for row in rows}

        self.assertTrue(set(expected).issubset(actions))
        for action_hint, side in expected.items():
            self.assertEqual(side, classify_decision_side(action_hint))


if __name__ == "__main__":
    unittest.main()
