"""Compress analysis summaries before sending them to GPT.

SQLite keeps the detailed raw evidence. GPT only needs a compact, decision
oriented payload so token cost and response latency stay controlled.
"""

import copy
import json

import config


TEXT_LIMIT = config.GPT_INPUT_MAX_TEXT_CHARS


def compress_market_summaries_for_gpt(market_summaries, settings=None):
    """Return compressed summaries and simple size statistics."""
    global TEXT_LIMIT
    TEXT_LIMIT = _setting(settings, "GPT_INPUT_MAX_TEXT_CHARS", config.GPT_INPUT_MAX_TEXT_CHARS)

    original_json = _to_json(market_summaries, indent=2)

    if not _setting(settings, "ENABLE_GPT_INPUT_COMPRESSION", config.ENABLE_GPT_INPUT_COMPRESSION):
        return market_summaries, {
            "enabled": False,
            "symbol_count": len(market_summaries or []),
            "original_json_chars": len(original_json),
            "compressed_json_chars": len(original_json),
            "compression_ratio": 1.0,
        }

    compressed = [
        compress_summary(
            summary,
            settings=settings,
            include_global_context=(index == 0)
        )
        for index, summary in enumerate(market_summaries or [])
    ]
    compressed_json = _to_json(compressed, compact=True)
    ratio = _ratio(len(compressed_json), len(original_json))

    return compressed, {
        "enabled": True,
        "symbol_count": len(compressed),
        "original_json_chars": len(original_json),
        "compressed_json_chars": len(compressed_json),
        "compression_ratio": ratio,
    }


def compress_summary(summary, settings=None, include_global_context=True):
    """Compress one symbol summary for GPT input."""
    recent_points = _setting(settings, "GPT_INPUT_RECENT_POINTS", config.GPT_INPUT_RECENT_POINTS)

    compressed = {
        "code": summary.get("code"),
        "name": summary.get("name"),
        "market_snapshot": _compact_dict(summary.get("market_snapshot"), [
            "trade_time",
            "current_price",
            "change_rate",
            "acc_volume",
            "day_open",
            "day_high",
            "day_low",
            "strength",
            "received_at",
        ]),
        "events": _compress_events(summary.get("events")),
        "validation_signal": _compress_validation_signal(summary.get("validation_signal"), settings),
        "timeframes": _compress_timeframes(summary.get("timeframes"), recent_points),
        "cost_context": _build_cost_context(summary, settings),
        "market_context": _compress_market_context(
            summary.get("market_context"),
            settings,
            include_global_context=include_global_context
        ),
        "historical_price_context": _compress_historical_price_context(summary.get("historical_price_context")),
        "historical_signal_stats": _compress_signal_stats(summary.get("historical_signal_stats"), settings),
    }

    return _drop_empty(compressed)


def _compress_timeframes(timeframes, recent_points):
    result = {}

    for label in ("1m", "3m", "5m"):
        timeframe = (timeframes or {}).get(label)
        if not timeframe:
            continue

        result[label] = _drop_empty({
            "bar_count": timeframe.get("bar_count"),
            "latest": _compact_dict(timeframe.get("latest"), [
                "time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "return_1bar_pct",
            ]),
            "moving_average": _compact_dict(timeframe.get("moving_average"), [
                "ma5",
                "ma20",
                "ma60",
                "price_above_ma5",
                "price_above_ma20",
                "price_above_ma60",
                "ma5_distance_pct",
                "ma20_distance_pct",
                "ma60_distance_pct",
            ]),
            "momentum": _compact_dict(timeframe.get("momentum"), [
                "rsi14",
                "macd",
                "macd_signal",
                "macd_hist",
                "macd_hist_rising",
            ]),
            "volume": _compact_dict(timeframe.get("volume"), [
                "volume_ma5",
                "volume_ma20",
                "volume_ratio_5",
                "volume_ratio_20",
            ]),
            "vwap": _compact_dict(timeframe.get("vwap"), [
                "vwap",
                "vwap_distance_pct",
                "price_above_vwap",
            ]),
            "trend": _compact_dict(timeframe.get("trend"), [
                "ma5_crossed_above_ma20",
                "ma5_crossed_below_ma20",
                "macd_crossed_above_signal",
                "macd_crossed_below_signal",
                "consecutive_up_bars",
                "consecutive_down_bars",
            ]),
            "volatility": _compact_dict(timeframe.get("volatility"), [
                "atr14",
                "atr14_pct",
                "bb_mid",
                "bb_upper",
                "bb_lower",
                "bb_width_pct",
                "bb_position",
                "price_above_bb_upper",
                "price_below_bb_lower",
            ]),
            "box_range": _compact_dict(timeframe.get("box_range"), [
                "box_high",
                "box_low",
                "box_mid",
                "current_price",
                "current_position_in_box",
                "is_near_box_high",
                "is_near_box_low",
            ]),
            "recent_closes": _tail(timeframe.get("recent_closes"), recent_points),
            "recent_volumes": _tail(timeframe.get("recent_volumes"), recent_points),
        })

    return result


def _compress_market_context(context, settings=None, include_global_context=True):
    context = context or {}
    max_items = _setting(settings, "GPT_INPUT_MAX_CONTEXT_ITEMS", config.GPT_INPUT_MAX_CONTEXT_ITEMS)

    result = {
        "sector_context": _compress_sector_context(context.get("sector_context"), max_items),
        "reference_levels": _compact_dict(context.get("reference_levels"), [
            "previous_close",
            "previous_high",
            "previous_low",
            "today_open_gap_pct",
            "recent_20d_high",
            "recent_20d_low",
            "distance_from_20d_high_pct",
            "distance_from_20d_low_pct",
        ]),
        "short_selling": _compact_dict(context.get("short_selling"), [
            "date",
            "short_sale_ratio_pct",
            "short_balance_ratio_pct",
            "stock_loan_change_qty",
            "stock_loan_balance_qty",
            "source",
            "asof",
        ]),
        "credit": _compact_dict(context.get("credit"), [
            "date",
            "credit_balance_qty",
            "credit_balance_ratio_pct",
            "credit_balance_change_qty",
            "loan_balance_qty",
            "source",
            "asof",
        ]),
        "investor_flow": _compact_dict(context.get("investor_flow"), [
            "date",
            "individual_net_value",
            "foreign_net_value",
            "institution_net_value",
            "source",
            "asof",
        ]),
        "orderbook": _compact_dict(context.get("orderbook"), [
            "best_bid",
            "best_ask",
            "spread_pct",
            "total_bid_qty",
            "total_ask_qty",
            "bid_ask_imbalance",
        ]),
        "program_trading": _compact_dict(context.get("program_trading"), [
            "program_net_value",
            "program_buy_value",
            "program_sell_value",
            "asof",
            "source",
        ]),
        "news": _compress_text_context(context.get("news"), max_items),
        "disclosures": _compress_text_context(context.get("disclosures"), max_items),
        "public_reaction": _compress_text_context(context.get("public_reaction"), max_items),
        "notes": _head(context.get("notes"), max_items),
    }

    if include_global_context:
        result.update({
            "market_status": _compact_dict(context.get("market_status"), [
            "asof",
            "market",
            "market_phase",
            "sidecar_status",
            "sidecar_direction",
            "sidecar_started_at",
            "sidecar_ended_at",
            "circuit_breaker_status",
            "vi_status",
            "summary",
            "source",
            "reliability",
            ]),
            "macro_context": _compress_macro_context(context.get("macro_context"), max_items),
            "market_indices": _compact_dict(context.get("market_indices"), [
            "kospi",
            "kospi_change_pct",
            "kosdaq",
            "kosdaq_change_pct",
            "kospi200",
            "kospi200_change_pct",
            "usd_krw",
            "usd_krw_change_pct",
            ]),
            "market_investor_flow": _compact_dict(context.get("market_investor_flow"), [
            "kospi_sector_count",
            "kospi_individual_net_value",
            "kospi_foreign_net_value",
            "kospi_institution_net_value",
            "kosdaq_sector_count",
            "kosdaq_individual_net_value",
            "kosdaq_foreign_net_value",
            "kosdaq_institution_net_value",
            "combined_foreign_net_value",
            "combined_institution_net_value",
            "combined_individual_net_value",
            "reliability",
            "asof",
            "source",
            ]),
            "benchmark_etfs": _compress_benchmark_etfs(context.get("benchmark_etfs"), max_items),
            "derivatives": _compact_dict(context.get("derivatives"), [
            "kospi200_futures_price",
            "kospi200_futures_change_pct",
            "basis",
            "theoretical_basis",
            "futures_volume",
            "open_interest",
            "foreign_futures_net_contracts",
            "institution_futures_net_contracts",
            "option_month",
            "call_option_volume",
            "put_option_volume",
            "call_option_open_interest",
            "put_option_open_interest",
            "put_call_ratio",
            "put_call_open_interest_ratio",
            "call_implied_volatility_avg",
            "put_implied_volatility_avg",
            "implied_volatility",
            "source",
            "asof",
            ]),
            "market_program_trading": _compact_dict(context.get("market_program_trading"), [
            "market",
            "time",
            "date",
            "arbitrage_net_value",
            "non_arbitrage_net_value",
            "total_net_value",
            "kospi200",
            "basis",
            "source",
            "asof",
            ]),
            "data_quality": _compress_data_quality(context.get("data_quality"), max_items),
        })

    return _drop_empty(result)


def _build_cost_context(summary, settings=None):
    """Calculate approximate fee/tax/slippage impact for GPT scenarios."""
    entry_price = _pick_entry_price(summary)
    signal = summary.get("validation_signal") or {}
    target_1 = _to_float(signal.get("target_1"))
    target_2 = _to_float(signal.get("target_2"))
    stop_loss = _to_float(signal.get("stop_loss"))

    buy_fee_pct = _to_float(_setting(settings, "TRADE_BUY_FEE_PCT", config.TRADE_BUY_FEE_PCT)) or 0.0
    sell_fee_pct = _to_float(_setting(settings, "TRADE_SELL_FEE_PCT", config.TRADE_SELL_FEE_PCT)) or 0.0
    sell_tax_pct = _to_float(_setting(settings, "TRADE_SELL_TAX_PCT", config.TRADE_SELL_TAX_PCT)) or 0.0
    slippage_pct = _to_float(_setting(settings, "TRADE_SLIPPAGE_PCT", config.TRADE_SLIPPAGE_PCT)) or 0.0
    round_trip_cost_pct = round(
        buy_fee_pct + sell_fee_pct + sell_tax_pct + (slippage_pct * 2),
        4
    )

    result = {
        "entry_price": _price_value(entry_price),
        "entry_price_krw_text": _price_text(entry_price),
        "assumptions_pct": {
            "buy_fee": buy_fee_pct,
            "sell_fee": sell_fee_pct,
            "sell_tax": sell_tax_pct,
            "slippage_per_side": slippage_pct,
            "round_trip_total": round_trip_cost_pct,
        },
        "note": "Approximate analysis cost. Edit app_settings to match the broker/account.",
    }

    if entry_price is None:
        return result

    breakeven_price = _price_after_pct(entry_price, round_trip_cost_pct)
    result.update({
        "breakeven_exit_price": _price_value(breakeven_price),
        "breakeven_exit_price_krw_text": _price_text(breakeven_price),
        "target_1": _cost_adjusted_level(entry_price, target_1, round_trip_cost_pct),
        "target_2": _cost_adjusted_level(entry_price, target_2, round_trip_cost_pct),
        "stop_loss": _cost_adjusted_level(entry_price, stop_loss, round_trip_cost_pct),
    })

    return _drop_empty(result)


def _pick_entry_price(summary):
    signal = summary.get("validation_signal") or {}
    signal_price = _to_float(signal.get("current_price"))
    if signal_price is not None:
        return signal_price

    market_snapshot = summary.get("market_snapshot") or {}
    snapshot_price = _to_float(market_snapshot.get("current_price"))
    if snapshot_price is not None:
        return snapshot_price

    timeframes = summary.get("timeframes") or {}
    for label in ("1m", "3m", "5m"):
        close = _to_float(((timeframes.get(label) or {}).get("latest") or {}).get("close"))
        if close is not None:
            return close

    return None


def _cost_adjusted_level(entry_price, exit_price, round_trip_cost_pct):
    if entry_price in (None, 0) or exit_price is None:
        return None

    gross_return_pct = round((exit_price - entry_price) / entry_price * 100, 3)
    net_return_pct = round(gross_return_pct - round_trip_cost_pct, 3)

    return {
        "price": _price_value(exit_price),
        "price_krw_text": _price_text(exit_price),
        "gross_return_pct": gross_return_pct,
        "net_return_after_cost_pct": net_return_pct,
    }


def _price_after_pct(price, pct):
    if price is None:
        return None
    return round(price * (1 + pct / 100.0), 2)


def _price_value(price):
    """Return a stable KRW price number without meaningless decimals."""
    value = _to_float(price)
    if value is None:
        return None
    return int(round(value))


def _price_text(price):
    """Return an explicit display string so GPT does not shift price digits."""
    value = _price_value(price)
    if value is None:
        return None
    if isinstance(value, int):
        return "{:,} KRW".format(value)
    return "{:,} KRW".format(int(round(value)))


def _compress_sector_context(section, max_items):
    return _drop_empty({
        "sector_name": (section or {}).get("sector_name"),
        "sector_change_pct": (section or {}).get("sector_change_pct"),
        "relative_strength_vs_sector_pct": (section or {}).get("relative_strength_vs_sector_pct"),
        "peer_movers": _head((section or {}).get("peer_movers"), max_items),
    })


def _compress_macro_context(section, max_items):
    section = section or {}
    return _drop_empty({
        "asof": section.get("asof"),
        "source": section.get("source"),
        "reliability": section.get("reliability"),
        "summary": _truncate_text(section.get("summary")),
        "risk_regime": section.get("risk_regime"),
        "risk_regime_reason": _truncate_text(section.get("risk_regime_reason")),
        "kr_base_rate": section.get("kr_base_rate"),
        "kr_base_rate_change_bp": section.get("kr_base_rate_change_bp"),
        "us_fed_funds_rate": section.get("us_fed_funds_rate"),
        "us_10y_yield": section.get("us_10y_yield"),
        "us_10y_yield_change_bp": section.get("us_10y_yield_change_bp"),
        "usd_krw": section.get("usd_krw"),
        "usd_krw_change_pct": section.get("usd_krw_change_pct"),
        "dxy": section.get("dxy"),
        "dxy_change_pct": section.get("dxy_change_pct"),
        "vix": section.get("vix"),
        "vix_change_pct": section.get("vix_change_pct"),
        "sp500_futures_change_pct": section.get("sp500_futures_change_pct"),
        "nasdaq_futures_change_pct": section.get("nasdaq_futures_change_pct"),
        "nikkei_change_pct": section.get("nikkei_change_pct"),
        "hangseng_change_pct": section.get("hangseng_change_pct"),
        "wti_change_pct": section.get("wti_change_pct"),
        "gold_change_pct": section.get("gold_change_pct"),
        "semiconductor_index_change_pct": section.get("semiconductor_index_change_pct"),
        "next_macro_events": _head(section.get("next_macro_events"), max_items),
        "notes": _head(section.get("notes"), max_items),
    })


def _compress_benchmark_etfs(section, max_items):
    result = {}
    if not isinstance(section, dict):
        return result

    for code, payload in list(section.items())[:max(int(max_items), 0)]:
        payload = payload or {}
        snapshot = payload.get("snapshot") or payload
        result[code] = _drop_empty({
            "name": payload.get("name") or snapshot.get("name"),
            "snapshot": _compact_dict(snapshot, [
                "current_price",
                "change_rate",
                "acc_volume",
                "strength",
                "received_at",
                "asof",
            ]),
        })
    return _drop_empty(result)


def _compress_data_quality(section, max_items):
    section = section or {}
    return _drop_empty({
        "tick_last_received_at": section.get("tick_last_received_at"),
        "orderbook_last_received_at": section.get("orderbook_last_received_at"),
        "program_trading_last_received_at": section.get("program_trading_last_received_at"),
        "market_program_trading_last_received_at": section.get("market_program_trading_last_received_at"),
        "short_selling_last_received_at": section.get("short_selling_last_received_at"),
        "credit_last_received_at": section.get("credit_last_received_at"),
        "investor_flow_last_received_at": section.get("investor_flow_last_received_at"),
        "market_indices_last_received_at": section.get("market_indices_last_received_at"),
        "market_investor_flow_last_received_at": section.get("market_investor_flow_last_received_at"),
        "derivatives_last_received_at": section.get("derivatives_last_received_at"),
        "macro_context_last_checked_at": section.get("macro_context_last_checked_at"),
        "news_last_checked_at": section.get("news_last_checked_at"),
        "disclosure_last_checked_at": section.get("disclosure_last_checked_at"),
        "public_reaction_last_checked_at": section.get("public_reaction_last_checked_at"),
        "missing_sections": _head(section.get("missing_sections"), max_items),
    })


def _compress_text_context(section, max_items):
    section = section or {}
    items = []

    for item in _head(section.get("items"), max_items):
        if isinstance(item, dict):
            items.append(_compact_dict(item, [
                "published_at",
                "date",
                "time",
                "source",
                "title",
                "headline",
                "summary",
                "sentiment",
                "materiality",
            ]))
        else:
            items.append(_truncate_text(item))

    return _drop_empty({
        "asof": section.get("asof"),
        "summary": _truncate_text(section.get("summary")),
        "sentiment": section.get("sentiment"),
        "materiality": section.get("materiality"),
        "source_count": section.get("source_count"),
        "dominant_topics": _head(section.get("dominant_topics"), max_items),
        "sample_size": section.get("sample_size"),
        "weight": section.get("weight"),
        "source": section.get("source"),
        "reliability": section.get("reliability"),
        "items": _drop_empty_list(items),
    })


def _compress_historical_price_context(context):
    result = {}

    for label in ("daily", "minute_1m", "minute_3m", "minute_5m"):
        section = (context or {}).get(label)
        if not section:
            continue

        result[label] = _compact_dict(section, [
            "timeframe",
            "sample_size",
            "oldest_bar_time",
            "latest_bar_time",
            "latest_close",
            "return_1bar_pct",
            "return_5bar_pct",
            "return_20bar_pct",
            "ma5",
            "ma20",
            "price_above_ma5",
            "price_above_ma20",
            "ma5_distance_pct",
            "ma20_distance_pct",
            "high_20bar",
            "low_20bar",
            "high_60bar",
            "low_60bar",
            "distance_from_20bar_high_pct",
            "distance_from_20bar_low_pct",
            "avg_volume_5bar",
            "avg_volume_20bar",
            "volume_ratio_5bar",
            "volume_ratio_20bar",
            "note",
        ])

    return result


def _compress_signal_stats(stats, settings=None):
    stats = stats or {}
    max_action_stats = _setting(settings, "GPT_INPUT_MAX_ACTION_STATS", config.GPT_INPUT_MAX_ACTION_STATS)
    include_recent_signals = _setting(
        settings,
        "GPT_INPUT_INCLUDE_RECENT_SIGNALS",
        config.GPT_INPUT_INCLUDE_RECENT_SIGNALS
    )
    max_recent_signals = _setting(settings, "GPT_INPUT_MAX_RECENT_SIGNALS", config.GPT_INPUT_MAX_RECENT_SIGNALS)

    action_stats = []
    for item in _head(stats.get("action_stats"), max_action_stats):
        action_stats.append(_compact_dict(item, [
            "action_hint",
            "sample_size",
            "evaluated_count",
            "avg_return_30m_pct",
            "avg_return_60m_pct",
            "win_rate_30m_pct",
            "win_rate_60m_pct",
            "target_1_hit_rate_pct",
            "target_2_hit_rate_pct",
            "stop_loss_hit_rate_pct",
            "outcome_counts",
        ]))

    recent_signals = []
    if include_recent_signals:
        for item in _head(stats.get("recent_signals"), max_recent_signals):
            recent_signals.append(_compact_dict(item, [
                "detected_at",
                "action_hint",
                "confidence_score",
                "risk_level",
                "return_30m_pct",
                "return_60m_pct",
                "target_1_hit",
                "target_2_hit",
                "stop_loss_hit",
                "outcome_label",
            ]))

    return _drop_empty({
        "asof": stats.get("asof"),
        "sample_size": stats.get("sample_size"),
        "evaluated_count": stats.get("evaluated_count"),
        "tradeable_long_actions": stats.get("tradeable_long_actions"),
        "avg_return_30m_pct": stats.get("avg_return_30m_pct"),
        "avg_return_60m_pct": stats.get("avg_return_60m_pct"),
        "win_rate_30m_pct": stats.get("win_rate_30m_pct"),
        "win_rate_60m_pct": stats.get("win_rate_60m_pct"),
        "target_1_hit_rate_pct": stats.get("target_1_hit_rate_pct"),
        "target_2_hit_rate_pct": stats.get("target_2_hit_rate_pct"),
        "stop_loss_hit_rate_pct": stats.get("stop_loss_hit_rate_pct"),
        "action_stats": _drop_empty_list(action_stats),
        "recent_signals": _drop_empty_list(recent_signals),
        "learning_feedback": _compress_learning_feedback(stats.get("learning_feedback")),
        "note": stats.get("note"),
    })


def _compress_learning_feedback(feedback):
    feedback = feedback or {}
    return _drop_empty({
        "regime_note": feedback.get("regime_note"),
        "guidance": feedback.get("guidance"),
        "quant_snapshot": _compress_quant_snapshot(feedback.get("quant_snapshot")),
        "avoid_actions": _drop_empty_list([
            _compact_dict(item, [
                "action_hint",
                "evaluated_count",
                "avg_return_60m_pct",
                "win_rate_60m_pct",
                "stop_loss_hit_rate_pct",
                "adjustment",
            ])
            for item in _head(feedback.get("avoid_actions"), 5)
        ]),
        "prefer_actions": _drop_empty_list([
            _compact_dict(item, [
                "action_hint",
                "evaluated_count",
                "avg_return_60m_pct",
                "win_rate_60m_pct",
                "adjustment",
            ])
            for item in _head(feedback.get("prefer_actions"), 3)
        ]),
    })


def _compress_quant_snapshot(snapshot):
    snapshot = snapshot or {}
    guidance = snapshot.get("guidance") or {}
    return _drop_empty({
        "generated_at": snapshot.get("generated_at"),
        "window_start": snapshot.get("window_start"),
        "overview": _compact_dict(snapshot.get("overview"), [
            "signal_count",
            "evaluated_count",
            "avg_net_return_60m_pct",
            "profit_factor_60m",
            "expectancy_60m_pct",
            "stop_loss_hit_rate_pct",
        ]),
        "label": guidance.get("label"),
        "summary": guidance.get("summary"),
        "avoid_actions": _drop_empty_list([
            _compact_dict(item, [
                "action_hint",
                "evaluated_count",
                "avg_net_return_60m_pct",
                "win_rate_60m_pct",
                "profit_factor_60m",
                "adjustment",
            ])
            for item in _head(guidance.get("avoid_actions"), 3)
        ]),
        "prefer_actions": _drop_empty_list([
            _compact_dict(item, [
                "action_hint",
                "evaluated_count",
                "avg_net_return_60m_pct",
                "win_rate_60m_pct",
                "profit_factor_60m",
                "adjustment",
            ])
            for item in _head(guidance.get("prefer_actions"), 2)
        ]),
    })


def _compress_events(events):
    result = []
    for event in events or []:
        result.append(_compact_dict(event, ["type", "timeframe", "message", "value"]))
    return _drop_empty_list(result)


def _compress_validation_signal(signal, settings=None):
    if not signal:
        return None

    max_items = _setting(settings, "GPT_INPUT_MAX_CONTEXT_ITEMS", config.GPT_INPUT_MAX_CONTEXT_ITEMS)
    return _drop_empty({
        "action_hint": signal.get("action_hint"),
        "confidence_score": signal.get("confidence_score"),
        "risk_level": signal.get("risk_level"),
        "current_price": signal.get("current_price"),
        "stop_loss": signal.get("stop_loss"),
        "target_1": signal.get("target_1"),
        "target_2": signal.get("target_2"),
        "reasons": _head(signal.get("reasons"), max_items),
    })


def _compact_dict(source, keys):
    source = source or {}
    result = {}

    for key in keys:
        if key not in source:
            continue
        value = source.get(key)
        if not _has_value(value):
            continue
        result[key] = _truncate_text(value)

    return result


def _drop_empty(value):
    if not isinstance(value, dict):
        return value

    result = {}
    for key, item in value.items():
        if not _has_value(item):
            continue
        result[key] = item
    return result


def _drop_empty_list(values):
    return [value for value in values or [] if _has_value(value)]


def _head(values, count):
    if not isinstance(values, list):
        return []
    return [_truncate_text(copy.deepcopy(value)) for value in values[:max(int(count), 0)]]


def _tail(values, count):
    if not isinstance(values, list):
        return []
    count = max(int(count), 0)
    if count == 0:
        return []
    return [_truncate_text(copy.deepcopy(value)) for value in values[-count:]]


def _truncate_text(value):
    if not isinstance(value, str):
        return value

    limit = TEXT_LIMIT
    if len(value) <= limit:
        return value

    return value[:limit] + "..."


def _setting(settings, key, default):
    if not settings or key not in settings:
        return default
    return settings.get(key)


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_value(value):
    if value is None:
        return False
    if value == "":
        return False
    if value == []:
        return False
    if value == {}:
        return False
    return True


def _to_json(value, indent=None, compact=False):
    if compact:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return json.dumps(value, ensure_ascii=False, indent=indent, default=str)


def _ratio(compressed_chars, original_chars):
    if not original_chars:
        return None
    return round(float(compressed_chars) / float(original_chars), 4)
