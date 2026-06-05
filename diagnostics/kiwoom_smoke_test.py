"""Timed Kiwoom OpenAPI+ smoke test.

This script is safer than realtime_test.py for automation because it exits by
itself after a login timeout and a short realtime observation window.
"""

import argparse
import os
import sys
from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget


class KiwoomSmokeTest:
    """Check Kiwoom OCX creation, login, realtime registration, and tick receipt."""

    def __init__(self, codes, login_timeout_sec, realtime_seconds):
        self.codes = codes
        self.login_timeout_sec = login_timeout_sec
        self.realtime_seconds = realtime_seconds
        self.login_result = None
        self.register_result = None
        self.real_count = 0
        self.exit_code = 1
        self.login_timer = None

        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        if self.ocx.isNull():
            print("KIWOOM_OCX_STATUS=failed")
            print("ERROR=KHOPENAPI.KHOpenAPICtrl.1 could not be created")
            QTimer.singleShot(0, QApplication.instance().quit)
            return

        print("KIWOOM_OCX_STATUS=created")
        connect_state = self.ocx.dynamicCall("GetConnectState()")
        print("CONNECT_STATE_BEFORE={}".format(connect_state))

        self.ocx.OnEventConnect.connect(self.on_login)
        self.ocx.OnReceiveRealData.connect(self.on_receive_real_data)

        try:
            is_connected = int(connect_state) == 1
        except (TypeError, ValueError):
            is_connected = False

        if is_connected:
            print("LOGIN_SKIPPED_ALREADY_CONNECTED=True")
            QTimer.singleShot(0, lambda: self.on_login(0))
            return

        QTimer.singleShot(0, self.request_login)

    def request_login(self):
        """Request login after the Qt event loop has started."""
        connect_state = self.ocx.dynamicCall("GetConnectState()")
        print("CONNECT_STATE_AT_LOGIN_REQUEST={}".format(connect_state))

        try:
            is_connected = int(connect_state) == 1
        except (TypeError, ValueError):
            is_connected = False

        if is_connected:
            print("LOGIN_SKIPPED_ALREADY_CONNECTED_AT_REQUEST=True")
            self.on_login(0)
            return

        self.login_timer = QTimer()
        self.login_timer.setSingleShot(True)
        self.login_timer.timeout.connect(self.on_login_timeout)
        self.login_timer.start(self.login_timeout_sec * 1000)

        self.ocx.dynamicCall("CommConnect()")
        print("LOGIN_REQUESTED=True")

    def on_login(self, err_code):
        """Handle login result and start a short realtime observation window."""
        if self.login_timer:
            self.login_timer.stop()
        self.login_result = int(err_code)
        print("LOGIN_RESULT={}".format(self.login_result))
        print("CONNECT_STATE_AFTER={}".format(self.ocx.dynamicCall("GetConnectState()")))

        if self.login_result != 0:
            self.exit_code = 2
            QApplication.instance().quit()
            return

        self.register_realtime()

        QTimer.singleShot(self.realtime_seconds * 1000, self.finish)

    def register_realtime(self):
        """Register basic trade FIDs for the requested symbols."""
        code_text = ";".join(self.codes)
        fid_list = "10;12;13;15;20"
        self.register_result = self.ocx.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            "9100",
            code_text,
            fid_list,
            "0"
        )
        print("REALTIME_REGISTER_RESULT={}".format(self.register_result))
        print("REALTIME_REGISTER_CODES={}".format(code_text))

    def on_receive_real_data(self, code, real_type, real_data):
        """Count realtime events and print the first few samples."""
        self.real_count += 1

        if self.real_count <= 5:
            price = self.get_real_data(code, 10)
            trade_time = self.get_real_data(code, 20)
            print("REALTIME_SAMPLE_{}={},{},{},{}".format(
                self.real_count,
                datetime.now().strftime("%H:%M:%S"),
                code,
                real_type,
                price or trade_time
            ))

    def get_real_data(self, code, fid):
        return self.ocx.dynamicCall(
            "GetCommRealData(QString, int)",
            code,
            fid
        ).strip()

    def on_login_timeout(self):
        """Exit cleanly when Kiwoom does not finish login in time."""
        print("LOGIN_TIMEOUT=True")
        print("CONNECT_STATE_TIMEOUT={}".format(self.ocx.dynamicCall("GetConnectState()")))
        self.exit_code = 3
        QApplication.instance().quit()

    def finish(self):
        """Print a compact test summary and exit."""
        try:
            self.ocx.dynamicCall("SetRealRemove(QString, QString)", "9100", "ALL")
        except Exception as exc:
            print("REALTIME_CLEAR_ERROR={}".format(exc))
        print("REALTIME_EVENT_COUNT={}".format(self.real_count))
        self.exit_code = 0 if self.login_result == 0 else 2
        QApplication.instance().quit()


def parse_args():
    parser = argparse.ArgumentParser(description="Run a timed Kiwoom login/realtime smoke test.")
    parser.add_argument(
        "--codes",
        default="005930,000660,035720,035420",
        help="Comma-separated stock codes to register.",
    )
    parser.add_argument("--login-timeout-sec", type=int, default=45)
    parser.add_argument("--realtime-seconds", type=int, default=20)
    return parser.parse_args()


def main():
    args = parse_args()
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]
    app = QApplication(sys.argv)
    test = KiwoomSmokeTest(
        codes=codes,
        login_timeout_sec=args.login_timeout_sec,
        realtime_seconds=args.realtime_seconds,
    )

    def force_exit():
        print("SMOKE_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(20)

    QTimer.singleShot((args.login_timeout_sec + args.realtime_seconds + 30) * 1000, force_exit)
    app.exec_()
    return test.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
