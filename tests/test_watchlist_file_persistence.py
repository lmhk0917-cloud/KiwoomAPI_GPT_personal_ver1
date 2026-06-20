import json
import os
import tempfile
import unittest

from ui_dashboard import save_watchlist_file


class WatchlistFilePersistenceTests(unittest.TestCase):
    def test_save_watchlist_file_writes_visible_json_snapshot(self):
        handle = tempfile.NamedTemporaryFile(delete=False)
        path = handle.name
        handle.close()
        os.unlink(path)

        try:
            saved_path = save_watchlist_file({
                "005930": "Samsung Electronics",
                "000660": "SK Hynix",
            }, path=path)

            self.assertEqual(path, saved_path)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as fp:
                payload = json.load(fp)

            self.assertEqual("ui_dashboard", payload["source"])
            self.assertEqual({
                "000660": "SK Hynix",
                "005930": "Samsung Electronics",
            }, payload["watch_codes"])
            self.assertIn("updated_at", payload)
            self.assertFalse(os.path.exists(path + ".tmp"))
        finally:
            if os.path.exists(path):
                os.unlink(path)
            if os.path.exists(path + ".tmp"):
                os.unlink(path + ".tmp")


if __name__ == "__main__":
    unittest.main()
