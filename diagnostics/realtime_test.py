"""Minimal Kiwoom realtime connection smoke test.

This file is intentionally smaller than ``main.py``. Use it only to verify
login and raw 주식체결 reception from Kiwoom OpenAPI+.
"""

import sys
from datetime import datetime

from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget


class KiwoomRealtimeTest:
    """Login to Kiwoom and print raw realtime trade fields."""

    def __init__(self):
        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")

        self.ocx.OnEventConnect.connect(self.on_login)
        self.ocx.OnReceiveRealData.connect(self.on_receive_real_data)

        print("로그인 요청")
        self.ocx.dynamicCall("CommConnect()")

    def on_login(self, err_code):
        """Register realtime fields after successful login."""
        if err_code == 0:
            print("로그인 성공")
            self.register_realtime()
        else:
            print("로그인 실패:", err_code)

    def register_realtime(self):
        """Register a small stock list with basic trade FIDs."""
        codes = "005930;000660;035720;035420"

        fid_list = "10;12;13;15;20"

        result = self.ocx.dynamicCall(
            "SetRealReg(QString, QString, QString, QString)",
            "1000",
            codes,
            fid_list,
            "0"
        )

        print("실시간 등록 결과:", result)
        print("등록 종목:", codes)

    def get_real_data(self, code, fid):
        """Read one realtime FID value from Kiwoom."""
        return self.ocx.dynamicCall(
            "GetCommRealData(QString, int)",
            code,
            fid
        ).strip()

    def on_receive_real_data(self, code, real_type, real_data):
        """Print raw trade data when Kiwoom sends a 주식체결 event."""
        if real_type != "주식체결":
            return

        current_price = self.get_real_data(code, 10)
        change_rate = self.get_real_data(code, 12)
        acc_volume = self.get_real_data(code, 13)
        tick_volume = self.get_real_data(code, 15)
        trade_time = self.get_real_data(code, 20)

        print({
            "received_at": datetime.now().strftime("%H:%M:%S"),
            "code": code,
            "trade_time": trade_time,
            "price": current_price,
            "change_rate": change_rate,
            "acc_volume": acc_volume,
            "tick_volume": tick_volume,
        })


if __name__ == "__main__":
    app = QApplication(sys.argv)
    test = KiwoomRealtimeTest()
    sys.exit(app.exec_())
