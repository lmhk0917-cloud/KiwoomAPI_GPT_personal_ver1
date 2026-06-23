import os
import tempfile
import unittest

from data_store import TickStore


class StorageSchemaIndexesTests(unittest.TestCase):
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

    def test_performance_indexes_are_created(self):
        rows = self.store.conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
        """).fetchall()
        index_names = {row["name"] for row in rows}

        expected = {
            "idx_event_logs_type_detected_at",
            "idx_signal_logs_action_detected_at",
            "idx_quant_signal_scores_decision_time",
            "idx_paper_trade_results_code_evaluated_at",
        }
        self.assertTrue(expected.issubset(index_names))


if __name__ == "__main__":
    unittest.main()
