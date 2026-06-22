"""SQLite schema creation and lightweight migrations."""


TABLE_SQL = [
    """
    CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        trade_time TEXT,
        price INTEGER,
        change_rate REAL,
        acc_volume INTEGER,
        tick_volume INTEGER,
        open_price INTEGER,
        high_price INTEGER,
        low_price INTEGER,
        strength REAL,
        received_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        analyzed_at TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT,
        current_price REAL,
        rsi14 REAL,
        ma5 REAL,
        ma20 REAL,
        ma60 REAL,
        volume_ratio_5 REAL,
        volume_ratio_20 REAL,
        vwap REAL,
        vwap_distance_pct REAL,
        box_high REAL,
        box_low REAL,
        box_position REAL,
        day_open REAL,
        day_high REAL,
        day_low REAL,
        strength REAL,
        market_context_json TEXT,
        summary_json TEXT,
        gpt_result TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detected_at TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT,
        event_type TEXT NOT NULL,
        timeframe TEXT,
        message TEXT,
        value REAL,
        gpt_requested INTEGER NOT NULL,
        skip_reason TEXT,
        summary_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gpt_call_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        status TEXT NOT NULL,
        requested_count INTEGER NOT NULL,
        codes TEXT,
        model TEXT,
        duration_ms INTEGER,
        prompt_chars INTEGER,
        payload_original_chars INTEGER,
        payload_compressed_chars INTEGER,
        payload_compression_ratio REAL,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        total_tokens INTEGER,
        error_message TEXT,
        result_preview TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS gpt_analysis_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        gpt_call_id INTEGER,
        analyzed_at TEXT NOT NULL,
        code TEXT NOT NULL,
        parse_status TEXT NOT NULL,
        decision TEXT,
        risk_score REAL,
        gpt_context_score REAL,
        breakout_score REAL,
        trend_score REAL,
        confidence REAL,
        risk_flags_json TEXT,
        invalid_condition TEXT,
        summary TEXT,
        entry_plan TEXT,
        raw_json TEXT,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signal_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detected_at TEXT NOT NULL,
        code TEXT NOT NULL,
        name TEXT,
        action_hint TEXT NOT NULL,
        confidence_score REAL,
        risk_level TEXT,
        current_price REAL,
        stop_loss REAL,
        target_1 REAL,
        target_2 REAL,
        reason_json TEXT,
        summary_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant_signal_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER,
        scored_at TEXT NOT NULL,
        code TEXT NOT NULL,
        action_hint TEXT,
        quant_signal_score REAL,
        expected_value_score REAL,
        market_risk_score REAL,
        final_quant_score REAL,
        decision_side TEXT,
        feature_json TEXT,
        formula_version TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_trade_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER NOT NULL,
        evaluated_at TEXT NOT NULL,
        code TEXT NOT NULL,
        entry_time TEXT,
        entry_price REAL,
        return_5m_pct REAL,
        return_10m_pct REAL,
        return_30m_pct REAL,
        return_60m_pct REAL,
        max_gain_30m_pct REAL,
        max_loss_30m_pct REAL,
        max_gain_60m_pct REAL,
        max_loss_60m_pct REAL,
        target_1_hit INTEGER,
        target_2_hit INTEGER,
        stop_loss_hit INTEGER,
        outcome_label TEXT,
        result_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sent_at TEXT NOT NULL,
        code TEXT,
        name TEXT,
        channel TEXT NOT NULL,
        status TEXT NOT NULL,
        event_types TEXT,
        message TEXT,
        error_message TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS historical_bars (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        bar_time TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER,
        trading_value INTEGER,
        source TEXT,
        fetched_at TEXT NOT NULL,
        UNIQUE(code, timeframe, bar_time)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_context_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        collected_at TEXT NOT NULL,
        scope TEXT NOT NULL,
        code TEXT,
        section TEXT NOT NULL,
        source TEXT,
        asof TEXT,
        reliability TEXT,
        weight TEXT,
        summary TEXT,
        payload_json TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant_feedback_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generated_at TEXT NOT NULL,
        scope TEXT NOT NULL,
        code TEXT,
        window_start TEXT,
        window_end TEXT,
        min_sample INTEGER,
        signal_count INTEGER,
        evaluated_count INTEGER,
        payload_json TEXT NOT NULL,
        guidance_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        value_type TEXT NOT NULL,
        description TEXT,
        updated_at TEXT NOT NULL
    )
    """,
]

MIGRATION_COLUMNS = [
    ("analysis_results", "vwap", "REAL"),
    ("analysis_results", "vwap_distance_pct", "REAL"),
    ("analysis_results", "day_open", "REAL"),
    ("analysis_results", "day_high", "REAL"),
    ("analysis_results", "day_low", "REAL"),
    ("analysis_results", "strength", "REAL"),
    ("analysis_results", "market_context_json", "TEXT"),
    ("gpt_call_logs", "model", "TEXT"),
    ("gpt_call_logs", "duration_ms", "INTEGER"),
    ("gpt_call_logs", "prompt_chars", "INTEGER"),
    ("gpt_call_logs", "payload_original_chars", "INTEGER"),
    ("gpt_call_logs", "payload_compressed_chars", "INTEGER"),
    ("gpt_call_logs", "payload_compression_ratio", "REAL"),
    ("gpt_call_logs", "prompt_tokens", "INTEGER"),
    ("gpt_call_logs", "completion_tokens", "INTEGER"),
    ("gpt_call_logs", "total_tokens", "INTEGER"),
    ("paper_trade_results", "return_60m_pct", "REAL"),
    ("paper_trade_results", "max_gain_60m_pct", "REAL"),
    ("paper_trade_results", "max_loss_60m_pct", "REAL"),
    ("paper_trade_results", "target_1_hit", "INTEGER"),
    ("paper_trade_results", "target_2_hit", "INTEGER"),
    ("paper_trade_results", "stop_loss_hit", "INTEGER"),
    ("paper_trade_results", "outcome_label", "TEXT"),
    ("gpt_analysis_scores", "entry_plan", "TEXT"),
]

INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_ticks_code_received_at ON ticks (code, received_at)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_code_analyzed_at ON analysis_results (code, analyzed_at)",
    "CREATE INDEX IF NOT EXISTS idx_event_logs_code_detected_at ON event_logs (code, detected_at)",
    "CREATE INDEX IF NOT EXISTS idx_gpt_call_logs_started_at ON gpt_call_logs (started_at)",
    "CREATE INDEX IF NOT EXISTS idx_gpt_analysis_scores_code_time ON gpt_analysis_scores (code, analyzed_at)",
    "CREATE INDEX IF NOT EXISTS idx_gpt_analysis_scores_call_id ON gpt_analysis_scores (gpt_call_id)",
    "CREATE INDEX IF NOT EXISTS idx_signal_logs_code_detected_at ON signal_logs (code, detected_at)",
    "CREATE INDEX IF NOT EXISTS idx_quant_signal_scores_signal_id ON quant_signal_scores (signal_id)",
    "CREATE INDEX IF NOT EXISTS idx_quant_signal_scores_code_time ON quant_signal_scores (code, scored_at)",
    "CREATE INDEX IF NOT EXISTS idx_paper_trade_results_signal_id ON paper_trade_results (signal_id)",
    "CREATE INDEX IF NOT EXISTS idx_notification_logs_sent_at ON notification_logs (sent_at)",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_bars_unique
    ON historical_bars (code, timeframe, bar_time)
    """,
    "CREATE INDEX IF NOT EXISTS idx_historical_bars_code_tf_time ON historical_bars (code, timeframe, bar_time)",
    "CREATE INDEX IF NOT EXISTS idx_market_context_scope_section_time ON market_context_snapshots (scope, section, collected_at)",
    "CREATE INDEX IF NOT EXISTS idx_market_context_code_section_time ON market_context_snapshots (code, section, collected_at)",
    "CREATE INDEX IF NOT EXISTS idx_quant_feedback_scope_time ON quant_feedback_snapshots (scope, generated_at)",
    "CREATE INDEX IF NOT EXISTS idx_quant_feedback_code_time ON quant_feedback_snapshots (code, generated_at)",
    "CREATE INDEX IF NOT EXISTS idx_app_settings_updated_at ON app_settings (updated_at)",
]


def create_or_migrate_schema(conn):
    """Create tables, apply additive migrations, and ensure indexes."""
    for sql in TABLE_SQL:
        conn.execute(sql)

    for table_name, column_name, column_type in MIGRATION_COLUMNS:
        _ensure_column(conn, table_name, column_name, column_type)

    _deduplicate_historical_bars(conn)

    for sql in INDEX_SQL:
        conn.execute(sql)

    conn.commit()


def _ensure_column(conn, table_name, column_name, column_type):
    cursor = conn.execute("PRAGMA table_info({})".format(table_name))
    columns = [row["name"] for row in cursor.fetchall()]

    if column_name not in columns:
        conn.execute(
            "ALTER TABLE {} ADD COLUMN {} {}".format(table_name, column_name, column_type)
        )


def _deduplicate_historical_bars(conn):
    duplicate = conn.execute("""
        SELECT 1
        FROM historical_bars
        GROUP BY code, timeframe, bar_time
        HAVING COUNT(1) > 1
        LIMIT 1
    """).fetchone()

    if not duplicate:
        return

    conn.execute("""
        DELETE FROM historical_bars
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM historical_bars
            GROUP BY code, timeframe, bar_time
        )
    """)
