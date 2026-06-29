"""Best-effort hooks for exporting Kiwoom summaries to the shared context hub."""

import os
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
EXPORTER_PATH = os.path.join(PROJECT_ROOT, "tools", "export_to_shared_context.py")


def export_shared_context(reason="manual", timeout_sec=120):
    if os.environ.get("KIWOOM_SHARED_CONTEXT_EXPORT_DISABLED", "").lower() in ("1", "true", "yes"):
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_SKIPPED=disabled")
        return False
    if not os.path.exists(EXPORTER_PATH):
        print("KIWOOM_SHARED_CONTEXT_AUTO_EXPORT_STATUS=missing_exporter")
        return False

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
