"""Shared filesystem paths and runtime logging helpers.

Keep generated files under the project directory so packaging and backups are
predictable. Existing root-level ``ticks.db`` is copied into ``data/`` once for
backward compatibility.
"""

import os
import shutil
import sys
import faulthandler
from datetime import datetime


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
EXPORTS_DIR = os.path.join(PROJECT_DIR, "exports")
SCREENSHOT_DIR = os.path.join(EXPORTS_DIR, "screenshots")

DEFAULT_DB_PATH = os.path.join(DATA_DIR, "ticks.db")
LEGACY_DB_PATH = os.path.join(PROJECT_DIR, "ticks.db")

_LOG_FILE_HANDLE = None


def ensure_app_dirs():
    """Create standard runtime folders and migrate the legacy DB if needed."""
    for path in (DATA_DIR, LOG_DIR, EXPORTS_DIR, SCREENSHOT_DIR):
        os.makedirs(path, exist_ok=True)

    if os.path.exists(LEGACY_DB_PATH) and not os.path.exists(DEFAULT_DB_PATH):
        shutil.copy2(LEGACY_DB_PATH, DEFAULT_DB_PATH)


def setup_runtime_logging(prefix):
    """Mirror stdout/stderr to a daily log file while keeping console output."""
    global _LOG_FILE_HANDLE

    ensure_app_dirs()
    if _LOG_FILE_HANDLE is not None:
        return _LOG_FILE_HANDLE.name

    date_text = datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(LOG_DIR, "{}_{}.log".format(prefix, date_text))
    _LOG_FILE_HANDLE = open(log_path, "a", encoding="utf-8", buffering=1)

    sys.stdout = TeeStream(sys.__stdout__, _LOG_FILE_HANDLE)
    sys.stderr = TeeStream(sys.__stderr__, _LOG_FILE_HANDLE)

    try:
        faulthandler.enable(file=_LOG_FILE_HANDLE, all_threads=True)
    except Exception as exc:
        print("FAULTHANDLER_ENABLE_ERROR={}".format(exc))

    print("")
    print("========== runtime log started ==========")
    print("log_path={}".format(log_path))
    print("project_dir={}".format(PROJECT_DIR))
    print("db_path={}".format(DEFAULT_DB_PATH))
    print("started_at={}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("=========================================")

    return log_path


class TeeStream:
    """Write console output to both the original stream and a log file."""

    def __init__(self, stream, log_file):
        self.stream = stream
        self.log_file = log_file

    def write(self, message):
        self.stream.write(message)
        self.log_file.write(message)

    def flush(self):
        for target in (self.stream, self.log_file):
            try:
                target.flush()
            except OSError:
                # Console handles can become invalid after a parent PowerShell
                # process times out, but logging must not stop market analysis.
                pass

    def isatty(self):
        return self.stream.isatty()
