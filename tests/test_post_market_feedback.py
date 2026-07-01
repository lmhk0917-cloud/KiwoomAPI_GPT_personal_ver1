import os
import sys
import unittest
from datetime import datetime


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from main import RealtimeStrategyApp
from post_market_feedback_gpt import (
    build_authoritative_metrics,
    build_prompt,
    build_validation_notes,
    numeric_conventions,
    validate_result_interpretation,
    validate_result_units,
)


class _Timer:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class PostMarketFeedbackTests(unittest.TestCase):
    def test_post_market_gpt_prompt_preserves_percent_units(self):
        prompt = build_prompt({
            "paper_trade_report": {
                "overview": {
                    "avg_return_60m_pct": 0.185,
                    "avg_net_return_60m_pct": -0.125,
                },
            },
            "numeric_conventions": numeric_conventions(),
        })

        self.assertIn("0.185 means 0.185%, not 18.5%", prompt)
        self.assertIn("Never multiply *_pct values by 100", prompt)
        self.assertIn('"do_not_rescale_pct_values":true', prompt)
        self.assertIn("Output in Korean", prompt)
        self.assertIn("caution_missed_upside", prompt)
        self.assertIn("validation_notes.missed_upside_actions", prompt)

    def test_post_market_gpt_result_unit_warning_detects_rescaled_returns(self):
        payload = {
            "paper_trade_report": {
                "overview": {
                    "avg_return_60m_pct": 0.185,
                    "avg_net_return_60m_pct": -0.125,
                    "win_rate_60m_pct": 55.22,
                },
                "by_code": [
                    {"group_name": "000660", "avg_return_60m_pct": 0.924},
                ],
            }
        }

        warnings = validate_result_units(
            "Overview says 18.5% and SK hynix says 92.4%, win rate 55.22%.",
            payload,
        )

        self.assertTrue(any("avg_return_60m_pct=0.185" in item for item in warnings))
        self.assertTrue(any("avg_return_60m_pct=0.924" in item for item in warnings))
        self.assertFalse(any("win_rate_60m_pct" in item for item in warnings))

    def test_post_market_gpt_unit_warning_ignores_embedded_number_fragments(self):
        payload = {
            "paper_trade_report": {
                "by_code_action": [
                    {"group_name": "005930", "avg_return_10m_pct": 0.09},
                ],
            }
        }

        warnings = validate_result_units("Samsung was 0.509% over 60 minutes.", payload)

        self.assertEqual([], warnings)

    def test_post_market_gpt_authoritative_metrics_preserve_validation_labels(self):
        metrics = build_authoritative_metrics({
            "sample_summary": {
                "sample_label": "mixed_full_partial_or_pending",
                "full_60m_ratio_pct": 80.0,
            },
            "overview": {
                "signal_count": 10,
                "avg_return_60m_pct": 0.185,
                "avg_net_return_60m_pct": -0.125,
            },
            "by_action": [{
                "group_name": "AVOID_DOWNTREND",
                "avg_return_60m_pct": 0.924,
                "profit_label": "positive_net_expectancy",
                "directional_label": "direction_contra",
                "interpretation_hint": "caution_missed_upside",
            }],
        })

        self.assertEqual("paper_trade_report", metrics["source"])
        self.assertEqual(0.185, metrics["overview"]["avg_return_60m_pct"])
        self.assertEqual("mixed_full_partial_or_pending", metrics["sample_summary"]["sample_label"])
        self.assertEqual("caution_missed_upside", metrics["by_action"][0]["interpretation_hint"])
        self.assertEqual("AVOID_DOWNTREND", metrics["validation_notes"]["missed_upside_actions"][0]["group_name"])

    def test_validation_notes_separate_missed_upside_from_worked_caution(self):
        notes = build_validation_notes({
            "by_action": [
                {
                    "group_name": "AVOID_VOLATILITY_TRAP",
                    "interpretation_hint": "caution_missed_upside",
                    "directional_label": "direction_contra",
                    "avg_net_return_60m_pct": 0.381,
                },
                {
                    "group_name": "WATCH_RESISTANCE",
                    "interpretation_hint": "caution_worked",
                    "directional_label": "direction_validated",
                    "avg_net_return_60m_pct": -1.943,
                },
            ],
        })

        self.assertEqual("AVOID_VOLATILITY_TRAP", notes["missed_upside_actions"][0]["group_name"])
        self.assertEqual("WATCH_RESISTANCE", notes["worked_caution_actions"][0]["group_name"])

    def test_interpretation_warning_detects_missed_upside_contradiction(self):
        payload = {
            "authoritative_metrics": {
                "validation_notes": {
                    "missed_upside_actions": [
                        {"group_name": "AVOID_VOLATILITY_TRAP"},
                    ],
                },
            },
        }
        result = "\n".join([
            "- 잘 맞은 신호: AVOID_VOLATILITY_TRAP",
            "- 과도하게 회피한 신호: AVOID_VOLATILITY_TRAP",
        ])

        warnings = validate_result_interpretation(result, payload)

        self.assertEqual([
            "missed-upside action listed as well-matched: AVOID_VOLATILITY_TRAP",
        ], warnings)

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
