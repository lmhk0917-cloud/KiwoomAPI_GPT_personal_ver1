import argparse
import os
import sys
import unittest
from datetime import datetime


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from main_timed_test import tick_watchdog_deadline_timestamp, valid_hhmm


class MainTimedTestArgumentTests(unittest.TestCase):
    def test_valid_hhmm_normalizes_time(self):
        self.assertEqual("09:02", valid_hhmm("9:2"))

    def test_valid_hhmm_rejects_invalid_time(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            valid_hhmm("24:00")
        with self.assertRaises(argparse.ArgumentTypeError):
            valid_hhmm("0902")

    def test_tick_watchdog_deadline_uses_process_start_on_intraday_restart(self):
        process_started_at = datetime.now().replace(hour=13, minute=8, second=30, microsecond=0)

        deadline = tick_watchdog_deadline_timestamp(
            "09:02",
            180,
            process_started_at=process_started_at,
        )

        self.assertEqual(process_started_at.timestamp() + 180, deadline)

    def test_tick_watchdog_deadline_keeps_market_open_deadline_before_open(self):
        process_started_at = datetime.now().replace(hour=8, minute=50, second=0, microsecond=0)
        expected = datetime.now().replace(hour=9, minute=2, second=0, microsecond=0).timestamp() + 180

        deadline = tick_watchdog_deadline_timestamp(
            "09:02",
            180,
            process_started_at=process_started_at,
        )

        self.assertEqual(expected, deadline)


if __name__ == "__main__":
    unittest.main()
