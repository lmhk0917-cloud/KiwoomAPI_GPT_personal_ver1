import os
import unittest

import intraday_collector_supervisor as supervisor


class DummyArgs(object):
    def __init__(self, allow_tick_only_runtime=False, attempt_seconds=0):
        self.allow_tick_only_runtime = allow_tick_only_runtime
        self.attempt_seconds = attempt_seconds


class IntradaySupervisorGuardTests(unittest.TestCase):
    def setUp(self):
        self.previous = os.environ.pop("KIWOOM_ALLOW_TICK_ONLY", None)

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("KIWOOM_ALLOW_TICK_ONLY", None)
        else:
            os.environ["KIWOOM_ALLOW_TICK_ONLY"] = self.previous

    def test_blocks_direct_tick_only_runtime_by_default(self):
        self.assertFalse(supervisor.is_tick_only_runtime_allowed(DummyArgs()))

    def test_allows_explicit_tick_only_runtime_argument(self):
        self.assertTrue(
            supervisor.is_tick_only_runtime_allowed(
                DummyArgs(allow_tick_only_runtime=True)
            )
        )

    def test_allows_explicit_tick_only_runtime_environment(self):
        os.environ["KIWOOM_ALLOW_TICK_ONLY"] = "1"
        self.assertTrue(supervisor.is_tick_only_runtime_allowed(DummyArgs()))

    def test_tick_only_runtime_forces_single_long_collector(self):
        args = DummyArgs(allow_tick_only_runtime=True, attempt_seconds=300)
        self.assertEqual(supervisor.normalize_attempt_seconds(args), 0)
        self.assertEqual(args.attempt_seconds, 0)

    def test_non_tick_only_attempt_seconds_remains_unchanged(self):
        args = DummyArgs(allow_tick_only_runtime=False, attempt_seconds=300)
        self.assertEqual(supervisor.normalize_attempt_seconds(args), 300)
        self.assertEqual(args.attempt_seconds, 300)


if __name__ == "__main__":
    unittest.main()
