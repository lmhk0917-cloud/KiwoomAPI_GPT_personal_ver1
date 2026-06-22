import os
import sys
import tempfile
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from data_store import TickStore
from gpt_result_parser import extract_json_object, parse_gpt_analysis_scores


class GPTResultParserTests(unittest.TestCase):
    def test_extract_json_object_from_markdown_fence(self):
        parsed, error = extract_json_object('```json\n{"symbols":[{"code":"005930"}]}\n```')
        self.assertIsNone(error)
        self.assertEqual("005930", parsed["symbols"][0]["code"])

    def test_parse_scores_for_each_summary(self):
        result = """
        {
          "market": {"state": "neutral"},
          "symbols": [
            {
              "code": "005930",
              "decision": "observe",
              "risk_score": 70,
              "gpt_context_score": 40,
              "breakout_score": 20,
              "trend_score": 30,
              "confidence": 45,
              "risk_flags": ["foreign selling"],
              "invalid_condition": "VWAP recovery",
              "summary": "weak setup",
              "entry_plan": "wait"
            }
          ]
        }
        """
        rows = parse_gpt_analysis_scores(
            result_text=result,
            summaries=[{"code": "005930"}, {"code": "000660"}],
            gpt_call_id=123,
            analyzed_at="2026-06-22 10:00:00.000000",
        )
        self.assertEqual(2, len(rows))
        self.assertEqual("parsed", rows[0]["parse_status"])
        self.assertEqual("missing_symbol", rows[1]["parse_status"])
        self.assertEqual(70.0, rows[0]["risk_score"])

    def test_store_saves_gpt_analysis_scores(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        store = TickStore(db_path=tmp.name)
        try:
            saved = store.save_gpt_analysis_scores([
                {
                    "gpt_call_id": 1,
                    "analyzed_at": "2026-06-22 10:00:00.000000",
                    "code": "005930",
                    "parse_status": "parsed",
                    "decision": "observe",
                    "risk_score": 65,
                    "gpt_context_score": 50,
                    "breakout_score": 25,
                    "trend_score": 30,
                    "confidence": 40,
                    "risk_flags": ["risk"],
                    "invalid_condition": "invalid",
                    "summary": "summary",
                    "entry_plan": "wait",
                    "raw_json": {"code": "005930"},
                    "error_message": None,
                }
            ])
            row = store.conn.execute("""
                SELECT code, parse_status, decision, risk_score
                FROM gpt_analysis_scores
            """).fetchone()
            self.assertEqual(1, saved)
            self.assertEqual("005930", row["code"])
            self.assertEqual("parsed", row["parse_status"])
            self.assertEqual(65, row["risk_score"])
        finally:
            store.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
