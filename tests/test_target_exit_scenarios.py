import os
import tempfile
import unittest

from data_store import TickStore
from quant_signal_score import build_quant_signal_score
from target_exit_scenarios import build_target_exit_scenarios


class TargetExitScenarioTests(unittest.TestCase):
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

    def test_target_first_scenario(self):
        signal_id = self.store.save_signal_log(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 70,
                "risk_level": "low",
                "current_price": 100,
                "stop_loss": 99,
                "target_1": 101,
                "target_2": 102,
                "reasons": ["test"],
            },
            summary={"code": "005930", "events": [], "timeframes": {}},
            detected_at="2026-06-22 10:00:00.000000",
        )
        score = build_quant_signal_score(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 70,
                "risk_level": "low",
                "current_price": 100,
            },
            summary={"code": "005930", "events": [], "timeframes": {}},
            signal_id=signal_id,
            scored_at="2026-06-22 10:00:00.000000",
        )
        self.store.save_quant_signal_score(score)
        for received_at, price in [
            ("2026-06-22 10:00:00.000000", 100),
            ("2026-06-22 10:02:00.000000", 100.35),
            ("2026-06-22 10:10:00.000000", 100.2),
        ]:
            self.store.save_tick({
                "code": "005930",
                "trade_time": received_at[11:17].replace(":", ""),
                "price": price,
                "change_rate": 0,
                "acc_volume": 1,
                "tick_volume": 1,
                "open_price": 100,
                "high_price": price,
                "low_price": 100,
                "strength": 100,
                "received_at": received_at,
            })
        self.store.save_paper_trade_result({
            "signal_id": signal_id,
            "evaluated_at": "2026-06-22 10:11:00.000000",
            "code": "005930",
            "entry_time": "2026-06-22 10:00:00.000000",
            "entry_price": 100,
            "return_5m_pct": 0.35,
            "return_10m_pct": 0.2,
            "return_30m_pct": None,
            "return_60m_pct": None,
            "max_gain_30m_pct": None,
            "max_loss_30m_pct": None,
            "max_gain_60m_pct": None,
            "max_loss_60m_pct": None,
            "target_1_hit": False,
            "target_2_hit": False,
            "stop_loss_hit": False,
            "outcome_label": "test",
        })

        rows = build_target_exit_scenarios(
            self.store.conn,
            days=30,
            code="005930",
            scenarios=[{"horizon_min": 10, "target_pct": 0.3, "stop_pct": 0.4}],
        )

        self.assertEqual(1, rows[0]["evaluated_count"])
        self.assertEqual(1, rows[0]["target_first_count"])
        self.assertEqual(0, rows[0]["stop_first_count"])
        self.assertEqual(100.0, rows[0]["target_first_rate_pct"])
        self.assertEqual(0.3, rows[0]["avg_exit_return_pct"])


if __name__ == "__main__":
    unittest.main()
