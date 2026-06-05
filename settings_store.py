"""Runtime-editable settings stored in SQLite.

``config.py`` remains the source of default values. The ``app_settings`` table
stores overrides that can be changed from the dashboard while the realtime app
is running. The realtime app reloads these settings every analysis cycle.
"""

import json
import sqlite3
from datetime import datetime

from app_paths import DEFAULT_DB_PATH, ensure_app_dirs
import config


DEFAULT_SETTINGS = [
    (
        "GPT_ANALYSIS_INTERVAL_SEC",
        "int",
        config.GPT_ANALYSIS_INTERVAL_SEC,
        "Analysis loop interval in seconds. Runtime change is applied on next cycle.",
    ),
    (
        "GPT_COOLDOWN_SEC",
        "int",
        config.GPT_COOLDOWN_SEC,
        "Minimum seconds between GPT calls for the same symbol.",
    ),
    (
        "MIN_TICKS_FOR_ANALYSIS",
        "int",
        config.MIN_TICKS_FOR_ANALYSIS,
        "Minimum in-memory ticks required before analysis starts.",
    ),
    (
        "ENABLE_EVENT_FILTER",
        "bool",
        config.ENABLE_EVENT_FILTER,
        "If true, GPT is called only when events are detected.",
    ),
    (
        "EVENT_RSI_LOW",
        "float",
        config.EVENT_RSI_LOW,
        "RSI oversold threshold.",
    ),
    (
        "EVENT_RSI_HIGH",
        "float",
        config.EVENT_RSI_HIGH,
        "RSI overbought threshold.",
    ),
    (
        "EVENT_VOLUME_RATIO",
        "float",
        config.EVENT_VOLUME_RATIO,
        "Volume spike threshold.",
    ),
    (
        "EVENT_BOX_HIGH_POSITION",
        "float",
        config.EVENT_BOX_HIGH_POSITION,
        "Upper box position threshold.",
    ),
    (
        "EVENT_BOX_LOW_POSITION",
        "float",
        config.EVENT_BOX_LOW_POSITION,
        "Lower box position threshold.",
    ),
    (
        "EVENT_VWAP_NEAR_PCT",
        "float",
        config.EVENT_VWAP_NEAR_PCT,
        "VWAP near-distance threshold in percent.",
    ),
    (
        "EVENT_CONSECUTIVE_BARS",
        "int",
        config.EVENT_CONSECUTIVE_BARS,
        "Consecutive rising/falling bar event threshold.",
    ),
    (
        "EVENT_ORDERBOOK_IMBALANCE",
        "float",
        config.EVENT_ORDERBOOK_IMBALANCE,
        "Bid/ask orderbook imbalance threshold.",
    ),
    (
        "ENABLE_NOTIFICATIONS",
        "bool",
        config.ENABLE_NOTIFICATIONS,
        "Enable notification sending.",
    ),
    (
        "NOTIFICATION_CHANNELS",
        "json",
        config.NOTIFICATION_CHANNELS,
        "Notification channels, e.g. [\"console\", \"telegram\"].",
    ),
    (
        "NOTIFICATION_COOLDOWN_SEC",
        "int",
        config.NOTIFICATION_COOLDOWN_SEC,
        "Minimum seconds between notifications for the same symbol.",
    ),
    (
        "NOTIFICATION_MAX_EVENTS",
        "int",
        config.NOTIFICATION_MAX_EVENTS,
        "Maximum event count included in one notification message.",
    ),
    (
        "TELEGRAM_TIMEOUT_SEC",
        "int",
        config.TELEGRAM_TIMEOUT_SEC,
        "HTTP timeout in seconds for Telegram sendMessage requests.",
    ),
    (
        "TELEGRAM_MAX_MESSAGE_CHARS",
        "int",
        config.TELEGRAM_MAX_MESSAGE_CHARS,
        "Maximum Telegram message length before local truncation.",
    ),
    (
        "ENABLE_KIWOOM_TR_CONTEXT_REQUESTS",
        "bool",
        config.ENABLE_KIWOOM_TR_CONTEXT_REQUESTS,
        "Enable verified Kiwoom TR context refreshes.",
    ),
    (
        "MARKET_CONTEXT_TR_REQUEST_INTERVAL_SEC",
        "int",
        config.MARKET_CONTEXT_TR_REQUEST_INTERVAL_SEC,
        "Interval for slower TR context refreshes.",
    ),
    (
        "MARKET_CONTEXT_TR_REQUEST_DELAY_MS",
        "int",
        config.MARKET_CONTEXT_TR_REQUEST_DELAY_MS,
        "Delay between scheduled Kiwoom market-context TR requests.",
    ),
    (
        "MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH",
        "int",
        config.MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH,
        "Maximum market-context TR requests scheduled per refresh batch.",
    ),
    (
        "ENABLE_MACRO_CONTEXT_CRAWL",
        "bool",
        config.ENABLE_MACRO_CONTEXT_CRAWL,
        "Enable best-effort macro context crawling for base rates and event calendar.",
    ),
    (
        "MACRO_CONTEXT_REFRESH_INTERVAL_SEC",
        "int",
        config.MACRO_CONTEXT_REFRESH_INTERVAL_SEC,
        "Minimum seconds between macro context crawls.",
    ),
    (
        "MACRO_CONTEXT_TIMEOUT_SEC",
        "int",
        config.MACRO_CONTEXT_TIMEOUT_SEC,
        "HTTP timeout in seconds for macro context crawlers.",
    ),
    (
        "MACRO_BOK_BASE_RATE_URL",
        "str",
        config.MACRO_BOK_BASE_RATE_URL,
        "Bank of Korea base-rate page used by the macro crawler.",
    ),
    (
        "MACRO_FED_OPEN_MARKET_URL",
        "str",
        config.MACRO_FED_OPEN_MARKET_URL,
        "Federal Reserve open-market operations page used for the fed funds target range.",
    ),
    (
        "MACRO_EVENT_CALENDAR_URLS",
        "json",
        config.MACRO_EVENT_CALENDAR_URLS,
        "Macro event calendar pages crawled for upcoming policy/economic events.",
    ),
    (
        "PRELOAD_RECENT_TICKS_FROM_DB",
        "bool",
        config.PRELOAD_RECENT_TICKS_FROM_DB,
        "Load recent persisted ticks into memory when main.py starts.",
    ),
    (
        "PRELOAD_TICKS_PER_CODE",
        "int",
        config.PRELOAD_TICKS_PER_CODE,
        "Maximum recent ticks loaded per code on startup.",
    ),
    (
        "PRELOAD_TICKS_MAX_AGE_MINUTES",
        "int",
        config.PRELOAD_TICKS_MAX_AGE_MINUTES,
        "Only preload ticks newer than this many minutes.",
    ),
    (
        "ENABLE_PAPER_TRADE_EVALUATION",
        "bool",
        config.ENABLE_PAPER_TRADE_EVALUATION,
        "Evaluate saved validation signals once enough future ticks exist.",
    ),
    (
        "PAPER_TRADE_EVALUATION_LIMIT",
        "int",
        config.PAPER_TRADE_EVALUATION_LIMIT,
        "Maximum pending validation signals evaluated per analysis cycle.",
    ),
    (
        "ENABLE_GPT_INPUT_COMPRESSION",
        "bool",
        config.ENABLE_GPT_INPUT_COMPRESSION,
        "Compress GPT input payload before API calls while keeping raw DB evidence.",
    ),
    (
        "GPT_INPUT_RECENT_POINTS",
        "int",
        config.GPT_INPUT_RECENT_POINTS,
        "Recent close/volume points kept per timeframe in GPT input.",
    ),
    (
        "GPT_INPUT_MAX_CONTEXT_ITEMS",
        "int",
        config.GPT_INPUT_MAX_CONTEXT_ITEMS,
        "Maximum news/disclosure/reaction items kept per GPT input section.",
    ),
    (
        "GPT_INPUT_MAX_ACTION_STATS",
        "int",
        config.GPT_INPUT_MAX_ACTION_STATS,
        "Maximum action-stat rows kept in GPT input.",
    ),
    (
        "GPT_INPUT_MAX_RECENT_SIGNALS",
        "int",
        config.GPT_INPUT_MAX_RECENT_SIGNALS,
        "Maximum recent signal rows kept in GPT input.",
    ),
    (
        "GPT_INPUT_INCLUDE_RECENT_SIGNALS",
        "bool",
        config.GPT_INPUT_INCLUDE_RECENT_SIGNALS,
        "Include recent individual signal rows in GPT input. Summary stats are still kept.",
    ),
    (
        "GPT_INPUT_MAX_TEXT_CHARS",
        "int",
        config.GPT_INPUT_MAX_TEXT_CHARS,
        "Maximum characters kept for each free-text context field.",
    ),
    (
        "GPT_MIN_SIGNAL_SCORE",
        "float",
        config.GPT_MIN_SIGNAL_SCORE,
        "Minimum validation signal score required for GPT call eligibility.",
    ),
    (
        "GPT_MAX_SYMBOLS_PER_CALL",
        "int",
        config.GPT_MAX_SYMBOLS_PER_CALL,
        "Maximum number of symbols included in one GPT request.",
    ),
    (
        "GPT_STRONG_EVENT_TYPES",
        "json",
        config.GPT_STRONG_EVENT_TYPES,
        "Event types that can qualify a symbol for GPT analysis.",
    ),
    (
        "ENABLE_MARKET_FLOW_DIRECTION_RISK",
        "bool",
        config.ENABLE_MARKET_FLOW_DIRECTION_RISK,
        "Enable direction-only market foreign/program selling risk until OPT10051 units are live-validated.",
    ),
    (
        "EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT",
        "int",
        config.EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT,
        "Minimum count of weak benchmark ETFs required for market foreign-sell pressure.",
    ),
    (
        "SIGNAL_MARKET_FLOW_RISK_PENALTY",
        "int",
        config.SIGNAL_MARKET_FLOW_RISK_PENALTY,
        "Validation-score penalty when foreign selling, program selling, and weak ETFs align.",
    ),
    (
        "TELEGRAM_COMPACT_EVENT_MESSAGE",
        "bool",
        config.TELEGRAM_COMPACT_EVENT_MESSAGE,
        "Send compact event messages to Telegram/console instead of long diagnostic text.",
    ),
    (
        "TELEGRAM_NOTIFY_ONLY_HIGH_PRIORITY",
        "bool",
        config.TELEGRAM_NOTIFY_ONLY_HIGH_PRIORITY,
        "If true, Telegram receives only high-priority signals while console logging stays broader.",
    ),
    (
        "TELEGRAM_MIN_SIGNAL_SCORE",
        "float",
        config.TELEGRAM_MIN_SIGNAL_SCORE,
        "Minimum validation signal score required for Telegram event notification.",
    ),
    (
        "TELEGRAM_ALLOWED_ACTION_HINTS",
        "json",
        config.TELEGRAM_ALLOWED_ACTION_HINTS,
        "Validation action hints allowed to send Telegram notifications when high-priority filtering is enabled.",
    ),
    (
        "TELEGRAM_ALWAYS_NOTIFY_EVENT_TYPES",
        "json",
        config.TELEGRAM_ALWAYS_NOTIFY_EVENT_TYPES,
        "Critical event types that always allow Telegram notification.",
    ),
    (
        "SIGNAL_FOCUS_TIME_WINDOWS",
        "json",
        config.SIGNAL_FOCUS_TIME_WINDOWS,
        "Time windows where otherwise valid long signals get a small focus bonus.",
    ),
    (
        "SIGNAL_FOCUS_WINDOW_BONUS",
        "float",
        config.SIGNAL_FOCUS_WINDOW_BONUS,
        "Small validation-score bonus applied inside focus time windows.",
    ),
    (
        "SIGNAL_NON_FOCUS_WINDOW_PENALTY",
        "float",
        config.SIGNAL_NON_FOCUS_WINDOW_PENALTY,
        "Validation-score penalty applied to long signals outside focus time windows.",
    ),
    (
        "SIGNAL_WEAK_TIME_WINDOWS",
        "json",
        config.SIGNAL_WEAK_TIME_WINDOWS,
        "Time windows where long signals are treated more conservatively.",
    ),
    (
        "SIGNAL_WEAK_WINDOW_EXTRA_PENALTY",
        "float",
        config.SIGNAL_WEAK_WINDOW_EXTRA_PENALTY,
        "Extra validation-score penalty applied inside weak time windows.",
    ),
    (
        "TRADE_BUY_FEE_PCT",
        "float",
        config.TRADE_BUY_FEE_PCT,
        "Estimated buy commission percentage for GPT cost-adjusted analysis.",
    ),
    (
        "TRADE_SELL_FEE_PCT",
        "float",
        config.TRADE_SELL_FEE_PCT,
        "Estimated sell commission percentage for GPT cost-adjusted analysis.",
    ),
    (
        "TRADE_SELL_TAX_PCT",
        "float",
        config.TRADE_SELL_TAX_PCT,
        "Estimated sell-side transaction tax percentage for GPT cost-adjusted analysis.",
    ),
    (
        "TRADE_SLIPPAGE_PCT",
        "float",
        config.TRADE_SLIPPAGE_PCT,
        "Estimated one-way slippage percentage for GPT cost-adjusted analysis.",
    ),
    (
        "GPT_MAX_TOKENS",
        "int",
        config.GPT_MAX_TOKENS,
        "Maximum GPT output tokens. Requires restart to affect GPTAnalyzer import-time config.",
    ),
    (
        "WATCH_CODES",
        "json",
        config.WATCH_CODES,
        "Watch code map. Runtime re-registration is applied by main.py after the next analysis cycle.",
    ),
    (
        "MARKET_BENCHMARK_CODES",
        "json",
        config.MARKET_BENCHMARK_CODES,
        "Context-only market ETF map. Realtime ticks are stored without symbol-level GPT analysis or stock TR requests.",
    ),
]


class SettingsStore:
    """Read and write app settings from SQLite."""

    def __init__(self, conn=None, db_path=DEFAULT_DB_PATH):
        self.conn = conn
        self.owns_connection = conn is None

        if self.conn is None:
            ensure_app_dirs()
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row

        self._create_table()
        self.ensure_defaults()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                value_type TEXT NOT NULL,
                description TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def ensure_defaults(self):
        """Insert missing default settings without overwriting user changes."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        rows = []

        for key, value_type, value, description in DEFAULT_SETTINGS:
            rows.append((
                key,
                self.serialize(value, value_type),
                value_type,
                description,
                now,
            ))

        self.conn.executemany("""
            INSERT OR IGNORE INTO app_settings (
                key, value, value_type, description, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
        """, rows)
        self.conn.commit()

    def get_all(self):
        """Return every setting row ordered by key."""
        return self.conn.execute("""
            SELECT key, value, value_type, description, updated_at
            FROM app_settings
            ORDER BY key ASC
        """).fetchall()

    def get_runtime_settings(self):
        """Return parsed settings as a plain dictionary."""
        settings = {}
        for row in self.get_all():
            settings[row["key"]] = self.parse(row["value"], row["value_type"])
        return settings

    def update_setting(self, key, value):
        """Update one setting from a UI/string value."""
        row = self.conn.execute("""
            SELECT value_type
            FROM app_settings
            WHERE key = ?
        """, (key,)).fetchone()

        if not row:
            raise KeyError("Unknown setting: {}".format(key))

        value_type = row["value_type"]
        parsed = value if value_type == "json" and not isinstance(value, str) else self.parse(str(value), value_type)
        serialized = self.serialize(parsed, value_type)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        self.conn.execute("""
            UPDATE app_settings
            SET value = ?,
                updated_at = ?
            WHERE key = ?
        """, (serialized, now, key))
        self.conn.commit()

    def get(self, key, default=None):
        row = self.conn.execute("""
            SELECT value, value_type
            FROM app_settings
            WHERE key = ?
        """, (key,)).fetchone()

        if not row:
            return default

        return self.parse(row["value"], row["value_type"])

    def close(self):
        if self.owns_connection and self.conn:
            self.conn.close()
            self.conn = None

    @staticmethod
    def serialize(value, value_type):
        if value_type == "json":
            return json.dumps(value, ensure_ascii=False)
        if value_type == "bool":
            return "true" if bool(value) else "false"
        return str(value)

    @staticmethod
    def parse(value, value_type):
        if value_type == "int":
            return int(float(value))
        if value_type == "float":
            return float(value)
        if value_type == "bool":
            return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
        if value_type == "json":
            return json.loads(value)
        return value
