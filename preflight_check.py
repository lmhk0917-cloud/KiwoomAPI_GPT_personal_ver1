"""Preflight checks for Kiwoom single-session test runs.

Kiwoom OpenAPI+ is sensitive to duplicate login/COM sessions. This module
checks for leftover Python/Kiwoom processes before starting a market-hours
test. It blocks by default and only terminates processes when explicitly asked
with ``--kill-residual``.
"""

import argparse
import csv
import io
import json
import os
import signal
import subprocess
import sys
import time


PYTHON_PROCESS_NAMES = set(["python.exe", "pythonw.exe"])
KIWOOM_PROCESS_NAMES = set([
    "khmini.exe",
    "khministarter.exe",
    "nkmini.exe",
    "nkministarter.exe",
    "opstarter.exe",
    "kstarter.exe",
    "khopenapi.exe",
    "koastudio.exe",
    "koastudiosa.exe",
])

PROJECT_PYTHON_MARKERS = [
    "main.py",
    "main_timed_test.py",
    "intraday_collector_supervisor.py",
    "kiwoom_realtime_collector.py",
    "kiwoom_login_diagnostics.py",
    "kiwoom_smoke_test.py",
    "realtime_test.py",
    "historical_backfill.py",
]


def run_preflight(
    allow_existing_python=False,
    allow_existing_kiwoom=False,
    kill_residual=False,
    project_dir=None,
):
    """Inspect and optionally clean residual sessions.

    Returns a dictionary suitable for compact logging. Unknown Python
    processes are never killed automatically; they are reported for manual
    review unless the user allows existing Python processes.
    """
    project_dir = os.path.abspath(project_dir or os.getcwd())
    result = inspect_residual_sessions(
        allow_existing_python=allow_existing_python,
        allow_existing_kiwoom=allow_existing_kiwoom,
        project_dir=project_dir,
    )

    if kill_residual and result["residuals"]:
        actions = kill_residual_sessions(result["residuals"], project_dir)
        time.sleep(1.0)
        result = inspect_residual_sessions(
            allow_existing_python=allow_existing_python,
            allow_existing_kiwoom=allow_existing_kiwoom,
            project_dir=project_dir,
        )
        result["kill_actions"] = actions
    else:
        result["kill_actions"] = []

    return result


def inspect_residual_sessions(allow_existing_python, allow_existing_kiwoom, project_dir):
    """Return residual Python/Kiwoom processes that may block login."""
    processes, source, error = list_relevant_processes()
    current_pid = os.getpid()
    parent_pid = get_parent_pid()
    ignored_pids = set([current_pid])
    if parent_pid:
        ignored_pids.add(parent_pid)

    residuals = []
    ignored = []
    warnings = []

    for process in processes:
        pid = process.get("pid")
        name = process.get("name") or ""
        command_line = process.get("command_line") or ""
        lower_name = name.lower()

        if pid in ignored_pids:
            ignored.append(make_process_entry(process, "current_or_parent"))
            continue

        is_python = lower_name in PYTHON_PROCESS_NAMES
        is_kiwoom = is_kiwoom_process(lower_name, command_line, is_python)

        if is_python and is_current_conda_wrapper(command_line):
            ignored.append(make_process_entry(process, "current_conda_wrapper"))
            continue

        if is_python and allow_existing_python:
            ignored.append(make_process_entry(process, "allowed_python"))
            continue
        if is_kiwoom and allow_existing_kiwoom:
            ignored.append(make_process_entry(process, "allowed_kiwoom"))
            continue

        if is_python:
            if not command_line:
                warnings.append(make_process_entry(process, "unknown_python_command_line"))
            elif is_project_python(command_line, project_dir):
                residuals.append(make_process_entry(process, "residual_project_python"))
            else:
                warnings.append(make_process_entry(process, "non_project_python"))
        elif is_kiwoom:
            residuals.append(make_process_entry(process, "residual_kiwoom"))

    inspection_available = source != "none"

    return {
        "ok": inspection_available and len(residuals) == 0,
        "source": source,
        "error": error,
        "inspection_available": inspection_available,
        "current_pid": current_pid,
        "parent_pid": parent_pid,
        "residuals": residuals,
        "ignored": ignored,
        "warnings": warnings,
    }


def list_relevant_processes():
    """List Python/Kiwoom-like processes using the best available method."""
    processes, error = list_processes_from_cim()
    if processes is not None:
        return processes, "cim", error

    processes, tasklist_error = list_processes_from_tasklist()
    if processes is not None:
        return processes, "tasklist", error or tasklist_error

    return [], "none", error or tasklist_error


def list_processes_from_cim():
    """Use PowerShell CIM to get process names and command lines."""
    command = (
        "$ErrorActionPreference='Stop'; "
        "$items = Get-CimInstance Win32_Process | "
        "Where-Object { "
        "$_.Name -match '^(python|pythonw)\\.exe$' -or "
        "$_.Name -match '^(khmini|khministarter|nkmini|nkministarter|opstarter|kstarter|khopenapi|koastudio|koastudiosa)\\.exe$' "
        "} | Select-Object ProcessId,Name,CommandLine; "
        "if ($items) { $items | ConvertTo-Json -Compress }"
    )

    errors = []
    for powershell_path in executable_candidates(
        "powershell",
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
    ):
        try:
            output = subprocess.check_output(
                [powershell_path, "-NoProfile", "-Command", command],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=8,
            ).strip()
            break
        except Exception as exc:
            errors.append("{}: {}".format(powershell_path, exc))
    else:
        return None, " | ".join(errors)

    if not output:
        return [], None

    try:
        parsed = json.loads(output)
    except ValueError as exc:
        return None, str(exc)

    if isinstance(parsed, dict):
        parsed = [parsed]

    processes = []
    for item in parsed:
        processes.append({
            "pid": safe_int(item.get("ProcessId")),
            "name": item.get("Name") or "",
            "command_line": item.get("CommandLine") or "",
        })

    return processes, None


def list_processes_from_tasklist():
    """Fallback when command-line process inspection is denied."""
    errors = []
    for tasklist_path in executable_candidates(
        "tasklist",
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tasklist.exe"),
    ):
        try:
            output = subprocess.check_output(
                [tasklist_path, "/FO", "CSV", "/NH"],
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                timeout=8,
            )
            break
        except Exception as exc:
            errors.append("{}: {}".format(tasklist_path, exc))
    else:
        return None, " | ".join(errors)

    processes = []
    reader = csv.reader(io.StringIO(output))
    for row in reader:
        if len(row) < 2:
            continue
        name = row[0]
        lower_name = name.lower()
        if lower_name not in PYTHON_PROCESS_NAMES and lower_name not in KIWOOM_PROCESS_NAMES:
            continue
        processes.append({
            "pid": safe_int(row[1]),
            "name": name,
            "command_line": "",
        })

    return processes, None


def executable_candidates(*paths):
    """Return unique executable candidates while preserving fallback order."""
    seen = set()
    result = []
    for path in paths:
        if not path:
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def is_kiwoom_process(lower_name, command_line, is_python):
    """Return True for Kiwoom/OpenAPI host processes, excluding Python."""
    if is_python:
        return False
    if lower_name in KIWOOM_PROCESS_NAMES:
        return True

    text = (command_line or "").lower()
    return (
        "khopenapi" in text
        or "koastudio" in text
        or "opstarter" in text
        or "nkmini" in text
        or "kiwoom" in text
        or "영웅문" in command_line
    )


def is_current_conda_wrapper(command_line):
    """Ignore the conda-run wrapper for the script currently being checked."""
    lower_command = (command_line or "").lower()
    if "conda-script.py" not in lower_command:
        return False

    script_name = os.path.basename(sys.argv[0] or "").lower()
    if script_name and script_name in lower_command:
        return True

    return False


def is_project_python(command_line, project_dir):
    """Return True when a Python process belongs to this project/runtime."""
    lower_command = (command_line or "").lower()
    project_dir_lower = os.path.abspath(project_dir).lower()
    if project_dir_lower in lower_command:
        return True
    return any(marker in lower_command for marker in PROJECT_PYTHON_MARKERS)


def kill_residual_sessions(residuals, project_dir):
    """Terminate residual sessions only for explicit cleanup runs."""
    actions = []
    project_dir_lower = os.path.abspath(project_dir).lower()

    for item in residuals:
        pid = item.get("pid")
        reason = item.get("reason")
        command_line = item.get("command_line") or ""
        lower_command = command_line.lower()
        can_kill = False

        if reason == "residual_kiwoom":
            can_kill = True
        elif reason in ("residual_python", "residual_project_python"):
            if project_dir_lower in lower_command:
                can_kill = True
            elif any(marker in lower_command for marker in PROJECT_PYTHON_MARKERS):
                can_kill = True

        if not pid or pid == os.getpid():
            can_kill = False

        if not can_kill:
            actions.append({
                "pid": pid,
                "name": item.get("name"),
                "action": "skipped",
                "reason": "unknown_python_or_protected",
            })
            continue

        try:
            os.kill(pid, signal.SIGTERM)
            actions.append({
                "pid": pid,
                "name": item.get("name"),
                "action": "terminated",
                "reason": reason,
            })
        except Exception as exc:
            actions.append({
                "pid": pid,
                "name": item.get("name"),
                "action": "failed",
                "reason": str(exc),
            })

    return actions


def print_preflight_report(result):
    """Print a stable key-value report for logs and automation."""
    print("PREFLIGHT_STATUS={}".format("ok" if result["ok"] else "blocked"))
    print("PREFLIGHT_SOURCE={}".format(result.get("source")))
    print("PREFLIGHT_CURRENT_PID={}".format(result.get("current_pid")))
    print("PREFLIGHT_PARENT_PID={}".format(result.get("parent_pid")))

    if result.get("error"):
        print("PREFLIGHT_PROCESS_LIST_ERROR={}".format(result["error"]))

    for action in result.get("kill_actions", []):
        print("PREFLIGHT_KILL_ACTION=pid:{pid},name:{name},action:{action},reason:{reason}".format(
            pid=action.get("pid"),
            name=action.get("name"),
            action=action.get("action"),
            reason=compact_text(action.get("reason")),
        ))

    print("PREFLIGHT_RESIDUAL_COUNT={}".format(len(result.get("residuals", []))))
    for item in result.get("residuals", []):
        print("PREFLIGHT_RESIDUAL=pid:{pid},name:{name},reason:{reason},cmd:{cmd}".format(
            pid=item.get("pid"),
            name=item.get("name"),
            reason=item.get("reason"),
            cmd=compact_text(item.get("command_line")),
        ))

    print("PREFLIGHT_WARNING_COUNT={}".format(len(result.get("warnings", []))))
    for item in result.get("warnings", []):
        print("PREFLIGHT_WARNING=pid:{pid},name:{name},reason:{reason},cmd:{cmd}".format(
            pid=item.get("pid"),
            name=item.get("name"),
            reason=item.get("reason"),
            cmd=compact_text(item.get("command_line")),
        ))


def make_process_entry(process, reason):
    """Normalize one process entry for reports."""
    return {
        "pid": process.get("pid"),
        "name": process.get("name"),
        "command_line": process.get("command_line") or "",
        "reason": reason,
    }


def get_parent_pid():
    try:
        return os.getppid()
    except AttributeError:
        return None


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compact_text(value, limit=220):
    text = (value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def parse_args():
    parser = argparse.ArgumentParser(description="Check residual Kiwoom/Python sessions.")
    parser.add_argument("--allow-existing-python", action="store_true")
    parser.add_argument("--allow-existing-kiwoom", action="store_true")
    parser.add_argument(
        "--allow-inspection-unavailable",
        action="store_true",
        help="Return success when process inspection is unavailable. Use only for offline diagnostics.",
    )
    parser.add_argument("--kill-residual", action="store_true")
    parser.add_argument("--project-dir", default=os.getcwd())
    return parser.parse_args()


def main():
    args = parse_args()
    result = run_preflight(
        allow_existing_python=args.allow_existing_python,
        allow_existing_kiwoom=args.allow_existing_kiwoom,
        kill_residual=args.kill_residual,
        project_dir=args.project_dir,
    )
    if args.allow_inspection_unavailable and not result.get("inspection_available"):
        result["warnings"].append({
            "pid": None,
            "name": "process_inspection",
            "command_line": result.get("error") or "",
            "reason": "inspection_unavailable_allowed",
        })
        result["ok"] = True
    print_preflight_report(result)
    return 0 if result["ok"] else 10


if __name__ == "__main__":
    raise SystemExit(main())
