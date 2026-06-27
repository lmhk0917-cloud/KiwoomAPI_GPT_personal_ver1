"""Market context loader and runtime overlay.

GPT should receive more than price bars when available: market indices,
reference levels, orderbook, program trading, short selling, credit,
derivatives, news, disclosures, and very low-weight public reaction context.
Some data comes from a manual JSON file, while realtime Kiwoom events update
the runtime overlay.
"""

import copy
import json
import os
import sqlite3

from config import ENABLE_MARKET_CONTEXT, MARKET_CONTEXT_PATH


DEFAULT_MARKET_CONTEXT = {
    "asof": None,
    "market_indices": {
        "kospi": None,
        "kospi_change_pct": None,
        "kosdaq": None,
        "kosdaq_change_pct": None,
        "kospi200": None,
        "kospi200_change_pct": None,
        "usd_krw": None,
        "usd_krw_change_pct": None,
    },
    "market_investor_flow": {
        "kospi_sector_count": None,
        "kospi_individual_net_value": None,
        "kospi_foreign_net_value": None,
        "kospi_institution_net_value": None,
        "kosdaq_sector_count": None,
        "kosdaq_individual_net_value": None,
        "kosdaq_foreign_net_value": None,
        "kosdaq_institution_net_value": None,
        "combined_foreign_net_value": None,
        "combined_institution_net_value": None,
        "combined_individual_net_value": None,
        "reliability": "sector_sum_proxy_pending_live_unit_validation",
    },
    "benchmark_etfs": {},
    "macro_context": {
        "asof": None,
        "source": None,
        "reliability": "manual_or_unverified",
        "summary": None,
        "risk_regime": None,
        "risk_regime_reason": None,
        "kr_base_rate": None,
        "kr_base_rate_change_bp": None,
        "us_fed_funds_rate": None,
        "us_10y_yield": None,
        "us_10y_yield_change_bp": None,
        "usd_krw": None,
        "usd_krw_change_pct": None,
        "dxy": None,
        "dxy_change_pct": None,
        "vix": None,
        "vix_change_pct": None,
        "sp500_futures_change_pct": None,
        "nasdaq_futures_change_pct": None,
        "nikkei_change_pct": None,
        "hangseng_change_pct": None,
        "wti_change_pct": None,
        "gold_change_pct": None,
        "semiconductor_index_change_pct": None,
        "next_macro_events": [],
        "notes": [],
    },
    "market_status": {
        "asof": None,
        "market": None,
        "sidecar_status": "inactive",
        "sidecar_direction": None,
        "sidecar_started_at": None,
        "sidecar_ended_at": None,
        "circuit_breaker_status": "inactive",
        "vi_status": "inactive",
        "market_phase": None,
        "summary": None,
        "source": None,
        "reliability": "manual_or_unverified",
    },
    "sector_context": {
        "sector_name": None,
        "sector_index": None,
        "sector_change_pct": None,
        "relative_strength_vs_sector_pct": None,
        "peer_movers": [],
    },
    "reference_levels": {
        "previous_close": None,
        "previous_high": None,
        "previous_low": None,
        "today_open_gap_pct": None,
        "intraday_high_breakout": None,
        "intraday_low_breakdown": None,
        "recent_20d_high": None,
        "recent_20d_low": None,
        "distance_from_20d_high_pct": None,
        "distance_from_20d_low_pct": None,
    },
    "derivatives": {
        "kospi200_futures_price": None,
        "kospi200_futures_change_pct": None,
        "basis": None,
        "theoretical_basis": None,
        "futures_volume": None,
        "open_interest": None,
        "foreign_futures_net_contracts": None,
        "institution_futures_net_contracts": None,
        "option_month": None,
        "call_option_count": None,
        "put_option_count": None,
        "call_option_volume": None,
        "put_option_volume": None,
        "call_option_trading_value": None,
        "put_option_trading_value": None,
        "call_option_open_interest": None,
        "put_option_open_interest": None,
        "put_call_ratio": None,
        "put_call_open_interest_ratio": None,
        "call_implied_volatility_avg": None,
        "put_implied_volatility_avg": None,
        "implied_volatility": None,
    },
    "short_selling": {
        "date": None,
        "close": None,
        "short_sale_volume": None,
        "short_sale_value": None,
        "short_sale_ratio_pct": None,
        "short_sale_avg_price": None,
        "short_balance_qty": None,
        "short_balance_ratio_pct": None,
        "stock_loan_date": None,
        "stock_loan_execution_qty": None,
        "stock_loan_repayment_qty": None,
        "stock_loan_change_qty": None,
        "stock_loan_balance_qty": None,
        "stock_loan_balance_value": None,
    },
    "credit": {
        "date": None,
        "credit_new_qty": None,
        "credit_repay_qty": None,
        "credit_balance_qty": None,
        "credit_amount": None,
        "credit_supply_ratio_pct": None,
        "credit_balance_ratio_pct": None,
        "credit_balance_change_qty": None,
        "loan_balance_qty": None,
        "loan_balance_change_qty": None,
    },
    "investor_flow": {
        "date": None,
        "individual_net_value": None,
        "foreign_net_value": None,
        "institution_net_value": None,
        "financial_investment_net_value": None,
        "insurance_net_value": None,
        "trust_net_value": None,
        "bank_net_value": None,
        "pension_net_value": None,
        "private_fund_net_value": None,
        "other_corporation_net_value": None,
        "domestic_foreign_net_value": None,
    },
    "orderbook": {
        "best_bid": None,
        "best_ask": None,
        "spread": None,
        "spread_pct": None,
        "total_bid_qty": None,
        "total_ask_qty": None,
        "bid_ask_imbalance": None,
        "bid_levels": [],
        "ask_levels": [],
    },
    "program_trading": {
        "program_net_value": None,
        "program_buy_value": None,
        "program_sell_value": None,
        "foreign_net_value": None,
        "institution_net_value": None,
    },
    "market_program_trading": {
        "market": None,
        "time": None,
        "date": None,
        "arbitrage_sell_value": None,
        "arbitrage_buy_value": None,
        "arbitrage_net_value": None,
        "non_arbitrage_sell_value": None,
        "non_arbitrage_buy_value": None,
        "non_arbitrage_net_value": None,
        "total_sell_value": None,
        "total_buy_value": None,
        "total_net_value": None,
        "kospi200": None,
        "basis": None,
    },
    "news": {
        "asof": None,
        "summary": None,
        "sentiment": None,
        "source_count": None,
        "items": [],
    },
    "disclosures": {
        "asof": None,
        "summary": None,
        "materiality": None,
        "items": [],
    },
    "public_reaction": {
        "asof": None,
        "summary": None,
        "sentiment": None,
        "source_count": None,
        "dominant_topics": [],
        "sample_size": None,
        "weight": "very_low",
    },
    "data_quality": {
        "tick_last_received_at": None,
        "orderbook_last_received_at": None,
        "program_trading_last_received_at": None,
        "market_program_trading_last_received_at": None,
        "short_selling_last_received_at": None,
        "credit_last_received_at": None,
        "investor_flow_last_received_at": None,
        "market_indices_last_received_at": None,
        "market_investor_flow_last_received_at": None,
        "derivatives_last_received_at": None,
        "macro_context_last_checked_at": None,
        "market_status_last_checked_at": None,
        "news_last_checked_at": None,
        "disclosure_last_checked_at": None,
        "public_reaction_last_checked_at": None,
        "missing_sections": [],
    },
    "notes": [],
}


class MarketContextStore:
    """Merge default, file-based, and realtime market context for each symbol."""

    def __init__(self, json_path=None, enabled=ENABLE_MARKET_CONTEXT):
        self.enabled = enabled
        self.json_path = self._resolve_path(json_path or MARKET_CONTEXT_PATH)
        self.global_context = {}
        self.code_contexts = {}
        self.runtime_global_context = {}
        self.runtime_code_contexts = {}
        self.reload()

    def reload(self):
        """Reload optional JSON context without deleting realtime overlays."""
        self.global_context = {}
        self.code_contexts = {}

        if not self.enabled:
            return

        if self.json_path and os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except Exception as exc:
                self.global_context = {
                    "notes": ["market context load failed: {}".format(exc)]
                }
                data = {}

            self.global_context = data.get("global", {})
            self.code_contexts = data.get("codes", {})
        shared_toss = load_latest_shared_toss_context()
        if shared_toss.get("status") == "ok":
            self.global_context["shared_toss_context"] = shared_toss

    def get_context(self, code):
        context = copy.deepcopy(DEFAULT_MARKET_CONTEXT)

        if not self.enabled:
            return context

        # Merge order matters: defaults < file global < file code < runtime global < runtime code.
        self._deep_update(context, self.global_context)
        self._deep_update(context, self.code_contexts.get(code, {}))
        self._deep_update(context, self.runtime_global_context)
        self._deep_update(context, self.runtime_code_contexts.get(code, {}))

        return context

    def update_code_context(self, code, section, values):
        """Update one context section for a specific symbol."""
        if code not in self.runtime_code_contexts:
            self.runtime_code_contexts[code] = {}

        if section not in self.runtime_code_contexts[code]:
            self.runtime_code_contexts[code][section] = {}

        self.runtime_code_contexts[code][section].update(values)

    def update_global_context(self, section, values):
        """Update one context section that applies to every symbol."""
        if section not in self.runtime_global_context:
            self.runtime_global_context[section] = {}

        self.runtime_global_context[section].update(values)

    def update_orderbook(self, code, orderbook):
        self.update_code_context(code, "orderbook", orderbook)

    def update_short_selling(self, code, short_selling):
        self.update_code_context(code, "short_selling", short_selling)

    def update_credit(self, code, credit):
        self.update_code_context(code, "credit", credit)

    def update_program_trading(self, code, program_trading):
        self.update_code_context(code, "program_trading", program_trading)

    def update_news(self, code, news):
        self.update_code_context(code, "news", news)

    def update_disclosures(self, code, disclosures):
        self.update_code_context(code, "disclosures", disclosures)

    def update_public_reaction(self, code, public_reaction):
        self.update_code_context(code, "public_reaction", public_reaction)

    def update_reference_levels(self, code, reference_levels):
        self.update_code_context(code, "reference_levels", reference_levels)

    def update_market_indices(self, market_indices):
        self.update_global_context("market_indices", market_indices)

    def update_market_status(self, market_status):
        self.update_global_context("market_status", market_status)

    def update_macro_context(self, macro_context):
        self.update_global_context("macro_context", macro_context)

    def update_sector_context(self, code, sector_context):
        self.update_code_context(code, "sector_context", sector_context)

    def _resolve_path(self, path):
        """Resolve relative config paths beside this project file."""
        if not path:
            return None

        if os.path.isabs(path):
            return path

        return os.path.join(os.path.dirname(__file__), path)

    def _deep_update(self, base, update):
        """Recursive dict merge used to preserve nested default keys."""
        for key, value in update.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value


def load_latest_shared_toss_context(shared_db_path=None, limit=12):
    """Load Toss summaries from shared_context.db before using direct fallbacks."""
    db_path = shared_db_path or os.environ.get(
        "SHARED_CONTEXT_DB_PATH",
        r"C:\Users\lmhk2\Documents\New project\shared_market_context\shared_context.db",
    )
    if not db_path or not os.path.exists(db_path):
        return {
            "status": "missing_db",
            "db_path": db_path,
            "sections": {},
            "source_preference": "shared_context_db",
        }
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if not _has_table(conn, "shared_context_snapshots"):
            return {
                "status": "missing_table",
                "db_path": db_path,
                "sections": {},
                "source_preference": "shared_context_db",
            }
        rows = conn.execute("""
            SELECT source, market, symbol, timeframe, section, asof, collected_at,
                   status, staleness_sec, sample_count, payload_json
            FROM shared_context_snapshots
            WHERE source = 'toss'
            ORDER BY collected_at DESC, id DESC
            LIMIT ?
        """, (int(limit),)).fetchall()
        sections = {}
        latest_values = []
        for row in rows:
            payload = _parse_json(row["payload_json"])
            body = payload.get("payload_json") or payload.get("payload") or payload
            sections.setdefault(row["section"], []).append({
                "market": row["market"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "asof": row["asof"],
                "collected_at": row["collected_at"],
                "status": row["status"],
                "sample_count": row["sample_count"],
                "payload": body,
            })
            if row["collected_at"]:
                latest_values.append(row["collected_at"])
        return {
            "status": "ok" if sections else "empty",
            "db_path": db_path,
            "source_preference": "shared_context_db",
            "sections": sections,
            "data_quality": {
                "latest_collected_at": max(latest_values) if latest_values else None,
                "section_count": len(sections),
                "warning": "Toss context comes from shared_context.db; direct project DB reads should remain fallback only.",
            },
            "interpretation_rules": [
                "Toss context is US-market and relationship background, not Kiwoom order evidence.",
                "Short-term event overlays are catalyst context only, not proven correlation.",
                "Daily relationship rows are not intraday timing evidence.",
            ],
        }
    finally:
        conn.close()


def _has_table(conn, table):
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _parse_json(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}
