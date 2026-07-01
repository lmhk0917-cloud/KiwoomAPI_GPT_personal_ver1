import os
import tempfile
import unittest


from backfill_quant_signal_scores import backfill_quant_signal_scores
from data_store import TickStore


class BackfillQuantSignalScoresTests(unittest.TestCase):
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

    def test_backfill_inserts_missing_scores_once(self):
        self.store.save_signal_log(
            signal={
                "action_hint": "WATCH_SUPPORT",
                "confidence_score": 65,
                "risk_level": "medium",
                "current_price": 70000,
                "stop_loss": 69000,
                "target_1": 71000,
                "target_2": 72000,
                "reasons": ["test"],
            },
            summary={
                "code": "005930",
                "events": [],
                "timeframes": {
                    "1m": {
                        "latest": {"return_1bar_pct": 0.1},
                        "volume": {"volume_ratio_20": 1.2},
                    }
                },
            },
            detected_at="2026-06-22 10:00:00.000000",
        )

        first = backfill_quant_signal_scores(
            conn=self.store.conn,
            store=self.store,
            days=30,
            dry_run=False,
        )
        second = backfill_quant_signal_scores(
            conn=self.store.conn,
            store=self.store,
            days=30,
            dry_run=False,
        )

        count = self.store.conn.execute("SELECT COUNT(1) FROM quant_signal_scores").fetchone()[0]
        self.assertEqual(1, first["candidates"])
        self.assertEqual(1, first["inserted"])
        self.assertEqual(0, second["candidates"])
        self.assertEqual(1, count)

    def test_dry_run_does_not_insert(self):
        self.store.save_signal_log(
            signal={
                "action_hint": "OBSERVE_EVENT",
                "confidence_score": 45,
                "risk_level": "high",
                "current_price": 100,
                "reasons": [],
            },
            summary={"code": "000660", "events": [], "timeframes": {}},
            detected_at="2026-06-22 10:00:00.000000",
        )

        result = backfill_quant_signal_scores(
            conn=self.store.conn,
            store=self.store,
            days=30,
            code="000660",
            dry_run=True,
        )

        count = self.store.conn.execute("SELECT COUNT(1) FROM quant_signal_scores").fetchone()[0]
        self.assertEqual(1, result["candidates"])
        self.assertEqual(1, result["inserted"])
        self.assertEqual(0, count)

    def test_refresh_existing_updates_without_duplicate_rows(self):
        signal_id = self.store.save_signal_log(
            signal={
                "action_hint": "WATCH_PULLBACK",
                "confidence_score": 70,
                "risk_level": "medium",
                "current_price": 100,
                "stop_loss": 99,
                "target_1": 101,
                "target_2": 102,
                "reasons": ["test"],
            },
            summary={
                "code": "000660",
                "events": [],
                "historical_signal_stats": {
                    "learning_feedback": {
                        "quant_snapshot": {
                            "by_action": [{
                                "action_hint": "WATCH_PULLBACK",
                                "evaluated_60m_count": 25,
                                "avg_net_return_60m_pct": -0.4,
                                "win_rate_60m_pct": 40,
                                "directional_success_60m_pct": 40,
                                "stop_loss_hit_rate_pct": 55,
                            }],
                        }
                    }
                },
                "timeframes": {},
            },
            detected_at="2026-06-22 10:00:00.000000",
        )
        self.store.conn.execute("""
            INSERT INTO quant_signal_scores (
                signal_id, scored_at, code, action_hint, quant_signal_score,
                expected_value_score, market_risk_score, final_quant_score,
                decision_side, feature_json, formula_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal_id,
            "2026-06-22 10:00:00.000000",
            "000660",
            "WATCH_PULLBACK",
            1,
            1,
            1,
            1,
            "long_candidate",
            "{}",
            "old",
        ))
        self.store.conn.commit()

        result = backfill_quant_signal_scores(
            conn=self.store.conn,
            store=self.store,
            days=30,
            refresh_existing=True,
        )

        rows = self.store.conn.execute(
            "SELECT formula_version, feature_json FROM quant_signal_scores WHERE signal_id = ?",
            (signal_id,),
        ).fetchall()
        self.assertEqual(1, result["candidates"])
        self.assertEqual(0, result["inserted"])
        self.assertEqual(1, result["updated"])
        self.assertEqual(1, len(rows))
        self.assertEqual("quant_signal_score_v2", rows[0]["formula_version"])
        self.assertIn("long_score", rows[0]["feature_json"])


if __name__ == "__main__":
    unittest.main()
