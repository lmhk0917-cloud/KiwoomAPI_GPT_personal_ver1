"""Compatibility wrapper for diagnostics.mock_test."""

import runpy


if __name__ == "__main__":
    runpy.run_module("diagnostics.mock_test", run_name="__main__")
