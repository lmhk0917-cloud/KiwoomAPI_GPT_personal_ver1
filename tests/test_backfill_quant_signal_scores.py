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


if __name__ == "__main__":
    unittest.main()
