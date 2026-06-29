import os
import tempfile
import unittest

import shared_context_auto_export as auto_export


class FakeProcess(object):
    def __init__(self, pid=4321, running=True):
        self.pid = pid
        self.running = running

    def poll(self):
        return None if self.running else 0


class SharedContextAutoExportTests(unittest.TestCase):
    def test_background_export_uses_popen_and_skips_duplicate_running_process(self):
        calls = []
        original_popen = auto_export.subprocess.Popen
        original_process = auto_export._BACKGROUND_PROCESS
        original_log_dir = auto_export.LOG_DIR
        try:
            auto_export._BACKGROUND_PROCESS = None
            auto_export.LOG_DIR = tempfile.mkdtemp()

            def fake_popen(*args, **kwargs):
                calls.append((args, kwargs))
                return FakeProcess(pid=9876, running=True)

            auto_export.subprocess.Popen = fake_popen
            self.assertTrue(auto_export.start_shared_context_export(reason="unit_test"))
            self.assertEqual(1, len(calls))
            self.assertEqual(9876, auto_export._BACKGROUND_PROCESS.pid)

            self.assertTrue(auto_export.start_shared_context_export(reason="unit_test_duplicate"))
            self.assertEqual(1, len(calls))
        finally:
            auto_export.subprocess.Popen = original_popen
            auto_export._BACKGROUND_PROCESS = original_process
            auto_export.LOG_DIR = original_log_dir

    def test_blocking_flag_false_routes_to_background_start(self):
        original_start = auto_export.start_shared_context_export
        try:
            calls = []

            def fake_start(reason):
                calls.append(reason)
                return True

            auto_export.start_shared_context_export = fake_start
            self.assertTrue(auto_export.export_shared_context(reason="loop", blocking=False))
            self.assertEqual(["loop"], calls)
        finally:
            auto_export.start_shared_context_export = original_start


if __name__ == "__main__":
    unittest.main()
