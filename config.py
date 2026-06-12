"""Runtime configuration for the Kiwoom + OpenAI analysis prototype.

Keep this file simple. Values here are imported by the realtime app,
simulation, event detector, notifier, and database layer.
"""

WATCH_CODES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
}

MARKET_BENCHMARK_CODES = {
    "069500": "KODEX 200",
    "229200": "KODEX 코스닥150",
    "091160": "KODEX 반도체",
    "139260": "TIGER 200 IT",
    "102780": "KODEX 삼성그룹",
}

# GPT analysis timer. Event filtering means GPT is called only when meaningful
# events are detected, not on every timer tick.
GPT_ANALYSIS_INTERVAL_SEC = 60

# Per-symbol in-memory tick cap. SQLite persistence is separate.
MAX_TICKS_PER_CODE_MEMORY = 50000

# Minimum ticks required before indicator analysis starts.
MIN_TICKS_FOR_ANALYSIS = 30

# The current 32-bit Python/OpenAI SDK environment uses chat.completions.create.
GPT_MODEL = "gpt-4o-mini"
GPT_MAX_TOKENS = 3000

# GPT input compression. Raw evidence stays in SQLite; GPT receives a compact
# payload to keep token cost and latency predictable.
ENABLE_GPT_INPUT_COMPRESSION = True
GPT_INPUT_RECENT_POINTS = 5
GPT_INPUT_MAX_CONTEXT_ITEMS = 3
GPT_INPUT_MAX_ACTION_STATS = 3
GPT_INPUT_MAX_RECENT_SIGNALS = 0
GPT_INPUT_MAX_TEXT_CHARS = 700
GPT_INPUT_INCLUDE_RECENT_SIGNALS = False

# GPT trigger pruning. Cooldown remains separate; these settings reduce payload
# size and avoid asking GPT about weak events.
GPT_MIN_SIGNAL_SCORE = 55
GPT_MAX_SYMBOLS_PER_CALL = 4
GPT_STRONG_EVENT_TYPES = [
    "RSI_OVERSOLD",
    "RSI_OVERBOUGHT",
    "VOLUME_SPIKE",
    "NEAR_BOX_HIGH",
    "NEAR_BOX_LOW",
    "MA5_MA20_GOLDEN_CROSS",
    "MA5_MA20_DEAD_CROSS",
    "ORDERBOOK_BID_IMBALANCE",
    "ORDERBOOK_ASK_IMBALANCE",
    "MARKET_SIDECAR_ACTIVE",
    "MARKET_SIDECAR_RECENT",
    "MARKET_CIRCUIT_BREAKER_ACTIVE",
    "MARKET_VI_ACTIVE",
    "MARKET_FOREIGN_SELL_PRESSURE",
]

# Trading cost assumptions used only for analysis and paper validation.
# Values are percentages. Keep them editable because broker fees and taxes vary.
TRADE_BUY_FEE_PCT = 0.015
TRADE_SELL_FEE_PCT = 0.015
TRADE_SELL_TAX_PCT = 0.18
TRADE_SLIPPAGE_PCT = 0.05

# Event-based GPT calls. If no event exists, GPT calls are skipped to reduce
# cost and latency.
ENABLE_EVENT_FILTER = True
GPT_COOLDOWN_SEC = 180

# Deterministic event thresholds.
EVENT_RSI_LOW = 30
EVENT_RSI_HIGH = 70
EVENT_VOLUME_RATIO = 2.0
EVENT_BOX_HIGH_POSITION = 0.95
EVENT_BOX_LOW_POSITION = 0.05
EVENT_VWAP_NEAR_PCT = 0.5
EVENT_CONSECUTIVE_BARS = 3
EVENT_ORDERBOOK_IMBALANCE = 0.35

# Market-wide flow risk uses direction only until OPT10051 live units have
# been checked. Tune the ETF count and score penalty after regular-session
# samples have accumulated.
ENABLE_MARKET_FLOW_DIRECTION_RISK = True
EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT = 1
SIGNAL_MARKET_FLOW_RISK_PENALTY = 12

# Risk-on sessions can make short intraday pullbacks look like downtrends.
# This does not create orders; it only prevents deterministic validation labels
# from becoming too defensive when the broader tape and the stock are both up.
ENABLE_RISK_ON_PULLBACK_RELABEL = True
SIGNAL_RISK_ON_MIN_MARKET_CHANGE_PCT = 1.0
SIGNAL_RISK_ON_MIN_STOCK_CHANGE_PCT = 1.0

# Pullback candidates are fragile in weak tapes or before large macro events.
SIGNAL_PULLBACK_MIN_CONFIRMING_VWAP_TIMEFRAMES = 1
SIGNAL_PULLBACK_MACRO_EVENT_PENALTY = 10
SIGNAL_PULLBACK_MACRO_EVENT_KEYWORDS = [
    "CPI",
    "Core CPI",
    "Consumer Price Index",
    "PPI",
    "Core PPI",
    "FOMC",
    "Federal Reserve",
    "Fed",
    "rate decision",
    "inflation",
]

# VWAP resistance is not always bearish in a risk-on tape. If the market,
# stock, and 3m/5m confirmation align, treat it as momentum observation instead
# of an avoid/caution signal.
ENABLE_RISK_ON_RESISTANCE_RELABEL = True
SIGNAL_RESISTANCE_MIN_CONFIRMING_VWAP_TIMEFRAMES = 1

# Post-market paper validation showed too many false caution signals from
# standalone VWAP resistance and one-sided orderbook supply. Keep these strict
# unless another price/flow condition confirms the risk.
SIGNAL_REQUIRE_RESISTANCE_CONFIRMATION = True
SIGNAL_REQUIRE_SUPPLY_CONFIRMATION = True

# Notifications. Console is enabled by default. Telegram is filtered to reduce
# noise when it is enabled in app settings.
ENABLE_NOTIFICATIONS = True
NOTIFICATION_CHANNELS = ["console"]
NOTIFICATION_COOLDOWN_SEC = 180
NOTIFICATION_MAX_EVENTS = 5
TELEGRAM_TIMEOUT_SEC = 5
TELEGRAM_MAX_MESSAGE_CHARS = 3500
TELEGRAM_COMPACT_EVENT_MESSAGE = True
TELEGRAM_NOTIFY_ONLY_HIGH_PRIORITY = True
TELEGRAM_MIN_SIGNAL_SCORE = 70
TELEGRAM_ALLOWED_ACTION_HINTS = [
    "WATCH_REBOUND",
    "WATCH_PULLBACK",
    "WATCH_BREAKOUT",
    "WATCH_MOMENTUM",
    "AVOID_DOWNTREND",
    "AVOID_MARKET_RISK",
]
TELEGRAM_ALWAYS_NOTIFY_EVENT_TYPES = [
    "MARKET_SIDECAR_ACTIVE",
    "MARKET_CIRCUIT_BREAKER_ACTIVE",
    "MARKET_VI_ACTIVE",
]

# Time-of-day signal adjustment. GPT calls are unchanged; this only nudges the
# deterministic validation score used for ranking and notifications.
SIGNAL_FOCUS_TIME_WINDOWS = ["09:00-10:00", "12:00-14:00"]
SIGNAL_FOCUS_WINDOW_BONUS = 3
SIGNAL_NON_FOCUS_WINDOW_PENALTY = 5
SIGNAL_WEAK_TIME_WINDOWS = ["10:00-12:00"]
SIGNAL_WEAK_WINDOW_EXTRA_PENALTY = 3

# Optional extra market context for GPT.
ENABLE_MARKET_CONTEXT = True
MARKET_CONTEXT_PATH = "market_context.json"

# Verified Kiwoom TR context requests. TR definitions are read from the local
# C:\OpenAPI KOA files and requested slowly to leave room under Kiwoom limits.
ENABLE_KIWOOM_TR_CONTEXT_REQUESTS = True
MARKET_CONTEXT_TR_REQUEST_INTERVAL_SEC = 900
MARKET_CONTEXT_TR_REQUEST_DELAY_MS = 1100
MARKET_CONTEXT_TR_MAX_REQUESTS_PER_BATCH = 24

# Macro context crawling. These pages are best-effort supplemental inputs; if a
# page layout changes, the app keeps running and records the failure in notes.
ENABLE_MACRO_CONTEXT_CRAWL = True
MACRO_CONTEXT_REFRESH_INTERVAL_SEC = 1800
MACRO_CONTEXT_TIMEOUT_SEC = 5
MACRO_BOK_BASE_RATE_URL = "https://www.bok.or.kr/portal/singl/baseRate/progress.do?dataSeCd=01&menuNo=200643"
MACRO_FED_OPEN_MARKET_URL = "https://www.federalreserve.gov/monetarypolicy/openmarket.htm"
MACRO_EVENT_CALENDAR_URLS = [
    "https://www.bok.or.kr/portal/singl/crncyPolicyDrcMtg/listYear.do?menuNo=200755&mtgSe=A",
]

# Realtime tick console printing is useful while debugging, but noisy during
# normal market-hours runs because every trade event is already persisted.
PRINT_REALTIME_TICKS = False
REALTIME_TICK_PRINT_EVERY = 100

# Warm-start analysis after a restart by loading recent ticks from SQLite into
# memory. Stale ticks are ignored by max-age.
PRELOAD_RECENT_TICKS_FROM_DB = True
PRELOAD_TICKS_PER_CODE = 50000
PRELOAD_TICKS_MAX_AGE_MINUTES = 30

# Paper-trade evaluation. Saved validation signals are evaluated later when
# enough future ticks exist. This improves GPT context without placing orders.
ENABLE_PAPER_TRADE_EVALUATION = True
PAPER_TRADE_EVALUATION_LIMIT = 200

# Historical backfill defaults. These are intentionally conservative so a
# normal startup backfill leaves room under Kiwoom TR limits.
BACKFILL_DAILY_DAYS = 365
BACKFILL_MINUTE_DAYS = 5
BACKFILL_MINUTE_INTERVALS = "1,3,5"
BACKFILL_REQUEST_DELAY_MS = 1200
BACKFILL_MAX_PAGES_PER_JOB = 1
BACKFILL_MAX_TR_REQUESTS_PER_RUN = 60
