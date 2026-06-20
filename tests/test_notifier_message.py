import unittest

from notifier import Notifier


class NotifierMessageTests(unittest.TestCase):
    def test_signal_levels_are_labeled_as_observation_anchors(self):
        notifier = Notifier(settings={
            "ENABLE_NOTIFICATIONS": True,
            "NOTIFICATION_CHANNELS": ["console"],
            "TELEGRAM_COMPACT_EVENT_MESSAGE": True,
        })
        summary = {
            "code": "005930",
            "name": "Samsung Electronics",
            "timeframes": {
                "1m": {
                    "latest": {"close": 356000},
                    "momentum": {"rsi14": 48.5},
                    "vwap": {"vwap_distance_pct": 0.42},
                }
            },
        }
        events = [{"type": "NEAR_VWAP_SUPPORT", "value": 0.42}]
        signal = {
            "action_hint": "OBSERVE_EVENT",
            "confidence_score": 43,
            "risk_level": "high",
            "stop_loss": 350000,
            "target_1": 358000,
            "target_2": 361500,
        }

        message = notifier._build_event_message(summary, events, signal)

        self.assertIn("관찰 기준선", message)
        self.assertIn("하단=350000", message)
        self.assertIn("1차상단=358000", message)
        self.assertIn("2차상단=361500", message)
        self.assertNotIn("기준: 손절", message)


if __name__ == "__main__":
    unittest.main()
