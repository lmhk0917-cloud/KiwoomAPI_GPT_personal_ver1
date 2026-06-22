import os
import sys
import unittest
from datetime import datetime


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from main import RealtimeStrategyApp


class _Timer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class PostMarketFeedbackTests(unittest.TestCase):
    def test_post_market_feedback_runs_once_and_stops_timer(self):
        app = RealtimeStrategyApp.__new__(RealtimeStrategyApp)
        app.post_market_feedback_done_date = None
        app.timer = _Timer()
        app.watch_codes = {"005930": "Samsung", "000660": "SKHynix"}
        app._get_setting = lambda key, default=None: default

        calls = []

        def evaluate(**kwargs):
            calls.append(("evaluate", kwargs))
            return 7

        def snapshot():
            calls.append(("snapshot", {}))
            return 3

        app._evaluate_pending_paper_trades = evaluate
        app._save_quant_feedback_snapshot = snapshot

        first = app._handle_post_market_feedback(datetime(2026, 6, 22, 15, 31))
        second = app._handle_post_market_feedback(datetime(2026, 6, 22, 15, 32))

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual("2026-06-22", app.post_market_feedback_done_date)
        self.assertTrue(app.timer.stopped)
        self.assertEqual([
            ("evaluate", {
                "allow_partial": True,
                "since": "2026-06-22 00:00:00",
                "refresh_feedback": False,
            }),
            ("snapshot", {}),
        ], calls)

    def test_before_post_market_time_does_not_block_analysis(self):
        app = RealtimeStrategyApp.__new__(RealtimeStrategyApp)
        app._get_setting = lambda key, default=None: default
        self.assertFalse(app._handle_post_market_feedback(datetime(2026, 6, 22, 15, 30)))


if __name__ == "__main__":
    unittest.main()
