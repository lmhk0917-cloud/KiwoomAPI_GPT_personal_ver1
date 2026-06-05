"""Kiwoom OpenAPI+ login environment diagnostics.

This script is read-only. It does not call CommConnect, does not terminate
processes, and does not modify registry or OpenAPI files. Use it after OpenAPI
updates or login callback failures to capture the local state in one place.
"""

import argparse
import os
import subprocess
from datetime import datetime

from app_paths import setup_runtime_logging
from preflight_check import print_preflight_report, run_preflight


OPENAPI_DIR = r"C:\OpenAPI"
OPENAPI_LOG_DIR = os.path.join(OPENAPI_DIR, "log")
OPENAPI_SYSTEM_DIR = os.path.join(OPENAPI_DIR, "system")

IMPORTANT_FILES = [
    r"C:\OpenAPI\khopenapi.ocx",
    r"C:\OpenAPI\opcommapi.dll",
    r"C:\OpenAPI\opcomms.dll",
    r"C:\OpenAPI\opstarter.exe",
    r"C:\OpenAPI\apiinitrsc.lst",
    r"C:\OpenAPI\apiotrsc.lst",
    r"C:\OpenAPI\mst.lst",
    r"C:\OpenAPI\system\opcomms.ini",
    r"C:\OpenAPI\system\MultiLogin.ini",
    r"C:\OpenAPI\system\Autologin.dat",
]


def main():
    args = parse_args()
    setup_runtime_logging("kiwoom_login_diagnostics")
    print("DIAG_STARTED_AT={}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print("DIAG_OPENAPI_DIR={}".format(OPENAPI_DIR))
    print_preflight_report(run_preflight())
    print_file_status()
    print_registry_status()
    print_recent_log_files()
    print_selected_file_text(args.tail_lines)
    print("DIAG_FINISHED_AT={}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return 0


def print_file_status():
    """Print existence, size, and mtime for important OpenAPI files."""
    for path in IMPORTANT_FILES:
        if not os.path.exists(path):
            print("DIAG_FILE_MISSING={}".format(path))
            continue
        stat = os.stat(path)
        print("DIAG_FILE=path:{},size:{},mtime:{}".format(
            path,
            stat.st_size,
            datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        ))


def print_registry_status():
    """Print COM registration info for the 32-bit OpenAPI control."""
    commands = [
        (
            "DIAG_REG_PROGID",
            "Get-ItemProperty -Path 'Registry::HKEY_CLASSES_ROOT\\KHOPENAPI.KHOpenAPICtrl.1\\CLSID' "
            "-ErrorAction SilentlyContinue | Format-List"
        ),
        (
            "DIAG_REG_WOW64_PROGID",
            "Get-ItemProperty -Path 'Registry::HKEY_CLASSES_ROOT\\Wow6432Node\\KHOPENAPI.KHOpenAPICtrl.1\\CLSID' "
            "-ErrorAction SilentlyContinue | Format-List"
        ),
        (
            "DIAG_REG_INPROC",
            "$clsid=(Get-ItemProperty -Path 'Registry::HKEY_CLASSES_ROOT\\KHOPENAPI.KHOpenAPICtrl.1\\CLSID' "
            "-ErrorAction SilentlyContinue).'(default)'; "
            "if ($clsid) { Get-ItemProperty -Path ('Registry::HKEY_CLASSES_ROOT\\Wow6432Node\\CLSID\\' + $clsid + '\\InprocServer32') "
            "-ErrorAction SilentlyContinue | Format-List }"
        ),
    ]

    for label, command in commands:
        print("{}_BEGIN".format(label))
        output = run_powershell(command)
        print(output.strip() if output.strip() else "{}_EMPTY".format(label))
        print("{}_END".format(label))


def print_recent_log_files():
    """Print the most recently touched OpenAPI log files."""
    if not os.path.isdir(OPENAPI_LOG_DIR):
        print("DIAG_LOG_DIR_MISSING={}".format(OPENAPI_LOG_DIR))
        return

    files = []
    for name in os.listdir(OPENAPI_LOG_DIR):
        path = os.path.join(OPENAPI_LOG_DIR, name)
        if os.path.isfile(path):
            stat = os.stat(path)
            files.append((stat.st_mtime, path, stat.st_size))

    for mtime, path, size in sorted(files, reverse=True)[:12]:
        print("DIAG_LOG_FILE=path:{},size:{},mtime:{}".format(
            path,
            size,
            datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
        ))


def print_selected_file_text(tail_lines):
    """Print sanitized tails of key OpenAPI text logs and ini files."""
    today = datetime.now().strftime("%Y%m%d")
    paths = [
        os.path.join(OPENAPI_LOG_DIR, "KOA_lmh0917_{}.log".format(today)),
        os.path.join(OPENAPI_LOG_DIR, "VerLog.{}".format(today)),
        os.path.join(OPENAPI_LOG_DIR, "CommsLog.{}".format(today)),
        os.path.join(OPENAPI_SYSTEM_DIR, "MultiLogin.ini"),
        os.path.join(OPENAPI_SYSTEM_DIR, "opcomms.ini"),
    ]

    for path in paths:
        print("DIAG_TEXT_BEGIN={}".format(path))
        if not os.path.exists(path):
            print("DIAG_TEXT_MISSING={}".format(path))
            print("DIAG_TEXT_END={}".format(path))
            continue

        for line in read_tail(path, tail_lines):
            print(mask_sensitive_line(line.rstrip()))
        print("DIAG_TEXT_END={}".format(path))


def read_tail(path, tail_lines):
    """Read a small tail from cp949-ish OpenAPI text files."""
    with open(path, "r", encoding="cp949", errors="replace") as handle:
        lines = handle.readlines()
    return lines[-tail_lines:]


def mask_sensitive_line(line):
    """Avoid printing saved encoded IDs/password-like fields verbatim."""
    if "USER_ID=" in line:
        return "USER_ID=<masked>"
    if "InitDlg  AutoConnect" in line:
        return "InitDlg AutoConnect <masked>"
    return line


def run_powershell(command):
    try:
        return subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=8,
        )
    except Exception as exc:
        return "ERROR={}".format(exc)


def parse_args():
    parser = argparse.ArgumentParser(description="Diagnose Kiwoom OpenAPI login environment.")
    parser.add_argument("--tail-lines", type=int, default=80)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
