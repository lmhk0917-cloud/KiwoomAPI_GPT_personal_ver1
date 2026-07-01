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
        self.assertEqual("quant_signal_score_v2", score["formula_version"])
        self.assertIn("sub_scores", score["feature_json"])
        self.assertIn("trend_score", score["feature_json"]["sub_scores"])

    def test_market_crash_caps_quant_score_and_marks_override(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "WATCH_REBOUND",
                "confidence_score": 80,
                "risk_level": "medium",
                "current_price": 100,
                "stop_loss": 99,
                "target_1": 102,
                "target_2": 103,
            },
            summary={
                "code": "005930",
                "events": [
                    {"type": "MARKET_CIRCUIT_BREAKER_ACTIVE"},
                    {"type": "MARKET_CRASH_RISK"},
                ],
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": 1.0},
                        "moving_average": {
                            "price_above_ma5": True,
                            "price_above_ma20": True,
                        },
                        "vwap": {"price_above_vwap": True},
                    }
                },
            },
            signal_id=11,
            scored_at="2026-06-23 10:00:00.000000",
        )

        self.assertEqual("AVOID_MARKET_RISK", score["action_hint"])
        self.assertEqual("caution_or_avoid", score["decision_side"])
        self.assertLessEqual(score["final_quant_score"], 25)
        self.assertIn("MARKET_CRASH_RISK", score["feature_json"]["hard_overrides"])
        self.assertEqual("Avoid Market Risk", score["feature_json"]["score_label"])
        self.assertLessEqual(score["feature_json"]["long_score"], 20)
        self.assertGreaterEqual(score["feature_json"]["caution_score"], 85)

    def test_missing_gpt_uses_neutral_agreement_score(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "OBSERVE_EVENT",
                "confidence_score": 45,
                "risk_level": "medium",
                "current_price": 100,
            },
            summary={"code": "005930", "events": [], "timeframes": {}},
            signal_id=12,
            scored_at="2026-06-23 10:00:00.000000",
        )

        self.assertEqual(50, score["feature_json"]["sub_scores"]["gpt_agreement_score"])
        self.assertIn(
            "GPT score is not available; neutral agreement score used.",
            score["feature_json"]["score_reasons"],
        )

    def test_long_score_is_penalized_by_negative_action_feedback(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "WATCH_PULLBACK",
                "confidence_score": 75,
                "risk_level": "medium",
                "current_price": 100,
                "stop_loss": 99,
                "target_1": 101,
                "target_2": 102,
            },
            summary={
                "code": "000660",
                "events": [],
                "historical_signal_stats": {
                    "learning_feedback": {
                        "quant_snapshot": {
                            "overview": {
                                "evaluated_60m_count": 120,
                                "avg_net_return_60m_pct": -0.35,
                                "win_rate_60m_pct": 45,
                                "stop_loss_hit_rate_pct": 50,
                            },
                            "by_action": [{
                                "action_hint": "WATCH_PULLBACK",
                                "evaluated_60m_count": 80,
                                "avg_net_return_60m_pct": -0.45,
                                "win_rate_60m_pct": 44,
                                "directional_success_60m_pct": 44,
                                "stop_loss_hit_rate_pct": 55,
                            }],
                            "guidance": {"label": "negative_expectancy"},
                        }
                    }
                },
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": 0.5},
                        "moving_average": {
                            "price_above_ma5": True,
                            "price_above_ma20": True,
                        },
                        "vwap": {"price_above_vwap": True},
                    }
                },
            },
            signal_id=13,
            scored_at="2026-06-23 10:00:00.000000",
        )

        self.assertEqual("long_candidate", score["decision_side"])
        self.assertLess(score["feature_json"]["long_score"], 50)
        self.assertEqual(score["feature_json"]["long_score"], score["final_quant_score"])
        self.assertEqual("medium", score["feature_json"]["score_confidence"])
        self.assertIn(
            "Action feedback has negative 60m net expectancy.",
            score["feature_json"]["score_reasons"],
        )

    def test_caution_score_tracks_warning_quality_separately(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "OBSERVE_EVENT",
                "confidence_score": 55,
                "risk_level": "high",
                "current_price": 100,
            },
            summary={
                "code": "042700",
                "events": [{"type": "MARKET_FOREIGN_SELL_PRESSURE"}],
                "historical_signal_stats": {
                    "learning_feedback": {
                        "quant_snapshot": {
                            "by_action": [{
                                "action_hint": "OBSERVE_EVENT",
                                "evaluated_60m_count": 40,
                                "avg_net_return_60m_pct": -1.1,
                                "win_rate_60m_pct": 10,
                                "directional_success_60m_pct": 90,
                                "stop_loss_hit_rate_pct": 45,
                            }],
                        }
                    }
                },
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": -0.7},
                        "moving_average": {
                            "price_above_ma5": False,
                            "price_above_ma20": False,
                        },
                        "vwap": {"price_above_vwap": False},
                    }
                },
            },
            signal_id=14,
            scored_at="2026-06-23 10:00:00.000000",
        )

        self.assertEqual("caution_or_avoid", score["decision_side"])
        self.assertGreater(score["feature_json"]["caution_score"], score["feature_json"]["long_score"])
        self.assertEqual(score["feature_json"]["caution_score"], score["final_quant_score"])

    def test_high_volatility_penalizes_long_and_records_features(self):
        base_signal = {
            "action_hint": "WATCH_PULLBACK",
            "confidence_score": 75,
            "risk_level": "medium",
            "current_price": 100,
            "stop_loss": 98,
            "target_1": 103,
            "target_2": 105,
        }
        base_summary = {
            "code": "000660",
            "events": [],
            "timeframes": {
                "1m": {
                    "latest": {"return_1bar_pct": 0.5},
                    "moving_average": {
                        "price_above_ma5": True,
                        "price_above_ma20": True,
                    },
                    "vwap": {"price_above_vwap": True},
                    "volatility": {"atr14_pct": 0.2, "bb_width_pct": 1.0},
                }
            },
        }
        volatile_summary = {
            "code": "000660",
            "events": [],
            "timeframes": {
                "1m": {
                    "latest": {"return_1bar_pct": 0.5},
                    "moving_average": {
                        "price_above_ma5": True,
                        "price_above_ma20": True,
                    },
                    "vwap": {"price_above_vwap": True},
                    "volatility": {"atr14_pct": 1.0, "bb_width_pct": 4.5},
                }
            },
        }

        base_score = build_quant_signal_score(base_signal, base_summary)
        volatile_score = build_quant_signal_score(base_signal, volatile_summary)

        self.assertEqual("normal", base_score["feature_json"]["volatility_level"])
        self.assertEqual("extreme", volatile_score["feature_json"]["volatility_level"])
        self.assertLess(
            volatile_score["feature_json"]["long_score"],
            base_score["feature_json"]["long_score"],
        )
        self.assertGreater(
            volatile_score["feature_json"]["caution_score"],
            base_score["feature_json"]["caution_score"],
        )
        self.assertEqual(10, volatile_score["feature_json"]["volatility_long_penalty"])

    def test_volatility_opportunity_classification_adds_long_context(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "VOL_EXPANSION_MOMENTUM",
                "confidence_score": 82,
                "risk_level": "high",
                "current_price": 100,
                "stop_loss": 97,
                "target_1": 105,
                "target_2": 108,
            },
            summary={
                "code": "000660",
                "events": [{"type": "VOLUME_SPIKE"}, {"type": "NEAR_BOX_HIGH"}],
                "market_context": {
                    "market_indices": {
                        "kospi200_change_pct": 1.2,
                        "kosdaq_change_pct": 1.0,
                    },
                },
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": 0.8},
                        "moving_average": {"price_above_ma5": True, "price_above_ma20": True},
                        "vwap": {"price_above_vwap": True},
                        "volume": {"volume_ratio_5": 2.2},
                        "volatility": {"atr14_pct": 1.0, "bb_width_pct": 4.5},
                    },
                    "3m": {
                        "latest": {"return_1bar_pct": 0.5},
                        "moving_average": {"price_above_ma5": True, "price_above_ma20": True},
                        "vwap": {"price_above_vwap": True},
                        "volume": {"volume_ratio_5": 2.0},
                        "volatility": {"atr14_pct": 0.8, "bb_width_pct": 3.0},
                    },
                },
            },
        )

        self.assertEqual("long_candidate", score["decision_side"])
        self.assertEqual("opportunity", score["feature_json"]["volatility_classification"])
        self.assertGreaterEqual(score["feature_json"]["volatility_opportunity_score"], 55)
        self.assertIn(
            "Volatility expansion has directional confirmation, so treat it as opportunity context.",
            score["feature_json"]["score_reasons"],
        )

    def test_volatility_trap_classification_strengthens_caution_context(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "AVOID_VOLATILITY_TRAP",
                "confidence_score": 82,
                "risk_level": "high",
                "current_price": 100,
                "stop_loss": 97,
                "target_1": 105,
                "target_2": 108,
            },
            summary={
                "code": "000660",
                "events": [{"type": "ORDERBOOK_ASK_IMBALANCE"}],
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": -0.8},
                        "moving_average": {"price_above_ma5": False, "price_above_ma20": False},
                        "vwap": {"price_above_vwap": False},
                        "volume": {"volume_ratio_5": 2.2},
                        "volatility": {"atr14_pct": 1.0, "bb_width_pct": 4.5},
                    },
                    "3m": {
                        "latest": {"return_1bar_pct": -0.5},
                        "moving_average": {"price_above_ma5": False, "price_above_ma20": False},
                        "vwap": {"price_above_vwap": False},
                        "volume": {"volume_ratio_5": 2.0},
                        "volatility": {"atr14_pct": 0.8, "bb_width_pct": 3.0},
                    },
                },
            },
        )

        self.assertEqual("caution_or_avoid", score["decision_side"])
        self.assertEqual("trap", score["feature_json"]["volatility_classification"])
        self.assertGreaterEqual(score["feature_json"]["volatility_trap_score"], 35)
        self.assertGreater(score["feature_json"]["caution_score"], score["feature_json"]["long_score"])

    def test_volatility_reversal_classification_supports_reversal_watch(self):
        score = build_quant_signal_score(
            signal={
                "action_hint": "HIGH_VOL_REVERSAL_WATCH",
                "confidence_score": 76,
                "risk_level": "high",
                "current_price": 100,
                "stop_loss": 97,
                "target_1": 103,
                "target_2": 106,
            },
            summary={
                "code": "000660",
                "events": [{"type": "ORDERBOOK_ASK_IMBALANCE"}, {"type": "VOLUME_SPIKE"}],
                "market_context": {
                    "market_indices": {
                        "kospi200_change_pct": 0.4,
                        "kosdaq_change_pct": 0.3,
                    },
                },
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": 0.45},
                        "moving_average": {"price_above_ma5": True, "price_above_ma20": True},
                        "vwap": {"price_above_vwap": True},
                        "volume": {"volume_ratio_5": 2.2},
                        "volatility": {"atr14_pct": 1.0, "bb_width_pct": 4.5},
                    },
                    "3m": {
                        "latest": {"return_1bar_pct": 0.25},
                        "moving_average": {"price_above_ma5": True, "price_above_ma20": False},
                        "vwap": {"price_above_vwap": True},
                        "volume": {"volume_ratio_5": 2.0},
                        "volatility": {"atr14_pct": 0.8, "bb_width_pct": 3.0},
                    },
                },
            },
        )

        self.assertEqual("long_candidate", score["decision_side"])
        self.assertEqual("reversal", score["feature_json"]["volatility_classification"])
        self.assertGreater(score["feature_json"]["long_score"], 0)
        self.assertIn(
            "Volatility stress has recovery confirmation, so track it as reversal-watch context.",
            score["feature_json"]["score_reasons"],
        )

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
        for offset, confidence in ((30, 70), (45, 80)):
            self.store.conn.execute("""
                INSERT INTO gpt_analysis_scores (
                    gpt_call_id, analyzed_at, code, parse_status, decision,
                    risk_score, gpt_context_score, breakout_score, trend_score,
                    confidence, risk_flags_json, invalid_condition, summary,
                    entry_plan, raw_json, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                1,
                "2026-06-22 10:00:{:02d}.000000".format(offset),
                "005930",
                "ok",
                "watch",
                40,
                55,
                50,
                60,
                confidence,
                "[]",
                None,
                "test",
                "observe",
                "{}",
                None,
            ))
        self.store.conn.commit()
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
        self.assertEqual(70.0, report["overview"]["avg_gpt_confidence"])
        self.assertEqual(4, len(report["horizon_summary"]))
        self.assertEqual(5, report["horizon_summary"][0]["horizon_min"])
        self.assertEqual(1, report["horizon_summary"][0]["evaluated_count"])
        self.assertGreaterEqual(len(report["target_exit_scenarios"]), 1)
        self.assertEqual(1, len(report["recent"]))
        self.assertEqual("WATCH_SUPPORT", report["recent"][0]["action_hint"])
        self.assertIn("long_score", report["recent"][0])
        self.assertIn("caution_score", report["recent"][0])
        self.assertIn("score_confidence", report["recent"][0])


if __name__ == "__main__":
    unittest.main()
