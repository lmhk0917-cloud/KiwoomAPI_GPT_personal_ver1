"""Best-effort hooks for exporting Kiwoom summaries to the shared context hub."""

import os
import subprocess
import sys
from datetime import datetime


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
EXPORTER_PATH = os.path.join(PROJECT_ROOT, "tools", "export_to_shared_context.py")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
_BACKGROUND_PROCESS = None


def export_shared_context(reason="manual", timeout_sec=120, blocking=True):
    if os.environ.get("KIWOOM_SHARED_CONTEXT_EXPORT_DISABLED", "").lower() in ("1", "true", "yes"):
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_SKIPPED=disabled")
        return False
    if not os.path.exists(EXPORTER_PATH):
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_STATUS=missing_exporter")
        return False

    if not blocking:
        return start_shared_context_export(reason=reason)

    try:
        completed = subprocess.run(
            [sys.executable, EXPORTER_PATH],
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=timeout_sec,
        )
    except Exception as exc:
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_STATUS=failed")
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_REASON={}".format(reason))
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_ERROR={}".format(exc))
        return False

    for line in (completed.stdout or "").splitlines():
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_CHILD={}".format(line))
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_STATUS={}".format("ok" if completed.returncode == 0 else "failed"))
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_REASON={}".format(reason))
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_EXIT_CODE={}".format(completed.returncode))
    return completed.returncode == 0


def start_shared_context_export(reason="manual"):
    """Start a background export without blocking the Kiwoom Qt event loop."""
    global _BACKGROUND_PROCESS

    if _BACKGROUND_PROCESS is not None and _BACKGROUND_PROCESS.poll() is None:
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_SKIPPED=already_running")
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_REASON={}".format(reason))
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_PID={}".format(_BACKGROUND_PROCESS.pid))
        return True

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, "shared_context_export_{}.log".format(stamp))
    log_handle = None
    try:
        log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _BACKGROUND_PROCESS = subprocess.Popen(
            [sys.executable, EXPORTER_PATH],
            cwd=PROJECT_ROOT,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            close_fds=False,
            creationflags=creationflags,
        )
    except Exception as exc:
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_STATUS=failed_to_start")
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_REASON={}".format(reason))
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_ERROR={}".format(exc))
        return False
    finally:
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass

    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_STATUS=started")
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_MODE=background")
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_REASON={}".format(reason))
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_PID={}".format(_BACKGROUND_PROCESS.pid))
    print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_LOG={}".format(log_path))
    return True
