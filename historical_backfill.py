"""Kiwoom historical daily/minute bar backfill.

Run this script in the 32-bit conda environment with Kiwoom OpenAPI+ available.
It logs in through QAxWidget, requests historical daily/minute OHLCV TR data,
and upserts rows into the ``historical_bars`` SQLite table.

Examples:
    conda run -n py37_32 python historical_backfill.py --daily --minute --days 365 --minute-days 20
    conda run -n py37_32 python historical_backfill.py --codes 005930,000660 --daily
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from app_paths import DEFAULT_DB_PATH, setup_runtime_logging
from config import (
    BACKFILL_DAILY_DAYS,
    BACKFILL_MAX_PAGES_PER_JOB,
    BACKFILL_MAX_TR_REQUESTS_PER_RUN,
    BACKFILL_MINUTE_DAYS,
    BACKFILL_MINUTE_INTERVALS,
    BACKFILL_REQUEST_DELAY_MS,
    WATCH_CODES,
)
from data_store import TickStore


TR_DAILY = "opt10081"
TR_MINUTE = "opt10080"
RQ_DAILY = "HIST_DAILY"
RQ_MINUTE = "HIST_MINUTE"


class BackfillJob:
    """One Kiwoom historical TR request target."""

    def __init__(self, code, timeframe, from_date, interval=None):
        self.code = code
        self.timeframe = timeframe
        self.from_date = from_date
        self.interval = interval
        self.page_count = 0
        self.saved_count = 0
        self.finished = False


class HistoricalBackfillApp:
    """Sequential Kiwoom TR backfill runner."""

    def __init__(
        self,
        db_path,
        codes,
        daily,
        minute,
        days,
        minute_days,
        minute_intervals,
        adjusted_price_type,
        request_delay_ms,
        max_pages,
        max_requests,
    ):
        self.store = TickStore(db_path=db_path)
        self.codes = codes
        self.adjusted_price_type = adjusted_price_type
        self.request_delay_ms = request_delay_ms
        self.max_pages = max_pages
        self.max_requests = max_requests
        self.request_count = 0
        self.jobs = self._make_jobs(
            daily=daily,
            minute=minute,
            days=days,
            minute_days=minute_days,
            minute_intervals=minute_intervals,
        )
        self.current_job = None
        self.total_saved_count = 0

        self._print_plan()

        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.ocx.OnEventConnect.connect(self.on_login)
        self.ocx.OnReceiveTrData.connect(self.on_receive_tr_data)

        print("Kiwoom historical backfill login request")
        self.ocx.dynamicCall("CommConnect()")

    def _make_jobs(self, daily, minute, days, minute_days, minute_intervals):
        jobs = []
        today = datetime.now()
        daily_from_date = (today - timedelta(days=days)).strftime("%Y%m%d")
        minute_from_date = (today - timedelta(days=minute_days)).strftime("%Y%m%d")

        for code in self.codes:
            if daily:
                jobs.append(BackfillJob(code=code, timeframe="day", from_date=daily_from_date))

            if minute:
                for interval in minute_intervals:
                    jobs.append(
                        BackfillJob(
                            code=code,
                            timeframe="{}m".format(interval),
                            from_date=minute_from_date,
                            interval=interval,
                        )
                    )

        return jobs

    def on_login(self, err_code):
        """Start queue after Kiwoom login succeeds."""
        if err_code != 0:
            print("Kiwoom login failed:", err_code)
            self.finish()
            return

        print("Kiwoom login success")
        print("Backfill job count:", len(self.jobs))
        QTimer.singleShot(self.request_delay_ms, self.request_next_job)

    def request_next_job(self):
        """Request the next queued job."""
        if not self.jobs:
            print("Backfill completed. saved rows:", self.total_saved_count)
            self.finish()
            return

        self.current_job = self.jobs.pop(0)
        self.request_current_job(prev_next=0)

    def request_current_job(self, prev_next):
        """Request the current job page."""
        job = self.current_job

        if not job or job.finished:
            QTimer.singleShot(self.request_delay_ms, self.request_next_job)
            return

        if self.request_count >= self.max_requests:
            print(
                "Backfill TR request cap reached:",
                self.request_count,
                "/",
                self.max_requests,
            )
            self.finish()
            return

        if job.page_count >= self.max_pages:
            print("Max pages reached:", job.code, job.timeframe, "saved:", job.saved_count)
            QTimer.singleShot(self.request_delay_ms, self.request_next_job)
            return

        if job.timeframe == "day":
            self._request_daily(job, prev_next)
        else:
            self._request_minute(job, prev_next)

    def _request_daily(self, job, prev_next):
        self.request_count += 1
        print(
            "TR request:",
            self.request_count,
            "/",
            self.max_requests,
            job.code,
            job.timeframe,
            "prev_next=" + str(prev_next),
        )
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "종목코드", job.code)
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "기준일자", datetime.now().strftime("%Y%m%d"))
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", self.adjusted_price_type)
        self.ocx.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            RQ_DAILY,
            TR_DAILY,
            prev_next,
            "3000",
        )

    def _request_minute(self, job, prev_next):
        self.request_count += 1
        print(
            "TR request:",
            self.request_count,
            "/",
            self.max_requests,
            job.code,
            job.timeframe,
            "prev_next=" + str(prev_next),
        )
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "종목코드", job.code)
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "틱범위", str(job.interval))
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", self.adjusted_price_type)
        self.ocx.dynamicCall(
            "CommRqData(QString, QString, int, QString)",
            RQ_MINUTE,
            TR_MINUTE,
            prev_next,
            "3001",
        )

    def on_receive_tr_data(
        self,
        screen_no,
        rq_name,
        tr_code,
        record_name,
        prev_next,
        data_len,
        error_code,
        message,
        splm_msg,
    ):
        """Parse a received TR page and continue pagination when needed."""
        job = self.current_job

        if not job:
            return

        job.page_count += 1

        if rq_name == RQ_DAILY:
            bars = self._parse_daily_page(job, tr_code, record_name)
        elif rq_name == RQ_MINUTE:
            bars = self._parse_minute_page(job, tr_code, record_name)
        else:
            return

        saved_count = self.store.save_historical_bars(bars)
        job.saved_count += saved_count
        self.total_saved_count += saved_count

        print(
            "Backfill page:",
            job.code,
            job.timeframe,
            "page=" + str(job.page_count),
            "saved=" + str(saved_count),
            "total_job_saved=" + str(job.saved_count),
        )

        if self._should_continue(job, bars, prev_next):
            QTimer.singleShot(
                self.request_delay_ms,
                lambda: self.request_current_job(prev_next=2),
            )
        else:
            job.finished = True
            QTimer.singleShot(self.request_delay_ms, self.request_next_job)

    def _parse_daily_page(self, job, tr_code, record_name):
        count = self._get_repeat_count(tr_code, record_name)
        bars = []
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        for index in range(count):
            bar_time = self._get_comm_data(tr_code, record_name, index, "일자")

            if not self._is_valid_bar_time(bar_time):
                continue

            bars.append({
                "code": job.code,
                "timeframe": "day",
                "bar_time": bar_time,
                "open": self._parse_number(self._get_comm_data(tr_code, record_name, index, "시가")),
                "high": self._parse_number(self._get_comm_data(tr_code, record_name, index, "고가")),
                "low": self._parse_number(self._get_comm_data(tr_code, record_name, index, "저가")),
                "close": self._parse_number(self._get_comm_data(tr_code, record_name, index, "현재가")),
                "volume": self._parse_number(self._get_comm_data(tr_code, record_name, index, "거래량")),
                "trading_value": self._parse_number(self._get_comm_data(tr_code, record_name, index, "거래대금")),
                "source": TR_DAILY,
                "fetched_at": fetched_at,
            })

        return bars

    def _parse_minute_page(self, job, tr_code, record_name):
        count = self._get_repeat_count(tr_code, record_name)
        bars = []
        fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        for index in range(count):
            bar_time = self._get_comm_data(tr_code, record_name, index, "체결시간")

            if not self._is_valid_bar_time(bar_time):
                continue

            bars.append({
                "code": job.code,
                "timeframe": job.timeframe,
                "bar_time": bar_time,
                "open": self._parse_number(self._get_comm_data(tr_code, record_name, index, "시가")),
                "high": self._parse_number(self._get_comm_data(tr_code, record_name, index, "고가")),
                "low": self._parse_number(self._get_comm_data(tr_code, record_name, index, "저가")),
                "close": self._parse_number(self._get_comm_data(tr_code, record_name, index, "현재가")),
                "volume": self._parse_number(self._get_comm_data(tr_code, record_name, index, "거래량")),
                "trading_value": None,
                "source": TR_MINUTE,
                "fetched_at": fetched_at,
            })

        return bars

    def _should_continue(self, job, bars, prev_next):
        if str(prev_next) != "2":
            return False

        if not bars:
            return False

        oldest_bar_date = min(bar["bar_time"][:8] for bar in bars if bar.get("bar_time"))
        return oldest_bar_date > job.from_date

    def _get_repeat_count(self, tr_code, record_name):
        return int(self.ocx.dynamicCall(
            "GetRepeatCnt(QString, QString)",
            tr_code,
            record_name,
        ))

    def _get_comm_data(self, tr_code, record_name, index, item_name):
        return self.ocx.dynamicCall(
            "GetCommData(QString, QString, int, QString)",
            tr_code,
            record_name,
            index,
            item_name,
        ).strip()

    def _parse_number(self, value):
        if value is None:
            return None

        cleaned = value.strip().replace(",", "").replace("+", "").replace("-", "")

        if cleaned == "":
            return None

        try:
            return abs(int(cleaned))
        except ValueError:
            try:
                return abs(float(cleaned))
            except ValueError:
                return None

    def _is_valid_bar_time(self, value):
        if not value:
            return False
        return value[:8].isdigit()

    def finish(self):
        self.store.close()
        QApplication.instance().quit()

    def _print_plan(self):
        estimated_first_page_requests = len(self.jobs)
        estimated_cap_requests = min(
            estimated_first_page_requests * self.max_pages,
            self.max_requests,
        )
        print("Backfill plan jobs:", len(self.jobs))
        print("Backfill plan first-page TR requests:", estimated_first_page_requests)
        print("Backfill max pages per job:", self.max_pages)
        print("Backfill max TR requests per run:", self.max_requests)
        print("Backfill estimated TR cap:", estimated_cap_requests)
        print("Backfill request delay ms:", self.request_delay_ms)


def parse_codes(raw_codes):
    """Parse comma-separated codes or fall back to WATCH_CODES."""
    if not raw_codes:
        return list(WATCH_CODES.keys())

    return [
        code.strip()
        for code in raw_codes.split(",")
        if code.strip()
    ]


def parse_intervals(raw_intervals):
    """Parse comma-separated minute intervals."""
    intervals = []
    for raw_interval in raw_intervals.split(","):
        raw_interval = raw_interval.strip()
        if not raw_interval:
            continue
        intervals.append(int(raw_interval))
    return intervals


def print_backfill_plan(codes, daily, minute, minute_intervals, max_pages, max_requests, request_delay_ms):
    """Print the conservative TR request plan without creating a Kiwoom session."""
    job_count = 0
    if daily:
        job_count += len(codes)
    if minute:
        job_count += len(codes) * len(minute_intervals)

    estimated_cap_requests = min(job_count * max_pages, max_requests)
    print("Backfill plan jobs:", job_count)
    print("Backfill plan first-page TR requests:", job_count)
    print("Backfill max pages per job:", max_pages)
    print("Backfill max TR requests per run:", max_requests)
    print("Backfill estimated TR cap:", estimated_cap_requests)
    print("Backfill request delay ms:", request_delay_ms)


def main():
    parser = argparse.ArgumentParser(description="Backfill Kiwoom daily/minute OHLCV bars into SQLite.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB path")
    parser.add_argument("--codes", help="Comma-separated stock codes. Defaults to config.WATCH_CODES.")
    parser.add_argument("--daily", action="store_true", help="Fetch daily bars through opt10081")
    parser.add_argument("--minute", action="store_true", help="Fetch minute bars through opt10080")
    parser.add_argument("--days", type=int, default=BACKFILL_DAILY_DAYS, help="Daily bar lookback calendar days")
    parser.add_argument("--minute-days", type=int, default=BACKFILL_MINUTE_DAYS, help="Minute bar lookback calendar days")
    parser.add_argument("--minute-intervals", default=BACKFILL_MINUTE_INTERVALS, help="Comma-separated minute intervals")
    parser.add_argument("--adjusted-price-type", default="1", help="Kiwoom adjusted price flag")
    parser.add_argument("--request-delay-ms", type=int, default=BACKFILL_REQUEST_DELAY_MS, help="Delay between TR requests")
    parser.add_argument("--max-pages", type=int, default=BACKFILL_MAX_PAGES_PER_JOB, help="Safety cap per job")
    parser.add_argument("--max-requests", type=int, default=BACKFILL_MAX_TR_REQUESTS_PER_RUN, help="Safety cap for total TR requests in one run")
    parser.add_argument("--plan-only", action="store_true", help="Print the TR plan without logging in or requesting data")
    args = parser.parse_args()
    setup_runtime_logging("historical_backfill")

    if not args.daily and not args.minute:
        args.daily = True
        args.minute = True

    codes = parse_codes(args.codes)
    minute_intervals = parse_intervals(args.minute_intervals)

    if args.plan_only:
        print_backfill_plan(
            codes=codes,
            daily=args.daily,
            minute=args.minute,
            minute_intervals=minute_intervals,
            max_pages=args.max_pages,
            max_requests=args.max_requests,
            request_delay_ms=args.request_delay_ms,
        )
        return

    app = QApplication(sys.argv)
    runner = HistoricalBackfillApp(
        db_path=args.db,
        codes=codes,
        daily=args.daily,
        minute=args.minute,
        days=args.days,
        minute_days=args.minute_days,
        minute_intervals=minute_intervals,
        adjusted_price_type=args.adjusted_price_type,
        request_delay_ms=args.request_delay_ms,
        max_pages=args.max_pages,
        max_requests=args.max_requests,
    )
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
