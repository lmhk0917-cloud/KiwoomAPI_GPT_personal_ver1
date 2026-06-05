"""Minimal Kiwoom realtime tick collector.

This script intentionally avoids GPT, Telegram, TR context requests, and the
main analysis loop. It owns one Kiwoom OpenAPI+ QAxWidget session, receives
raw realtime stock ticks, and stores them into SQLite through ``TickStore``.
Use it as the first market-hours integration step when duplicate Kiwoom login
sessions are a concern.
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget

from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from config import WATCH_CODES
from data_store import TickStore


TRADE_FID_LIST = "10;12;13;15;16;17;18;20;228"


class KiwoomRealtimeCollector:
    """Collect Kiwoom 주식체결 events and persist them to SQLite."""

    def __init__(
        self,
        store,
        codes,
        login_timeout_sec,
        duration_seconds,
        require_existing_login,
        require_ticks=False,
    ):
        self.store = store
        self.codes = list(codes)
        self.login_timeout_sec = login_timeout_sec
        self.duration_seconds = duration_seconds
        self.require_existing_login = require_existing_login
        self.require_ticks = require_ticks
        self.login_result = None
        self.register_result = None
        self.real_event_count = 0
        self.saved_tick_count = 0
        self.exit_code = 1
        self.login_timer = None
        self.finish_timer = None

        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        if self.ocx.isNull():
            print("COLLECTOR_OCX_STATUS=failed")
            print("COLLECTOR_ERROR=KHOPENAPI.KHOpenAPICtrl.1 could not be created")
            QTimer.singleShot(0, QApplication.instance().quit)
            return

        print("COLLECTOR_OCX_STATUS=created")
        connect_state = self.ocx.dynamicCall("GetConnectState()")
        print("COLLECTOR_CONNECT_STATE_BEFORE={}".format(connect_state))

        self.ocx.OnEventConnect.connect(self.on_login)
        self.ocx.OnReceiveRealData.connect(self.on_receive_real_data)

        try:
            is_connected = int(connect_state) == 1
        except (TypeError, ValueError):
            is_connected = False

        if is_connected:
            print("COLLECTOR_LOGIN_SKIPPED_ALREADY_CONNECTED=True")
            QTimer.singleShot(0, lambda: self.on_login(0))
            return

        if self.require_existing_login:
            print("COLLECTOR_ABORTED=existing_login_not_confirmed")
            self.exit_code = 4
            QTimer.singleShot(0, QApplication.instance().quit)
            return

        QTimer.singleShot(0, self.request_login)

    def request_login(self):
        """Request Kiwoom login after the Qt event loop has started."""
        connect_state = self.ocx.dynamicCall("GetConnectState()")
        print("COLLECTOR_CONNECT_STATE_AT_LOGIN_REQUEST={}".format(connect_state))

        try:
            is_connected = int(connect_state) == 1
        except (TypeError, ValueError):
            is_connected = False

        if is_connected:
            print("COLLECTOR_LOGIN_SKIPPED_ALREADY_CONNECTED_AT_REQUEST=True")
            self.on_login(0)
            return

        self.login_timer = QTimer()
        self.login_timer.setSingleShot(True)
        self.login_timer.timeout.connect(self.on_login_timeout)
        self.login_timer.start(self.login_timeout_sec * 1000)

        print("COLLECTOR_LOGIN_REQUESTED=True")
        result = self.ocx.dynamicCall("CommConnect()")
        print("COLLECTOR_LOGIN_REQUEST_RETURN={}".format(result))

    def on_login(self, err_code):
        """Register realtime ticks after Kiwoom login succeeds."""
        if self.login_timer:
            self.login_timer.stop()

        self.login_result = int(err_code)
        print("COLLECTOR_LOGIN_RESULT={}".format(self.login_result))
        print("COLLECTOR_CONNECT_STATE_AFTER={}".format(self.ocx.dynamicCall("GetConnectState()")))

        if self.login_result != 0:
            self.exit_code = 2
            QApplication.instance().quit()
            return

        self.register_realtime()

        self.finish_timer = QTimer()
        self.finish_timer.setSingleShot(True)
        self.finish_timer.timeout.connect(self.finish)
        self.finish_timer.start(self.duration_seconds * 1000)

    def register_realtime(self):
        """Register basic realtime trade FIDs for all configured codes."""
        code_text = ";".join(self.codes)
        self.register_result = self.ocx.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            "9200",
            code_text,
            TRADE_FID_LIST,
            "0"
        )
        print("COLLECTOR_REALTIME_REGISTER_RESULT={}".format(self.register_result))
        print("COLLECTOR_REALTIME_REGISTER_CODES={}".format(code_text))

    def on_receive_real_data(self, code, real_type, real_data):
        """Persist stock trade events and print the first few samples."""
        self.real_event_count += 1

        if not self._is_real_type(real_type, "주식체결"):
            return

        tick = {
            "code": code,
            "trade_time": self.get_real_data(code, 20),
            "price": self.parse_int(self.get_real_data(code, 10)),
            "change_rate": self.parse_float(self.get_real_data(code, 12)),
            "acc_volume": self.parse_int(self.get_real_data(code, 13)),
            "tick_volume": self.parse_int(self.get_real_data(code, 15)),
            "open_price": self.parse_int(self.get_real_data(code, 16)),
            "high_price": self.parse_int(self.get_real_data(code, 17)),
            "low_price": self.parse_int(self.get_real_data(code, 18)),
            "strength": self.parse_float(self.get_real_data(code, 228)),
            "received_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        }

        self.store.add_tick(tick)
        self.saved_tick_count += 1

        if self.saved_tick_count <= 5 or self.saved_tick_count % 100 == 0:
            print("COLLECTOR_TICK_SAMPLE={},code:{},time:{},price:{},volume:{}".format(
                self.saved_tick_count,
                tick["code"],
                tick["trade_time"],
                tick["price"],
                tick["tick_volume"],
            ))

    def get_real_data(self, code, fid):
        """Read one realtime FID value."""
        return self.ocx.dynamicCall(
            "GetCommRealData(QString, int)",
            code,
            fid
        ).strip()

    def on_login_timeout(self):
        """Exit if login callback does not arrive."""
        print("COLLECTOR_LOGIN_TIMEOUT=True")
        print("COLLECTOR_CONNECT_STATE_TIMEOUT={}".format(self.ocx.dynamicCall("GetConnectState()")))
        self.exit_code = 3
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(3)

    def finish(self):
        """Clean up realtime registration and exit."""
        print("COLLECTOR_FINISH_REQUESTED=True")
        try:
            self.ocx.dynamicCall("SetRealRemove(QString, QString)", "9200", "ALL")
        except Exception as exc:
            print("COLLECTOR_REALTIME_CLEAR_ERROR={}".format(exc))

        print("COLLECTOR_REALTIME_EVENT_COUNT={}".format(self.real_event_count))
        print("COLLECTOR_SAVED_TICK_COUNT={}".format(self.saved_tick_count))
        self.exit_code = 0
        if self.require_ticks and self.saved_tick_count <= 0:
            self.exit_code = 5
        QApplication.instance().quit()

    @staticmethod
    def parse_int(value):
        try:
            value = value.strip().replace("+", "").replace("-", "")
            if value == "":
                return None
            return abs(int(value))
        except Exception:
            return None

    @staticmethod
    def parse_float(value):
        try:
            value = value.strip().replace("+", "").replace("%", "")
            if value == "":
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _is_real_type(real_type, expected):
        """Accept normal Korean and mojibake Kiwoom real_type names."""
        if real_type == expected:
            return True

        try:
            if real_type.encode("latin1").decode("cp949") == expected:
                return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

        try:
            if expected.encode("cp949").decode("latin1") == real_type:
                return True
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

        return False


def count_table_rows(db_path):
    """Return the current tick row count and latest received timestamp."""
    if not os.path.exists(db_path):
        return {"ticks": 0, "latest_received_at": None}

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT COUNT(*), MAX(received_at) FROM ticks").fetchone()
        return {"ticks": row[0], "latest_received_at": row[1]}
    finally:
        conn.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Collect realtime Kiwoom ticks into SQLite.")
    parser.add_argument("--codes", default=",".join(WATCH_CODES.keys()))
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--minutes", type=int, help="Run duration in minutes. Overrides --seconds.")
    parser.add_argument("--login-timeout-sec", type=int, default=45)
    parser.add_argument("--require-existing-login", action="store_true")
    parser.add_argument("--require-ticks", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_runtime_logging("kiwoom_collector")
    duration_seconds = args.minutes * 60 if args.minutes is not None else args.seconds
    codes = [code.strip() for code in args.codes.split(",") if code.strip()]

    before = count_table_rows(DEFAULT_DB_PATH)
    print("COLLECTOR_DB_BEFORE=ticks:{},latest:{}".format(
        before["ticks"],
        before["latest_received_at"],
    ))
    print("COLLECTOR_DURATION_SECONDS={}".format(duration_seconds))

    app = QApplication(sys.argv)
    store = TickStore(db_path=DEFAULT_DB_PATH)
    collector = KiwoomRealtimeCollector(
        store=store,
        codes=codes,
        login_timeout_sec=args.login_timeout_sec,
        duration_seconds=duration_seconds,
        require_existing_login=args.require_existing_login,
        require_ticks=args.require_ticks,
    )

    def force_exit():
        print("COLLECTOR_FORCE_EXIT=True")
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(20)

    QTimer.singleShot((duration_seconds + args.login_timeout_sec + 30) * 1000, force_exit)
    exit_code = app.exec_()

    try:
        store.close()
    except Exception as exc:
        print("COLLECTOR_DB_CLOSE_ERROR={}".format(exc))

    after = count_table_rows(DEFAULT_DB_PATH)
    print("COLLECTOR_DB_AFTER=ticks:{},latest:{}".format(
        after["ticks"],
        after["latest_received_at"],
    ))
    print("COLLECTOR_DB_DELTA=ticks:{}".format(after["ticks"] - before["ticks"]))

    if exit_code:
        return exit_code
    return collector.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
