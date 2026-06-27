"""PyQt dashboard for the personal Kiwoom/OpenAI analysis app.

The dashboard is intentionally read/write only for app configuration and
watchlist management. Kiwoom login and realtime collection stay in ``main.py``.
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_paths import DATA_DIR, DEFAULT_DB_PATH, ensure_app_dirs
from settings_store import SettingsStore
from ui.labels import (
    COLUMN_LABELS,
    SETTING_DESCRIPTIONS_KO,
    TABLE_CONFIG,
    TABLE_NAME_LABELS,
    TAB_LABELS,
    VALUE_LABELS_BY_COLUMN,
)
from ui.widgets import IndicatorGaugeWidget, PriceVolumeChart


WATCHLIST_FILE_PATH = os.path.join(DATA_DIR, "watchlist.json")


def save_watchlist_file(watch_codes, path=WATCHLIST_FILE_PATH):
    """Persist a visible watchlist JSON snapshot next to the runtime DB."""
    ensure_app_dirs()
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        "source": "ui_dashboard",
        "watch_codes": dict(sorted((watch_codes or {}).items())),
    }
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)
    return path


class Dashboard(QWidget):
    """Operational dashboard for analysis status, GPT output, and settings."""

    def __init__(self, db_path=DEFAULT_DB_PATH):
        super().__init__()
        self.db_path = db_path
        self.tables = {}
        self.gpt_row_ids = []
        self.context_row_ids = []
        self.refresh_running = False
        self.refresh_queue = []
        self.refresh_started_at = None
        self.raw_table_limit = 50

        self.setWindowTitle("키움 OpenAI 개인 분석 대시보드")
        self.resize(1500, 900)

        self.status_label = QLabel("")
        self.db_label = QLabel("DB: {}".format(self.db_path))
        self.auto_refresh_checkbox = QCheckBox("자동 새로고침")
        self.auto_refresh_checkbox.setChecked(True)

        self.refresh_button = QPushButton("전체 새로고침")
        self.refresh_button.clicked.connect(self.refresh_all)

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.refresh_button)
        top_bar.addWidget(self.auto_refresh_checkbox)
        top_bar.addStretch()
        top_bar.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self._build_overview_tab()
        self._build_chart_tab()
        self._build_operations_tab()
        self._build_gpt_tab()
        self._build_context_tab()
        self._build_raw_table_tabs()
        self._build_settings_tab()
        self._build_watchlist_tab()

        layout = QVBoxLayout()
        layout.addWidget(self.db_label)
        layout.addLayout(top_bar)
        layout.addWidget(self.tabs)
        self.setLayout(layout)

        self.timer = QTimer()
        self.timer.timeout.connect(self._auto_refresh)
        self.timer.start(5000)

        self.refresh_all()

    def _build_overview_tab(self):
        self.overview_tab = QWidget()
        main_layout = QVBoxLayout()

        self.metric_labels = {}
        metrics_box = QGroupBox("DB 상태")
        metrics_layout = QGridLayout()
        metric_names = [
            "ticks",
            "analysis_results",
            "event_logs",
            "gpt_call_logs",
            "signal_logs",
            "notification_logs",
            "historical_bars",
            "market_context_snapshots",
        ]

        for idx, name in enumerate(metric_names):
            label_title = QLabel(TABLE_NAME_LABELS.get(name, name))
            label_value = QLabel("0")
            label_value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.metric_labels[name] = label_value
            metrics_layout.addWidget(label_title, idx // 4, (idx % 4) * 2)
            metrics_layout.addWidget(label_value, idx // 4, (idx % 4) * 2 + 1)

        metrics_box.setLayout(metrics_layout)

        self.latest_table = QTableWidget()
        self.latest_table.setSortingEnabled(False)
        self._setup_table(self.latest_table)

        self.recent_events_table = QTableWidget()
        self.recent_events_table.setSortingEnabled(False)
        self._setup_table(self.recent_events_table)

        self.recent_signals_table = QTableWidget()
        self.recent_signals_table.setSortingEnabled(False)
        self._setup_table(self.recent_signals_table)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._wrap_table("종목별 최신 상태", self.latest_table))
        splitter.addWidget(self._wrap_table("최근 이벤트", self.recent_events_table))
        splitter.addWidget(self._wrap_table("최근 신호", self.recent_signals_table))
        splitter.setSizes([360, 240, 220])

        main_layout.addWidget(metrics_box)
        main_layout.addWidget(splitter)
        self.overview_tab.setLayout(main_layout)
        self.tabs.addTab(self.overview_tab, "개요")

    def _build_operations_tab(self):
        self.operations_tab = QWidget()
        layout = QVBoxLayout()

        self.operations_summary_table = QTableWidget()
        self.operations_summary_table.setSortingEnabled(False)
        self._setup_table(self.operations_summary_table)

        self.gpt_usage_table = QTableWidget()
        self.gpt_usage_table.setSortingEnabled(False)
        self._setup_table(self.gpt_usage_table)

        self.latest_context_table = QTableWidget()
        self.latest_context_table.setSortingEnabled(False)
        self._setup_table(self.latest_context_table)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._wrap_table("운영 요약", self.operations_summary_table))
        splitter.addWidget(self._wrap_table("최근 GPT 호출", self.gpt_usage_table))
        splitter.addWidget(self._wrap_table("섹션별 최신 시장 컨텍스트", self.latest_context_table))
        splitter.setSizes([220, 260, 360])

        layout.addWidget(splitter)
        self.operations_tab.setLayout(layout)
        self.tabs.addTab(self.operations_tab, "운영")

    def _build_chart_tab(self):
        self.chart_tab = QWidget()
        layout = QVBoxLayout()

        control_row = QHBoxLayout()
        control_row.addWidget(QLabel("종목"))
        self.chart_symbol_combo = QComboBox()
        self.chart_symbol_combo.currentIndexChanged.connect(self.refresh_chart_view)
        self.refresh_chart_button = QPushButton("차트 새로고침")
        self.refresh_chart_button.clicked.connect(self.refresh_chart_view)
        control_row.addWidget(self.chart_symbol_combo)
        control_row.addWidget(self.refresh_chart_button)
        control_row.addStretch()

        self.price_chart = PriceVolumeChart()
        self.indicator_gauge = IndicatorGaugeWidget()
        self.indicator_table = QTableWidget()
        self.indicator_table.setSortingEnabled(False)
        self._setup_table(self.indicator_table)

        detail_splitter = QSplitter(Qt.Horizontal)
        detail_splitter.addWidget(self._wrap_widget("지표 시각화", self.indicator_gauge))
        detail_splitter.addWidget(self._wrap_table("최신 지표값", self.indicator_table))
        detail_splitter.setSizes([700, 800])

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._wrap_widget("최근 가격/거래량", self.price_chart))
        splitter.addWidget(detail_splitter)
        splitter.setSizes([470, 330])

        layout.addLayout(control_row)
        layout.addWidget(splitter)
        self.chart_tab.setLayout(layout)
        self.tabs.addTab(self.chart_tab, "차트")

    def _build_gpt_tab(self):
        self.gpt_tab = QWidget()
        layout = QVBoxLayout()

        self.gpt_table = QTableWidget()
        self.gpt_table.setSortingEnabled(False)
        self.gpt_table.currentCellChanged.connect(self.show_selected_gpt_result)
        self._setup_table(self.gpt_table)

        self.gpt_text = QPlainTextEdit()
        self.gpt_text.setReadOnly(True)
        self.gpt_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.gpt_table)
        splitter.addWidget(self.gpt_text)
        splitter.setSizes([620, 880])

        layout.addWidget(splitter)
        self.gpt_tab.setLayout(layout)
        self.tabs.addTab(self.gpt_tab, "GPT 결과")

    def _build_context_tab(self):
        self.context_tab = QWidget()
        layout = QVBoxLayout()

        self.context_table = QTableWidget()
        self.context_table.setSortingEnabled(False)
        self.context_table.currentCellChanged.connect(self.show_selected_context_payload)
        self._setup_table(self.context_table)

        self.context_text = QPlainTextEdit()
        self.context_text.setReadOnly(True)
        self.context_text.setLineWrapMode(QPlainTextEdit.WidgetWidth)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.context_table)
        splitter.addWidget(self.context_text)
        splitter.setSizes([760, 740])

        layout.addWidget(splitter)
        self.context_tab.setLayout(layout)
        self.tabs.addTab(self.context_tab, "시장 컨텍스트")

    def _build_raw_table_tabs(self):
        for label in TABLE_CONFIG:
            table = QTableWidget()
            table.setSortingEnabled(False)
            self._setup_table(table)
            self.tabs.addTab(table, TAB_LABELS.get(label, label))
            self.tables[label] = table

    def _build_settings_tab(self):
        self.settings_tab = QWidget()
        layout = QVBoxLayout()

        button_row = QHBoxLayout()
        self.refresh_settings_button = QPushButton("설정 새로고침")
        self.refresh_settings_button.clicked.connect(self.refresh_settings)
        self.save_settings_button = QPushButton("설정 저장")
        self.save_settings_button.clicked.connect(self.save_settings)
        button_row.addWidget(self.refresh_settings_button)
        button_row.addWidget(self.save_settings_button)
        button_row.addStretch()

        self.settings_table = QTableWidget()
        self.settings_table.setSortingEnabled(False)
        self._setup_table(self.settings_table)

        layout.addLayout(button_row)
        layout.addWidget(self.settings_table)
        self.settings_tab.setLayout(layout)
        self.tabs.addTab(self.settings_tab, "설정")

    def _build_watchlist_tab(self):
        self.watchlist_tab = QWidget()
        layout = QVBoxLayout()

        editor_box = QGroupBox("종목 입력")
        editor_layout = QGridLayout()
        self.watch_code_input = QLineEdit()
        self.watch_code_input.setPlaceholderText("예: 005930")
        self.watch_name_input = QLineEdit()
        self.watch_name_input.setPlaceholderText("예: Samsung Electronics")
        self.watchlist_status_label = QLabel("")

        self.apply_watch_code_button = QPushButton("입력값 추가/수정")
        self.apply_watch_code_button.clicked.connect(self.apply_watch_code_from_inputs)
        self.clear_watch_code_button = QPushButton("입력 초기화")
        self.clear_watch_code_button.clicked.connect(self.clear_watch_code_inputs)

        editor_layout.addWidget(QLabel("종목코드"), 0, 0)
        editor_layout.addWidget(self.watch_code_input, 0, 1)
        editor_layout.addWidget(QLabel("종목명"), 0, 2)
        editor_layout.addWidget(self.watch_name_input, 0, 3)
        editor_layout.addWidget(self.apply_watch_code_button, 0, 4)
        editor_layout.addWidget(self.clear_watch_code_button, 0, 5)
        editor_layout.addWidget(self.watchlist_status_label, 1, 0, 1, 6)
        editor_box.setLayout(editor_layout)

        button_row = QHBoxLayout()
        self.refresh_watchlist_button = QPushButton("종목 새로고침")
        self.refresh_watchlist_button.clicked.connect(self.refresh_watchlist)
        self.add_watch_code_button = QPushButton("빈 행 추가")
        self.add_watch_code_button.clicked.connect(self.add_watch_code_row)
        self.delete_watch_code_button = QPushButton("선택 삭제")
        self.delete_watch_code_button.clicked.connect(self.delete_selected_watch_codes)
        self.save_watchlist_button = QPushButton("종목 저장")
        self.save_watchlist_button.clicked.connect(self.save_watchlist)

        button_row.addWidget(self.refresh_watchlist_button)
        button_row.addWidget(self.add_watch_code_button)
        button_row.addWidget(self.delete_watch_code_button)
        button_row.addWidget(self.save_watchlist_button)
        button_row.addStretch()

        self.watchlist_table = QTableWidget()
        self.watchlist_table.setSortingEnabled(False)
        self.watchlist_table.currentCellChanged.connect(self.load_selected_watch_code)
        self._setup_table(self.watchlist_table)

        hint = QLabel("저장한 관심 종목 변경사항은 main.py 실행 중 다음 분석 사이클부터 적용됩니다.")

        layout.addWidget(editor_box)
        layout.addLayout(button_row)
        layout.addWidget(hint)
        layout.addWidget(self.watchlist_table)
        self.watchlist_tab.setLayout(layout)
        self.tabs.addTab(self.watchlist_tab, "관심종목")

    def _wrap_table(self, title, table):
        return self._wrap_widget(title, table)

    def _wrap_widget(self, title, widget):
        box = QGroupBox(title)
        layout = QVBoxLayout()
        layout.addWidget(widget)
        box.setLayout(layout)
        return box

    def _setup_table(self, table):
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    def _auto_refresh(self):
        if self.auto_refresh_checkbox.isChecked():
            self.refresh_live_sections()

    def refresh_all(self):
        """Refresh all dashboard sections without locking the UI in one long call."""
        self._start_refresh_queue([
            self.refresh_overview,
            self.refresh_chart,
            self.refresh_operations,
            self.refresh_gpt_results,
            self.refresh_context_snapshots,
            self.refresh_raw_tables,
            self.refresh_settings,
            self.refresh_watchlist,
        ], label="full")

    def refresh_live_sections(self):
        """Refresh operational sections on the timer; skip heavy maintenance tabs."""
        self._start_refresh_queue([
            self.refresh_overview,
            self.refresh_chart,
            self.refresh_operations,
            self.refresh_gpt_results,
            self.refresh_context_snapshots,
        ], label="live")

    def _start_refresh_queue(self, callbacks, label):
        if self.refresh_running:
            self.status_label.setText("Refresh already running")
            return
        self.refresh_running = True
        self.refresh_started_at = datetime.now()
        self.refresh_queue = list(callbacks)
        self.refresh_button.setEnabled(False)
        self.status_label.setText("Refreshing {} sections...".format(label))
        QTimer.singleShot(0, self._run_next_refresh_step)

    def _run_next_refresh_step(self):
        if not self.refresh_queue:
            elapsed_ms = int((datetime.now() - self.refresh_started_at).total_seconds() * 1000) if self.refresh_started_at else 0
            self.refresh_running = False
            self.refresh_button.setEnabled(True)
            self.status_label.setText("Last refresh: {} ({} ms)".format(self._now_text(), elapsed_ms))
            return

        callback = self.refresh_queue.pop(0)
        try:
            callback()
        except Exception as exc:
            self.status_label.setText("Refresh failed in {}: {}".format(getattr(callback, "__name__", "step"), exc))
            self.refresh_queue = []
            self.refresh_running = False
            self.refresh_button.setEnabled(True)
            return
        QTimer.singleShot(1, self._run_next_refresh_step)

    def refresh_overview(self):
        """Refresh dashboard metrics, latest status, events, and signals."""
        if not os.path.exists(self.db_path):
            self.status_label.setText("DB 파일 없음")
            return

        conn = self._connect()
        try:
            self._refresh_metrics(conn)
            self._refresh_latest_status(conn)
            self._refresh_recent_events(conn)
            self._refresh_recent_signals(conn)
            self.status_label.setText("마지막 새로고침: {}".format(self._now_text()))
        finally:
            conn.close()

    def _refresh_metrics(self, conn):
        for table_name, label in self.metric_labels.items():
            try:
                count = conn.execute("SELECT COUNT(*) FROM {}".format(table_name)).fetchone()[0]
            except sqlite3.Error:
                count = 0
            label.setText(str(count))

    def _refresh_latest_status(self, conn):
        rows = conn.execute("""
            SELECT
                a.analyzed_at,
                a.code,
                a.name,
                a.current_price,
                a.rsi14,
                a.ma5,
                a.ma20,
                a.volume_ratio_20,
                a.vwap_distance_pct,
                a.box_position,
                (
                    SELECT GROUP_CONCAT(event_type, ', ')
                    FROM event_logs e
                    WHERE e.code = a.code
                      AND e.detected_at = (
                          SELECT MAX(detected_at)
                          FROM event_logs
                          WHERE code = a.code
                      )
                ) AS latest_events,
                (
                    SELECT action_hint
                    FROM signal_logs s
                    WHERE s.code = a.code
                    ORDER BY s.detected_at DESC
                    LIMIT 1
                ) AS latest_signal
            FROM analysis_results a
            JOIN (
                SELECT code, MAX(id) AS latest_id
                FROM analysis_results
                GROUP BY code
            ) latest
              ON latest.latest_id = a.id
            ORDER BY a.analyzed_at DESC
        """).fetchall()
        self.fill_table(self.latest_table, rows)

    def _refresh_recent_events(self, conn):
        rows = conn.execute("""
            SELECT detected_at, code, name, event_type, timeframe, value, gpt_requested, skip_reason
            FROM event_logs
            ORDER BY id DESC
            LIMIT 30
        """).fetchall()
        self.fill_table(self.recent_events_table, rows)

    def _refresh_recent_signals(self, conn):
        rows = conn.execute("""
            SELECT
                detected_at, code, name, action_hint, confidence_score, risk_level,
                current_price, stop_loss, target_1, target_2
            FROM signal_logs
            ORDER BY id DESC
            LIMIT 30
        """).fetchall()
        self.fill_table(self.recent_signals_table, rows)

    def refresh_chart(self):
        """Reload selectable symbols and redraw the chart tab."""
        if not os.path.exists(self.db_path):
            return

        conn = self._connect()
        try:
            self._refresh_chart_symbols(conn)
            self._refresh_chart_view(conn)
        finally:
            conn.close()

    def refresh_chart_view(self, *args):
        """Redraw chart tab for the currently selected symbol."""
        if not os.path.exists(self.db_path):
            return

        conn = self._connect()
        try:
            self._refresh_chart_view(conn)
        finally:
            conn.close()

    def _refresh_chart_symbols(self, conn):
        selected_code = self.chart_symbol_combo.currentData()
        symbols = []

        try:
            settings_store = SettingsStore(conn=conn)
            watch_codes = settings_store.get("WATCH_CODES", {})
        except Exception:
            watch_codes = {}

        for code, name in sorted((watch_codes or {}).items()):
            symbols.append((str(code), str(name)))

        try:
            rows = conn.execute("""
                SELECT code, COALESCE(MAX(name), code) AS name
                FROM analysis_results
                GROUP BY code
                ORDER BY code ASC
            """).fetchall()
            existing = set(code for code, name in symbols)
            for row in rows:
                if row["code"] not in existing:
                    symbols.append((row["code"], row["name"] or row["code"]))
        except sqlite3.Error:
            pass

        self.chart_symbol_combo.blockSignals(True)
        self.chart_symbol_combo.clear()
        for code, name in symbols:
            self.chart_symbol_combo.addItem("{}  {}".format(code, name), code)

        if selected_code:
            index = self.chart_symbol_combo.findData(selected_code)
            if index >= 0:
                self.chart_symbol_combo.setCurrentIndex(index)

        self.chart_symbol_combo.blockSignals(False)

    def _refresh_chart_view(self, conn):
        code = self.chart_symbol_combo.currentData()
        if not code:
            self.price_chart.set_data([])
            self.indicator_gauge.set_indicators({})
            self._fill_key_value_table(self.indicator_table, [])
            return

        latest = self._fetch_latest_indicator_row(conn, code)
        chart_rows = self._fetch_chart_rows(conn, code)
        name = latest["name"] if latest and latest["name"] else self._selected_chart_name()

        self.price_chart.set_data(chart_rows, code=code, name=name)
        self.indicator_gauge.set_indicators(dict(latest) if latest else {})
        self._fill_key_value_table(self.indicator_table, self._indicator_rows_for_table(latest))

    def _fetch_chart_rows(self, conn, code):
        try:
            rows = conn.execute("""
                SELECT received_at, price, tick_volume
                FROM ticks
                WHERE code = ?
                ORDER BY received_at DESC
                LIMIT 300
            """, (code,)).fetchall()
            if rows:
                return list(reversed(rows))
        except sqlite3.Error:
            pass

        try:
            rows = conn.execute("""
                SELECT bar_time AS received_at, close AS price, volume AS tick_volume
                FROM historical_bars
                WHERE code = ?
                ORDER BY bar_time DESC
                LIMIT 300
            """, (code,)).fetchall()
            return list(reversed(rows))
        except sqlite3.Error:
            return []

    def _fetch_latest_indicator_row(self, conn, code):
        try:
            return conn.execute("""
                SELECT
                    analyzed_at, code, name, current_price, rsi14, ma5, ma20, ma60,
                    volume_ratio_5, volume_ratio_20, vwap, vwap_distance_pct,
                    box_high, box_low, box_position, day_open, day_high, day_low,
                    strength
                FROM analysis_results
                WHERE code = ?
                ORDER BY id DESC
                LIMIT 1
            """, (code,)).fetchone()
        except sqlite3.Error:
            return None

    def _indicator_rows_for_table(self, row):
        if not row:
            return []

        return [
            ("종목", "{} {}".format(row["code"], row["name"] or "")),
            ("분석시각", row["analyzed_at"]),
            ("현재가", self._format_number(row["current_price"])),
            ("RSI14", row["rsi14"]),
            ("5이평", self._format_number(row["ma5"])),
            ("20이평", self._format_number(row["ma20"])),
            ("60이평", self._format_number(row["ma60"])),
            ("20봉 거래량 배율", row["volume_ratio_20"]),
            ("VWAP", self._format_number(row["vwap"])),
            ("VWAP 이격률", row["vwap_distance_pct"]),
            ("박스 위치", row["box_position"]),
            ("박스 하단", self._format_number(row["box_low"])),
            ("박스 상단", self._format_number(row["box_high"])),
            ("체결강도", row["strength"]),
        ]

    def _selected_chart_name(self):
        text = self.chart_symbol_combo.currentText()
        parts = text.split(None, 1)
        return parts[1] if len(parts) > 1 else ""

    def refresh_operations(self):
        """Refresh high-level operating status tables."""
        if not os.path.exists(self.db_path):
            return

        conn = self._connect()
        try:
            self._refresh_operations_summary(conn)
            self._refresh_gpt_usage_table(conn)
            self._refresh_latest_context_table(conn)
        finally:
            conn.close()

    def _refresh_operations_summary(self, conn):
        settings_store = SettingsStore(conn=conn)
        settings = settings_store.get_runtime_settings()

        watch_codes = settings.get("WATCH_CODES", {})
        buy_fee = self._to_float(settings.get("TRADE_BUY_FEE_PCT")) or 0.0
        sell_fee = self._to_float(settings.get("TRADE_SELL_FEE_PCT")) or 0.0
        sell_tax = self._to_float(settings.get("TRADE_SELL_TAX_PCT")) or 0.0
        slippage = self._to_float(settings.get("TRADE_SLIPPAGE_PCT")) or 0.0
        round_trip_cost = round(buy_fee + sell_fee + sell_tax + (slippage * 2), 4)

        rows = [
            ("DB 경로", self.db_path),
            ("관심 종목", "{} ({})".format(len(watch_codes), ", ".join(sorted(watch_codes.keys())))),
            ("분석 주기(초)", settings.get("GPT_ANALYSIS_INTERVAL_SEC")),
            ("GPT 쿨다운(초)", settings.get("GPT_COOLDOWN_SEC")),
            ("이벤트 필터", self._format_bool(settings.get("ENABLE_EVENT_FILTER"))),
            ("알림 채널", settings.get("NOTIFICATION_CHANNELS")),
            ("TR 갱신 주기(초)", settings.get("MARKET_CONTEXT_TR_REQUEST_INTERVAL_SEC")),
            ("TR 배치 최대 요청", settings.get("MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH")),
            ("GPT 입력 압축", self._format_bool(settings.get("ENABLE_GPT_INPUT_COMPRESSION"))),
            ("왕복 거래비용(%)", round_trip_cost),
            ("최근 틱", self._fetch_scalar(conn, "SELECT MAX(received_at) FROM ticks")),
            ("최근 분석", self._fetch_scalar(conn, "SELECT MAX(analyzed_at) FROM analysis_results")),
            ("최근 GPT 호출", self._fetch_scalar(conn, "SELECT MAX(started_at) FROM gpt_call_logs")),
            ("최근 알림", self._fetch_scalar(conn, "SELECT MAX(sent_at) FROM notification_logs")),
            ("최근 컨텍스트", self._fetch_scalar(conn, "SELECT MAX(collected_at) FROM market_context_snapshots")),
        ]
        shared = self._shared_context_status()
        rows.extend([
            ("공유 허브 DB", shared.get("db_path")),
            ("공유 허브 상태", shared.get("status")),
            ("공유 Kiwoom 최신", shared.get("latest_kiwoom_context_time") or "none"),
            ("공유 Toss 최신", shared.get("latest_toss_context_time") or "none"),
            ("공유 관계 최신", shared.get("latest_relationship_context_time") or "none"),
            ("공유 누락 섹션", ", ".join(shared.get("missing_sections") or []) or "none"),
        ])

        self._fill_key_value_table(self.operations_summary_table, rows)

    def _shared_context_status(self):
        db_path = os.environ.get(
            "SHARED_CONTEXT_DB_PATH",
            r"C:\Users\lmhk2\Documents\New project\shared_market_context\shared_context.db",
        )
        status = {
            "db_path": db_path,
            "status": "missing",
            "latest_kiwoom_context_time": None,
            "latest_toss_context_time": None,
            "latest_relationship_context_time": None,
            "missing_sections": [],
        }
        if not db_path or not os.path.exists(db_path):
            status["missing_sections"] = ["shared_context.db"]
            return status
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                quick = conn.execute("PRAGMA quick_check").fetchone()
                if not quick or quick[0] != "ok":
                    status["status"] = "failed"
                    return status
                if not self._shared_has_table(conn, "shared_context_snapshots"):
                    status["status"] = "missing_table"
                    status["missing_sections"] = ["shared_context_snapshots"]
                    return status
                status["latest_kiwoom_context_time"] = self._shared_latest(conn, "source = 'kiwoom'")
                status["latest_toss_context_time"] = self._shared_latest(conn, "source = 'toss'")
                status["latest_relationship_context_time"] = self._shared_latest(conn, "section = 'relationship_metrics'")
                for name, value in [
                    ("kiwoom", status["latest_kiwoom_context_time"]),
                    ("toss", status["latest_toss_context_time"]),
                    ("relationship", status["latest_relationship_context_time"]),
                ]:
                    if not value:
                        status["missing_sections"].append(name)
                status["status"] = "ok" if not status["missing_sections"] else "partial"
                return status
            finally:
                conn.close()
        except Exception as exc:
            status["status"] = "failed"
            status["missing_sections"] = [str(exc)]
            return status

    def _shared_has_table(self, conn, table):
        return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None

    def _shared_latest(self, conn, where):
        row = conn.execute("SELECT MAX(collected_at) AS latest FROM shared_context_snapshots WHERE {}".format(where)).fetchone()
        return row["latest"] if row else None

    def _refresh_gpt_usage_table(self, conn):
        try:
            rows = conn.execute("""
                SELECT
                    id,
                    started_at,
                    status,
                    requested_count,
                    codes,
                    model,
                    duration_ms,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    prompt_chars,
                    payload_original_chars,
                    payload_compressed_chars,
                    payload_compression_ratio
                FROM gpt_call_logs
                ORDER BY id DESC
                LIMIT 30
            """).fetchall()
        except sqlite3.Error:
            rows = conn.execute("""
                SELECT
                    id,
                    started_at,
                    status,
                    requested_count,
                    codes,
                    model,
                    duration_ms,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens
                FROM gpt_call_logs
                ORDER BY id DESC
                LIMIT 30
            """).fetchall()
        self.fill_table(self.gpt_usage_table, rows)

    def _refresh_latest_context_table(self, conn):
        try:
            rows = conn.execute("""
                SELECT
                    m.collected_at,
                    m.scope,
                    COALESCE(m.code, 'GLOBAL') AS code,
                    m.section,
                    m.source,
                    m.asof,
                    m.reliability,
                    m.weight,
                    m.summary
                FROM market_context_snapshots m
                JOIN (
                    SELECT
                        scope,
                        COALESCE(code, '') AS code_key,
                        section,
                        MAX(id) AS latest_id
                    FROM market_context_snapshots
                    GROUP BY scope, COALESCE(code, ''), section
                ) latest
                  ON latest.latest_id = m.id
                ORDER BY m.collected_at DESC
            """).fetchall()
        except sqlite3.Error:
            rows = []

        self.fill_table(self.latest_context_table, rows)

    def refresh_gpt_results(self):
        """Refresh GPT analysis list and preserve selected row when possible."""
        if not os.path.exists(self.db_path):
            return

        selected_id = self._selected_gpt_id()
        conn = self._connect()
        try:
            rows = conn.execute("""
                SELECT
                    id, analyzed_at, code, name, current_price, rsi14,
                    volume_ratio_20, vwap_distance_pct, box_position,
                    SUBSTR(gpt_result, 1, 160) AS result_preview
                FROM analysis_results
                ORDER BY id DESC
                LIMIT 100
            """).fetchall()

            self.gpt_row_ids = [row["id"] for row in rows]
            self.fill_table(self.gpt_table, rows)
            self._select_gpt_id(selected_id)
        finally:
            conn.close()

    def show_selected_gpt_result(self, current_row, current_col, previous_row, previous_col):
        """Load full GPT result for the selected analysis row."""
        if current_row < 0 or current_row >= len(self.gpt_row_ids):
            self.gpt_text.clear()
            return

        analysis_id = self.gpt_row_ids[current_row]
        conn = self._connect()
        try:
            row = conn.execute("""
                SELECT analyzed_at, code, name, summary_json, market_context_json, gpt_result
                FROM analysis_results
                WHERE id = ?
            """, (analysis_id,)).fetchone()

            if not row:
                self.gpt_text.clear()
                return

            text = [
                "분석시각: {}".format(row["analyzed_at"]),
                "종목: {} ({})".format(row["name"], row["code"]),
                "",
                "========== GPT 결과 ==========",
                row["gpt_result"] or "",
                "",
                "========== 시장 컨텍스트 JSON ==========",
                row["market_context_json"] or "",
            ]
            self.gpt_text.setPlainText("\n".join(text))
        finally:
            conn.close()

    def refresh_context_snapshots(self):
        """Refresh recent market-context snapshots and preserve selection."""
        if not os.path.exists(self.db_path):
            return

        selected_id = self._selected_context_id()
        conn = self._connect()
        try:
            try:
                rows = conn.execute("""
                    SELECT
                        id,
                        collected_at,
                        scope,
                        COALESCE(code, 'GLOBAL') AS code,
                        section,
                        source,
                        asof,
                        reliability,
                        weight,
                        summary,
                        SUBSTR(payload_json, 1, 220) AS payload_preview
                    FROM market_context_snapshots
                    ORDER BY id DESC
                    LIMIT 200
                """).fetchall()
            except sqlite3.Error:
                rows = []

            self.context_row_ids = [row["id"] for row in rows]
            self.fill_table(self.context_table, rows)
            self._select_context_id(selected_id)
        finally:
            conn.close()

    def show_selected_context_payload(self, current_row, current_col, previous_row, previous_col):
        """Load full JSON payload for the selected market-context snapshot."""
        if current_row < 0 or current_row >= len(self.context_row_ids):
            self.context_text.clear()
            return

        snapshot_id = self.context_row_ids[current_row]
        conn = self._connect()
        try:
            row = conn.execute("""
                SELECT
                    id, collected_at, scope, code, section, source,
                    asof, reliability, weight, summary, payload_json
                FROM market_context_snapshots
                WHERE id = ?
            """, (snapshot_id,)).fetchone()

            if not row:
                self.context_text.clear()
                return

            text = [
                "ID: {}".format(row["id"]),
                "수집시각: {}".format(row["collected_at"]),
                "범위/종목: {}/{}".format(
                    self._display_cell_text("scope", str(row["scope"])),
                    row["code"] or "GLOBAL",
                ),
                "구분/출처: {}/{}".format(
                    self._display_cell_text("section", str(row["section"])),
                    row["source"],
                ),
                "기준시각: {}".format(row["asof"]),
                "신뢰도/가중치: {}/{}".format(row["reliability"], row["weight"]),
                "요약: {}".format(row["summary"]),
                "",
                "========== Payload JSON ==========",
                row["payload_json"] or "",
            ]
            self.context_text.setPlainText("\n".join(text))
        finally:
            conn.close()

    def refresh_raw_tables(self):
        """Reload recent rows from raw DB tables."""
        if not os.path.exists(self.db_path):
            return

        conn = self._connect()
        try:
            for label, config in TABLE_CONFIG.items():
                table_name, order_col = config
                try:
                    rows = conn.execute("""
                        SELECT *
                        FROM {}
                        ORDER BY {} DESC
                        LIMIT ?
                    """.format(table_name, order_col), (self.raw_table_limit,)).fetchall()
                except sqlite3.Error:
                    rows = []
                self.fill_table(self.tables[label], rows)
        finally:
            conn.close()

    def fill_table(self, table, rows):
        """Render SQLite rows into a QTableWidget."""
        table.setUpdatesEnabled(False)
        try:
            if not rows:
                table.setRowCount(0)
                table.setColumnCount(0)
                return

            columns = list(rows[0].keys())
            table.setColumnCount(len(columns))
            table.setHorizontalHeaderLabels([self._display_column_label(column) for column in columns])
            table.setRowCount(len(rows))

            for row_idx, row in enumerate(rows):
                for col_idx, column in enumerate(columns):
                    value = row[column]
                    text = "" if value is None else str(value)
                    text = self._display_cell_text(column, text)
                    if len(text) > 240:
                        text = text[:240] + "..."
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    table.setItem(row_idx, col_idx, item)

            table.resizeColumnsToContents()
        finally:
            table.setUpdatesEnabled(True)

    def _fill_key_value_table(self, table, rows):
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["항목", "값"])
        table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            key, value = row
            key_item = QTableWidgetItem("" if key is None else str(key))
            value_item = QTableWidgetItem("" if value is None else str(value))
            key_item.setFlags(key_item.flags() & ~Qt.ItemIsEditable)
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row_idx, 0, key_item)
            table.setItem(row_idx, 1, value_item)

        table.resizeColumnsToContents()

    def refresh_settings(self):
        """Reload runtime-editable settings from SQLite."""
        settings_store = SettingsStore(db_path=self.db_path)
        rows = settings_store.get_all()
        settings_store.close()

        columns = ["key", "value", "value_type", "description", "updated_at"]
        self.settings_table.setColumnCount(len(columns))
        self.settings_table.setHorizontalHeaderLabels([self._display_column_label(column) for column in columns])
        self.settings_table.setRowCount(len(rows))

        for row_idx, row in enumerate(rows):
            for col_idx, column in enumerate(columns):
                value = row[column]
                if column == "description":
                    value = SETTING_DESCRIPTIONS_KO.get(row["key"], value)
                item = QTableWidgetItem("" if value is None else str(value))

                if column != "value":
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                self.settings_table.setItem(row_idx, col_idx, item)

        self.settings_table.resizeColumnsToContents()

    def save_settings(self):
        """Save edited setting values back to SQLite."""
        settings_store = SettingsStore(db_path=self.db_path)

        try:
            for row_idx in range(self.settings_table.rowCount()):
                key_item = self.settings_table.item(row_idx, 0)
                value_item = self.settings_table.item(row_idx, 1)

                if not key_item or not value_item:
                    continue

                settings_store.update_setting(
                    key=key_item.text(),
                    value=value_item.text()
                )

            QMessageBox.information(self, "설정", "설정을 저장했습니다.")
            self.refresh_settings()
        except Exception as exc:
            QMessageBox.critical(self, "설정 오류", str(exc))
        finally:
            settings_store.close()

    def refresh_watchlist(self):
        """Reload watch codes into an editable table."""
        settings_store = SettingsStore(db_path=self.db_path)
        watch_codes = settings_store.get("WATCH_CODES", {})
        settings_store.close()

        self.watchlist_table.setColumnCount(2)
        self.watchlist_table.setHorizontalHeaderLabels(["종목코드", "종목명"])
        self.watchlist_table.setRowCount(len(watch_codes))

        for row_idx, item in enumerate(watch_codes.items()):
            code, name = item
            self.watchlist_table.setItem(row_idx, 0, QTableWidgetItem(str(code)))
            self.watchlist_table.setItem(row_idx, 1, QTableWidgetItem(str(name)))

        self.watchlist_table.resizeColumnsToContents()
        self.watchlist_status_label.setText("{}개 종목을 불러왔습니다.".format(len(watch_codes)))

    def apply_watch_code_from_inputs(self):
        """Add a new watch code or update an existing code from the input fields."""
        code = self.watch_code_input.text().strip()
        name = self.watch_name_input.text().strip()

        if not code:
            self.watchlist_status_label.setText("종목코드를 입력하세요.")
            return

        if not self._is_reasonable_symbol_code(code):
            self.watchlist_status_label.setText("종목코드는 보통 6자리 숫자입니다. 해외/특수코드는 저장 전 확인하세요.")

        row_idx = self._find_watch_code_row(code)
        if row_idx < 0:
            row_idx = self.watchlist_table.rowCount()
            self.watchlist_table.insertRow(row_idx)

        self.watchlist_table.setItem(row_idx, 0, QTableWidgetItem(code))
        self.watchlist_table.setItem(row_idx, 1, QTableWidgetItem(name or code))
        self.watchlist_table.selectRow(row_idx)
        self.watchlist_table.resizeColumnsToContents()
        self.watchlist_status_label.setText("{} 종목을 편집 목록에 반영했습니다. 저장 버튼을 눌러 DB에 반영하세요.".format(code))

    def clear_watch_code_inputs(self):
        self.watch_code_input.clear()
        self.watch_name_input.clear()
        self.watchlist_table.clearSelection()
        self.watchlist_status_label.setText("입력값을 초기화했습니다.")

    def load_selected_watch_code(self, current_row, current_col, previous_row, previous_col):
        if current_row < 0:
            return

        code_item = self.watchlist_table.item(current_row, 0)
        name_item = self.watchlist_table.item(current_row, 1)
        self.watch_code_input.setText(code_item.text() if code_item else "")
        self.watch_name_input.setText(name_item.text() if name_item else "")
        if code_item:
            self.watchlist_status_label.setText("{} 선택됨. 입력값 수정 후 추가/수정을 누르세요.".format(code_item.text()))

    def add_watch_code_row(self):
        """Append an empty editable watch-code row."""
        row_idx = self.watchlist_table.rowCount()
        self.watchlist_table.insertRow(row_idx)
        self.watchlist_table.setItem(row_idx, 0, QTableWidgetItem(""))
        self.watchlist_table.setItem(row_idx, 1, QTableWidgetItem(""))
        self.watchlist_table.selectRow(row_idx)
        self.watchlist_status_label.setText("빈 행을 추가했습니다.")

    def delete_selected_watch_codes(self):
        """Delete selected watch-code rows from the UI table."""
        selected_rows = sorted(
            set(index.row() for index in self.watchlist_table.selectedIndexes()),
            reverse=True
        )

        for row_idx in selected_rows:
            self.watchlist_table.removeRow(row_idx)

        self.watchlist_status_label.setText("{}개 행을 삭제했습니다. 저장 버튼을 눌러 DB에 반영하세요.".format(len(selected_rows)))

    def save_watchlist(self):
        """Save the watchlist table back to the WATCH_CODES setting."""
        watch_codes = {}

        try:
            for row_idx in range(self.watchlist_table.rowCount()):
                code_item = self.watchlist_table.item(row_idx, 0)
                name_item = self.watchlist_table.item(row_idx, 1)

                code = code_item.text().strip() if code_item else ""
                name = name_item.text().strip() if name_item else ""

                if not code and not name:
                    continue

                if not code:
                    raise ValueError("{}행에 종목명은 있지만 종목코드가 없습니다.".format(row_idx + 1))

                if code in watch_codes:
                    raise ValueError("중복 종목코드: {}".format(code))

                watch_codes[code] = name or code

            settings_store = SettingsStore(db_path=self.db_path)
            try:
                settings_store.update_setting("WATCH_CODES", watch_codes)
            finally:
                settings_store.close()
            watchlist_path = save_watchlist_file(watch_codes)

            QMessageBox.information(
                self,
                "관심종목",
                "관심종목을 저장했습니다.\n{}\nmain.py 실행 중 다음 분석 사이클부터 적용됩니다.".format(
                    watchlist_path
                )
            )
            self.watchlist_status_label.setText(
                "{}개 관심종목을 저장했습니다. 파일: {}".format(len(watch_codes), watchlist_path)
            )
            self.refresh_watchlist()
            self.refresh_settings()
        except Exception as exc:
            QMessageBox.critical(self, "관심종목 오류", str(exc))
            self.watchlist_status_label.setText("저장 실패: {}".format(exc))

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _selected_gpt_id(self):
        row = self.gpt_table.currentRow()
        if row < 0 or row >= len(self.gpt_row_ids):
            return None
        return self.gpt_row_ids[row]

    def _select_gpt_id(self, analysis_id):
        if analysis_id in self.gpt_row_ids:
            self.gpt_table.selectRow(self.gpt_row_ids.index(analysis_id))
        elif self.gpt_row_ids:
            self.gpt_table.selectRow(0)

    def _selected_context_id(self):
        row = self.context_table.currentRow()
        if row < 0 or row >= len(self.context_row_ids):
            return None
        return self.context_row_ids[row]

    def _select_context_id(self, snapshot_id):
        if snapshot_id in self.context_row_ids:
            self.context_table.selectRow(self.context_row_ids.index(snapshot_id))
        elif self.context_row_ids:
            self.context_table.selectRow(0)

    def _fetch_scalar(self, conn, sql, params=None):
        try:
            row = conn.execute(sql, params or ()).fetchone()
        except sqlite3.Error:
            return None
        if not row:
            return None
        return row[0]

    def _find_watch_code_row(self, code):
        for row_idx in range(self.watchlist_table.rowCount()):
            item = self.watchlist_table.item(row_idx, 0)
            if item and item.text().strip() == code:
                return row_idx
        return -1

    def _is_reasonable_symbol_code(self, code):
        if code.isdigit() and len(code) == 6:
            return True
        if code.replace(".", "").replace("-", "").isalnum() and 1 <= len(code) <= 12:
            return True
        return False

    def _to_float(self, value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_number(self, value):
        number = self._to_float(value)
        if number is None:
            return value
        if abs(number) >= 1000:
            return "{:,.0f}".format(number)
        return "{:.2f}".format(number)

    def _format_bool(self, value):
        if value is True:
            return "사용"
        if value is False:
            return "미사용"
        return value

    def _display_column_label(self, column):
        return COLUMN_LABELS.get(column, column)

    def _display_cell_text(self, column, text):
        if column == "latest_signal":
            return VALUE_LABELS_BY_COLUMN.get("action_hint", {}).get(text, text)

        if column == "latest_events":
            event_labels = VALUE_LABELS_BY_COLUMN.get("event_type", {})
            return ", ".join(event_labels.get(item.strip(), item.strip()) for item in text.split(","))

        value_labels = VALUE_LABELS_BY_COLUMN.get(column)
        if value_labels:
            return value_labels.get(text, text)
        return text

    def _now_text(self):
        return datetime.now().strftime("%H:%M:%S")


def parse_args():
    parser = argparse.ArgumentParser(description="키움/OpenAI 대시보드를 실행합니다.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite DB 경로")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = QApplication(sys.argv)
    dashboard = Dashboard(db_path=args.db)
    dashboard.show()
    sys.exit(app.exec_())
