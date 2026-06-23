"""Unit tests for deterministic validation signal behavior.

These tests intentionally avoid Kiwoom, Telegram, and OpenAI side effects.
They protect the signal rules that are most likely to affect daily testing.
"""

import os
import sys
import unittest
from unittest.mock import patch


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from event_detector import detect_gpt_events
from macro_context_fetcher import fetch_news_context
from signal_generator import generate_validation_signal


def _event(event_type):
    return {"type": event_type}


def _timeframe(
    close=100.0,
    return_1bar_pct=0.2,
    above_ma5=True,
    above_ma20=True,
    above_vwap=True,
    consecutive_down_bars=0,
):
    return {
        "latest": {
            "close": close,
            "return_1bar_pct": return_1bar_pct,
        },
        "box_range": {
            "box_high": 105.0,
            "box_low": 97.0,
        },
        "moving_average": {
            "price_above_ma5": above_ma5,
            "price_above_ma20": above_ma20,
        },
        "vwap": {
            "price_above_vwap": above_vwap,
        },
        "trend": {
            "consecutive_down_bars": consecutive_down_bars,
        },
    }


def _summary(events, timeframes=None, market_context=None, detected_at="2026-06-05 09:30:00"):
    return {
        "code": "005930",
        "name": "Samsung Electronics",
        "detected_at": detected_at,
        "market_snapshot": {
            "change_rate": 2.5,
        },
        "events": [_event(event) for event in events],
        "timeframes": timeframes or {
            "1m": _timeframe(),
            "3m": _timeframe(),
            "5m": _timeframe(),
        },
        "market_context": market_context or {},
    }


def _event_summary(
    return_1bar_pct=0.1,
    volume_ratio_5=1.0,
    volume_ratio_20=1.0,
    market_context=None,
):
    return {
        "code": "005930",
        "name": "Samsung Electronics",
        "timeframes": {
            "1m": {
                "latest": {
                    "close": 100.0,
                    "return_1bar_pct": return_1bar_pct,
                },
                "volume": {
                    "volume_ratio_5": volume_ratio_5,
                    "volume_ratio_20": volume_ratio_20,
                },
                "momentum": {
                    "rsi14": 50.0,
                },
                "box_range": {
                    "current_position_in_box": 0.5,
                },
                "vwap": {
                    "vwap_distance_pct": 2.0,
                    "price_above_vwap": True,
                },
                "trend": {},
            }
        },
        "market_context": market_context or {},
    }


NEWS_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
<item>
  <title>SK하이닉스 실적 개선 기대에 강세</title>
  <link>https://example.com/a</link>
  <pubDate>Fri, 12 Jun 2026 05:00:00 GMT</pubDate>
  <source>Example News</source>
</item>
<item>
  <title>반도체 투자 확대 소식</title>
  <link>https://example.com/b</link>
</item>
</channel></rss>
"""


class SignalLogicTest(unittest.TestCase):
    def test_vwap_support_with_bid_imbalance_becomes_pullback_watch(self):
        signal = generate_validation_signal(
            _summary(["NEAR_VWAP_SUPPORT", "ORDERBOOK_BID_IMBALANCE"])
        )

        self.assertEqual("WATCH_PULLBACK", signal["action_hint"])
        self.assertEqual("medium", signal["risk_level"])
        self.assertGreaterEqual(signal["confidence_score"], 60)
        self.assertLessEqual(signal["stop_loss"], 99.0)

    def test_bearish_multi_timeframe_blocks_rebound_watch(self):
        bearish = {
            "1m": _timeframe(return_1bar_pct=-0.4, above_ma5=False, above_ma20=False, above_vwap=False, consecutive_down_bars=3),
            "3m": _timeframe(return_1bar_pct=-0.3, above_ma5=False, above_ma20=False, above_vwap=False, consecutive_down_bars=2),
            "5m": _timeframe(return_1bar_pct=-0.1, above_ma5=True, above_ma20=False, above_vwap=True, consecutive_down_bars=1),
        }

        signal = generate_validation_signal(
            _summary(["RSI_OVERSOLD", "NEAR_BOX_LOW"], timeframes=bearish)
        )

        self.assertEqual("AVOID_DOWNTREND", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])
        self.assertLessEqual(signal["confidence_score"], 55)

    def test_sell_side_sidecar_blocks_watch_signal(self):
        signal = generate_validation_signal(
            _summary(
                ["NEAR_BOX_LOW", "ORDERBOOK_BID_IMBALANCE", "MARKET_SIDECAR_ACTIVE"],
                market_context={
                    "market_status": {
                        "sidecar_direction": "sell",
                    }
                },
            )
        )

        self.assertEqual("AVOID_MARKET_RISK", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_market_crash_risk_blocks_watch_signal(self):
        signal = generate_validation_signal(
            _summary(["NEAR_BOX_LOW", "ORDERBOOK_BID_IMBALANCE", "MARKET_CRASH_RISK"])
        )

        self.assertEqual("AVOID_MARKET_RISK", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_unconfirmed_vwap_support_is_observation_only(self):
        signal = generate_validation_signal(_summary(["NEAR_VWAP_SUPPORT"]))

        self.assertEqual("OBSERVE_EVENT", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])
        self.assertLess(signal["confidence_score"], 55)

    def test_risk_on_market_relabels_mild_downtrend_as_pullback(self):
        bearish = {
            "1m": _timeframe(return_1bar_pct=-0.2, above_ma5=False, above_ma20=False, above_vwap=False, consecutive_down_bars=3),
            "3m": _timeframe(return_1bar_pct=-0.1, above_ma5=False, above_ma20=False, above_vwap=True, consecutive_down_bars=1),
            "5m": _timeframe(return_1bar_pct=0.2, above_ma5=True, above_ma20=True, above_vwap=True, consecutive_down_bars=0),
        }

        signal = generate_validation_signal(
            _summary(
                ["CONSECUTIVE_DOWN_BARS"],
                timeframes=bearish,
                market_context={
                    "market_indices": {
                        "kospi200_change_pct": 2.0,
                    },
                },
            )
        )

        self.assertEqual("WATCH_PULLBACK", signal["action_hint"])
        self.assertEqual("medium", signal["risk_level"])

    def test_risk_on_relabel_does_not_override_ask_supply(self):
        bearish = {
            "1m": _timeframe(return_1bar_pct=-0.2, above_ma5=False, above_ma20=False, above_vwap=False, consecutive_down_bars=3),
            "3m": _timeframe(return_1bar_pct=-0.1, above_ma5=False, above_ma20=False, above_vwap=True, consecutive_down_bars=1),
            "5m": _timeframe(return_1bar_pct=0.2, above_ma5=True, above_ma20=True, above_vwap=True, consecutive_down_bars=0),
        }

        signal = generate_validation_signal(
            _summary(
                ["CONSECUTIVE_DOWN_BARS", "ORDERBOOK_ASK_IMBALANCE"],
                timeframes=bearish,
                market_context={
                    "market_indices": {
                        "kospi200_change_pct": 2.0,
                    },
                },
            )
        )

        self.assertEqual("AVOID_SUPPLY", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_pullback_requires_3m_or_5m_vwap_confirmation(self):
        weak_pullback = {
            "1m": _timeframe(above_vwap=True),
            "3m": _timeframe(above_vwap=False),
            "5m": _timeframe(above_vwap=False),
        }

        signal = generate_validation_signal(
            _summary(
                ["NEAR_VWAP_SUPPORT", "ORDERBOOK_BID_IMBALANCE"],
                timeframes=weak_pullback,
            )
        )

        self.assertEqual("OBSERVE_EVENT", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_pullback_is_blocked_by_market_foreign_sell_pressure(self):
        signal = generate_validation_signal(
            _summary([
                "NEAR_VWAP_SUPPORT",
                "ORDERBOOK_BID_IMBALANCE",
                "MARKET_FOREIGN_SELL_PRESSURE",
            ])
        )

        self.assertEqual("OBSERVE_EVENT", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_pullback_is_downgraded_before_high_impact_macro_event(self):
        signal = generate_validation_signal(
            _summary(
                ["NEAR_VWAP_SUPPORT", "ORDERBOOK_BID_IMBALANCE"],
                market_context={
                    "macro_context": {
                        "next_macro_events": [
                            {
                                "time": "2026-06-10 21:30 KST",
                                "title": "US CPI and Core CPI release",
                            }
                        ]
                    }
                },
            )
        )

        self.assertEqual("OBSERVE_EVENT", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_unconfirmed_vwap_resistance_stays_observation(self):
        signal = generate_validation_signal(
            _summary(
                ["NEAR_VWAP_RESISTANCE"],
                market_context={
                    "market_indices": {
                        "kospi200_change_pct": 2.0,
                    },
                },
            )
        )

        self.assertEqual("OBSERVE_EVENT", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])
        self.assertLess(signal["confidence_score"], 55)

    def test_risk_on_vwap_resistance_does_not_override_market_selling(self):
        signal = generate_validation_signal(
            _summary(
                ["NEAR_VWAP_RESISTANCE", "MARKET_FOREIGN_SELL_PRESSURE"],
                market_context={
                    "market_indices": {
                        "kospi200_change_pct": 2.0,
                    },
                },
            )
        )

        self.assertEqual("WATCH_RESISTANCE", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])

    def test_ask_imbalance_alone_stays_observation(self):
        signal = generate_validation_signal(_summary(["ORDERBOOK_ASK_IMBALANCE"]))

        self.assertEqual("OBSERVE_EVENT", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])
        self.assertLess(signal["confidence_score"], 55)

    def test_ask_imbalance_with_downtrend_becomes_supply_avoid(self):
        signal = generate_validation_signal(
            _summary(["ORDERBOOK_ASK_IMBALANCE", "CONSECUTIVE_DOWN_BARS"])
        )

        self.assertEqual("AVOID_SUPPLY", signal["action_hint"])
        self.assertEqual("high", signal["risk_level"])


class EventDetectorTest(unittest.TestCase):
    def test_force_gpt_intraday_event_requires_confirmations(self):
        events = detect_gpt_events(_event_summary(return_1bar_pct=1.0, volume_ratio_5=2.4))

        self.assertIn("FORCE_GPT_INTRADAY_EVENT", [event["type"] for event in events])

    def test_force_gpt_intraday_event_does_not_trigger_on_price_only(self):
        events = detect_gpt_events(_event_summary(return_1bar_pct=1.0, volume_ratio_5=1.0))

        self.assertNotIn("FORCE_GPT_INTRADAY_EVENT", [event["type"] for event in events])

    def test_market_index_drop_infers_circuit_breaker_level_risk(self):
        events = detect_gpt_events(
            _event_summary(
                market_context={
                    "market_indices": {
                        "kospi_change_pct": -8.18,
                        "kosdaq_change_pct": -6.68,
                        "kospi200_change_pct": -8.54,
                    }
                }
            )
        )
        event_types = [event["type"] for event in events]

        self.assertIn("MARKET_CIRCUIT_BREAKER_ACTIVE", event_types)
        self.assertIn("MARKET_CRASH_RISK", event_types)


class NewsContextFetcherTest(unittest.TestCase):
    def test_positive_titles_create_low_weight_risk_on_bias(self):
        with patch("macro_context_fetcher._fetch_html", return_value=NEWS_RSS):
            context = fetch_news_context(
                code="000660",
                name="SK하이닉스",
                events=[{"type": "FORCE_GPT_INTRADAY_EVENT"}],
                settings={"NEWS_CONTEXT_MAX_ITEMS": 2},
            )

        self.assertEqual("crawler_unverified", context["reliability"])
        self.assertEqual("positive", context["sentiment"])
        self.assertEqual("risk_on", context["direction_bias"])
        self.assertEqual(3, context["confidence_adjustment"])
        self.assertEqual(2, context["source_count"])

    def test_network_failure_returns_failed_context_without_raising(self):
        with patch("macro_context_fetcher._fetch_html", side_effect=OSError("blocked")):
            context = fetch_news_context(
                code="005930",
                name="삼성전자",
                events=[{"type": "FORCE_GPT_INTRADAY_EVENT"}],
            )

        self.assertEqual("crawler_failed", context["reliability"])
        self.assertIn("notes", context)


if __name__ == "__main__":
    unittest.main()
