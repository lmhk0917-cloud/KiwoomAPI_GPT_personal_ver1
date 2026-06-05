"""Smoke-test verified Kiwoom market-context TR mappings.

This script logs in through Kiwoom OpenAPI+, requests a small batch of
market-context TRs, prints the merged context JSON, and exits. It does not call
OpenAI, send notifications, or place orders.
"""

import argparse
import json
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from data_store import TickStore
from kiwoom_client import KiwoomClient
from market_context import MarketContextStore


CODE_MAPPINGS = ["short_selling", "stock_loan_trend", "credit", "investor_flow"]
GLOBAL_MAPPINGS = [
    "market_index_kospi",
    "market_index_kosdaq",
    "market_index_kospi200",
    "market_program_trading",
    "derivatives",
    "option_call_chain",
    "option_put_chain",
]


def main():
    args = parse_args()
    codes = parse_codes(args.codes)
    app = QApplication(sys.argv)
    tick_store = TickStore(enable_sqlite=False)
    context_store = MarketContextStore(enabled=True)
    kiwoom = KiwoomClient(
        tick_store=tick_store,
        codes=codes,
        market_context_store=context_store,
    )

    state = {"scheduled": False}

    def maybe_schedule():
        if not kiwoom.is_logged_in or state["scheduled"]:
            return
        state["scheduled"] = True
        schedule_requests(kiwoom, codes, args.request_delay_ms)

    def finish():
        try:
            kiwoom.clear_realtime_codes()
        except Exception as exc:
            print("REALTIME_CLEAR_ERROR={}".format(exc))

        payload = {
            "codes": {
                code: context_store.get_context(code)
                for code in codes
            }
        }
        print("========== MARKET CONTEXT TR TEST RESULT ==========")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        app.quit()

    login_check_timer = QTimer()
    login_check_timer.timeout.connect(maybe_schedule)
    login_check_timer.start(500)

    QTimer.singleShot(args.seconds * 1000, finish)
    kiwoom.login()
    return app.exec_()


def parse_args():
    parser = argparse.ArgumentParser(description="Test Kiwoom market-context TR mappings.")
    parser.add_argument("--codes", default="005930", help="Comma-separated stock codes")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--request-delay-ms", type=int, default=1200)
    return parser.parse_args()


def parse_codes(raw_codes):
    return [code.strip() for code in raw_codes.split(",") if code.strip()]


def schedule_requests(kiwoom, codes, request_delay_ms):
    requests = []
    for code in codes:
        for mapping_name in CODE_MAPPINGS:
            requests.append((mapping_name, code))

    for mapping_name in GLOBAL_MAPPINGS:
        requests.append((mapping_name, None))

    for index, request in enumerate(requests):
        QTimer.singleShot(
            max(request_delay_ms, 0) * index,
            lambda request=request: send_request(kiwoom, request)
        )

    print("SCHEDULED_TR_REQUESTS={}".format(len(requests)))


def send_request(kiwoom, request):
    mapping_name, code = request
    try:
        result = kiwoom.request_context_mapping(mapping_name, code=code)
        print("TR_REQUEST mapping={} code={} result={}".format(
            mapping_name,
            code or "global",
            result,
        ))
    except Exception as exc:
        print("TR_REQUEST_ERROR mapping={} code={} error={}".format(
            mapping_name,
            code or "global",
            exc,
        ))


if __name__ == "__main__":
    raise SystemExit(main())
