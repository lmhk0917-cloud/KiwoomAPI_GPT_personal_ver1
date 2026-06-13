"""Run stability checks for the Kiwoom/OpenAI personal app.

This script avoids live Kiwoom and Telegram calls. By default it includes a
tiny live OpenAI smoke test so the GPT path is verified before market tests.
"""

import argparse
import ast
import os
import subprocess
import sys

from app_paths import DATA_DIR, EXPORTS_DIR, PROJECT_DIR, ensure_app_dirs

ARTIFACT_DIR = EXPORTS_DIR
SIM_DB = os.path.join(DATA_DIR, "stability_check_simulation.db")
EXAMPLE_DB = os.path.join(DATA_DIR, "ui_current_example.db")


def main():
    parser = argparse.ArgumentParser(description="Run offline project stability checks.")
    parser.add_argument("--count", type=int, default=720, help="Ticks per simulation scenario")
    parser.add_argument("--cycle-ticks", type=int, default=30, help="Analyze every N ticks")
    parser.add_argument("--include-ui", action="store_true", help="Also render current UI screenshots")
    parser.add_argument(
        "--skip-gpt-smoke",
        action="store_true",
        help="Skip the live OpenAI API smoke test"
    )
    args = parser.parse_args()

    ensure_app_dirs()
    log("PROJECT_DIR={}".format(PROJECT_DIR))
    log("ARTIFACT_DIR={}".format(ARTIFACT_DIR))

    run_compile_check()
    run_script(["preflight_check.py", "--allow-inspection-unavailable"])
    run_script(["tests/test_signal_logic.py"])
    run_script([
        "simulate_debug.py",
        "--db", SIM_DB,
        "--reset",
        "--count", str(args.count),
        "--cycle-ticks", str(args.cycle_ticks),
    ])
    run_script(["gpt_payload_preview.py", "--db", SIM_DB, "--limit", "3"])
    if args.skip_gpt_smoke:
        log("\n========== gpt_smoke_test.py ==========")
        log("GPT_SMOKE_SKIPPED=True")
    else:
        run_script(["gpt_smoke_test.py"])
    run_script(["gpt_call_report.py", "--db", SIM_DB, "--limit", "5"])
    run_script(["paper_trade_report.py", "--db", SIM_DB, "--min-sample", "3"])
    run_script(["kiwoom_realtime_collector.py", "--help"])
    run_script(["intraday_collector_supervisor.py", "--help"])
    run_script(["kiwoom_login_diagnostics.py", "--help"])

    if args.include_ui:
        run_script(["render_current_ui_screenshots.py"])
        run_script(["gpt_payload_preview.py", "--db", EXAMPLE_DB, "--limit", "2"])

    log("STABILITY_CHECK_RESULT=PASS")
    log("SIM_DB={}".format(SIM_DB))
    if args.include_ui:
        log("UI_EXAMPLE_DB={}".format(EXAMPLE_DB))


def run_compile_check():
    log("\n========== ast syntax check ==========")
    checked = 0
    ignored_dirs = {".git", "__pycache__", ".pytest_cache"}

    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [name for name in dirs if name not in ignored_dirs]
        for filename in files:
            if not filename.endswith(".py"):
                continue

            path = os.path.join(root, filename)
            with open(path, "r", encoding="utf-8-sig") as handle:
                source = handle.read()
            try:
                ast.parse(source, filename=path)
            except SyntaxError as exc:
                raise SystemExit("syntax check failed: {}: {}".format(path, exc))
            checked += 1

    log("AST_SYNTAX_OK={}".format(checked))


def run_script(args):
    command = [sys.executable] + args
    log("\n========== {} ==========".format(" ".join(args)))
    completed = subprocess.run(command, cwd=PROJECT_DIR)
    if completed.returncode != 0:
        raise SystemExit("command failed with exit code {}: {}".format(
            completed.returncode,
            " ".join(args),
        ))


def log(message):
    print(message, flush=True)


if __name__ == "__main__":
    main()
