"""Compatibility wrapper for diagnostics.realtime_test."""

import runpy


if __name__ == "__main__":
    runpy.run_module("diagnostics.realtime_test", run_name="__main__")
