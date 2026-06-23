"""Rule-based event detection before GPT calls.

The detector is deliberately cheap and deterministic. It decides whether a
symbol is interesting enough to send to GPT, so GPT is used on market events
instead of every timer tick.
"""

from config import (
    EVENT_BOX_HIGH_POSITION,
    EVENT_BOX_LOW_POSITION,
    EVENT_CONSECUTIVE_BARS,
    EVENT_ORDERBOOK_IMBALANCE,
    EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT,
    EVENT_RSI_HIGH,
    EVENT_RSI_LOW,
    EVENT_VOLUME_RATIO,
    EVENT_VWAP_NEAR_PCT,
    ENABLE_MARKET_FLOW_DIRECTION_RISK,
    ENABLE_FORCE_GPT_INTRADAY_EVENT,
    FORCE_GPT_MIN_CONFIRMATIONS,
    FORCE_GPT_RETURN_1BAR_PCT,
    FORCE_GPT_VOLUME_RATIO,
    EVENT_MARKET_CIRCUIT_BREAKER_INFER_PCT,
    EVENT_MARKET_CRASH_MIN_INDEX_COUNT,
    EVENT_MARKET_CRASH_WARNING_PCT,
)


def detect_gpt_events(summary, settings=None):
    """Return all GPT-triggering events found in a symbol summary."""
    timeframe = _get_primary_timeframe(summary)

    if not timeframe:
        return []

    events = []
    _detect_rsi_events(events, timeframe, settings)
    _detect_volume_events(events, timeframe, settings)
    _detect_box_events(events, timeframe, settings)
    _detect_vwap_events(events, timeframe, settings)
    _detect_trend_events(events, timeframe, settings)
    _detect_orderbook_events(events, summary, settings)
    _detect_market_status_events(events, summary)
    _detect_market_index_crash_events(events, summary, settings)
    _detect_market_flow_events(events, summary, settings)
    _detect_force_gpt_intraday_event(events, timeframe, summary, settings)

    return events


def _get_primary_timeframe(summary):
    """Use 1m as the primary signal timeframe, with a fallback for tests."""
    timeframes = summary.get("timeframes")

    if not timeframes:
        return summary

    if timeframes.get("1m"):
        return timeframes["1m"]

    for timeframe_summary in timeframes.values():
        return timeframe_summary

    return None


def _detect_rsi_events(events, timeframe, settings=None):
    """Detect overbought/oversold RSI states."""
    momentum = timeframe.get("momentum", {})
    rsi14 = _to_float(momentum.get("rsi14"))
    rsi_low = _setting(settings, "EVENT_RSI_LOW", EVENT_RSI_LOW)
    rsi_high = _setting(settings, "EVENT_RSI_HIGH", EVENT_RSI_HIGH)

    if rsi14 is None:
        return

    if rsi14 <= rsi_low:
        events.append({
            "type": "RSI_OVERSOLD",
            "timeframe": "1m",
            "message": "RSI oversold area",
            "value": rsi14,
        })
    elif rsi14 >= rsi_high:
        events.append({
            "type": "RSI_OVERBOUGHT",
            "timeframe": "1m",
            "message": "RSI overbought area",
            "value": rsi14,
        })


def _detect_volume_events(events, timeframe, settings=None):
    """Detect volume expansion against short moving averages."""
    volume = timeframe.get("volume", {})
    ratio_5 = _to_float(volume.get("volume_ratio_5"))
    ratio_20 = _to_float(volume.get("volume_ratio_20"))
    volume_ratio_threshold = _setting(settings, "EVENT_VOLUME_RATIO", EVENT_VOLUME_RATIO)
    ratios = [ratio for ratio in (ratio_5, ratio_20) if ratio is not None]

    if not ratios:
        return

    max_ratio = max(ratios)

    if max_ratio >= volume_ratio_threshold:
        events.append({
            "type": "VOLUME_SPIKE",
            "timeframe": "1m",
            "message": "Volume ratio spike",
            "value": round(max_ratio, 3),
        })


def _detect_box_events(events, timeframe, settings=None):
    """Detect price location near the recent range boundaries."""
    box_range = timeframe.get("box_range") or {}
    position = _to_float(box_range.get("current_position_in_box"))
    high_position = _setting(settings, "EVENT_BOX_HIGH_POSITION", EVENT_BOX_HIGH_POSITION)
    low_position = _setting(settings, "EVENT_BOX_LOW_POSITION", EVENT_BOX_LOW_POSITION)

    if position is None:
        return

    if position >= high_position:
        events.append({
            "type": "NEAR_BOX_HIGH",
            "timeframe": "1m",
            "message": "Price near box high",
            "value": position,
        })
    elif position <= low_position:
        events.append({
            "type": "NEAR_BOX_LOW",
            "timeframe": "1m",
            "message": "Price near box low",
            "value": position,
        })


def _detect_vwap_events(events, timeframe, settings=None):
    """Detect price interaction near VWAP."""
    vwap = timeframe.get("vwap", {})
    distance_pct = _to_float(vwap.get("vwap_distance_pct"))
    price_above_vwap = vwap.get("price_above_vwap")
    near_pct = _setting(settings, "EVENT_VWAP_NEAR_PCT", EVENT_VWAP_NEAR_PCT)

    if distance_pct is None:
        return

    if abs(distance_pct) <= near_pct:
        events.append({
            "type": "NEAR_VWAP_SUPPORT" if price_above_vwap else "NEAR_VWAP_RESISTANCE",
            "timeframe": "1m",
            "message": "Price is near VWAP",
            "value": round(distance_pct, 3),
        })


def _detect_trend_events(events, timeframe, settings=None):
    """Detect MA crosses and short consecutive bar movement."""
    trend = timeframe.get("trend", {})
    consecutive_threshold = _setting(settings, "EVENT_CONSECUTIVE_BARS", EVENT_CONSECUTIVE_BARS)

    if trend.get("ma5_crossed_above_ma20"):
        events.append({
            "type": "MA5_MA20_GOLDEN_CROSS",
            "timeframe": "1m",
            "message": "MA5 crossed above MA20",
            "value": None,
        })

    if trend.get("ma5_crossed_below_ma20"):
        events.append({
            "type": "MA5_MA20_DEAD_CROSS",
            "timeframe": "1m",
            "message": "MA5 crossed below MA20",
            "value": None,
        })

    consecutive_up = _to_float(trend.get("consecutive_up_bars"))
    consecutive_down = _to_float(trend.get("consecutive_down_bars"))

    if consecutive_up is not None and consecutive_up >= consecutive_threshold:
        events.append({
            "type": "CONSECUTIVE_UP_BARS",
            "timeframe": "1m",
            "message": "Recent closes are rising consecutively",
            "value": consecutive_up,
        })

    if consecutive_down is not None and consecutive_down >= consecutive_threshold:
        events.append({
            "type": "CONSECUTIVE_DOWN_BARS",
            "timeframe": "1m",
            "message": "Recent closes are falling consecutively",
            "value": consecutive_down,
        })


def _detect_orderbook_events(events, summary, settings=None):
    """Detect strong realtime bid/ask imbalance from market_context."""
    market_context = summary.get("market_context") or {}
    orderbook = market_context.get("orderbook") or {}
    imbalance = _to_float(orderbook.get("bid_ask_imbalance"))
    threshold = _setting(settings, "EVENT_ORDERBOOK_IMBALANCE", EVENT_ORDERBOOK_IMBALANCE)

    if imbalance is None:
        return

    if imbalance >= threshold:
        events.append({
            "type": "ORDERBOOK_BID_IMBALANCE",
            "timeframe": "realtime",
            "message": "Bid side orderbook imbalance",
            "value": imbalance,
        })
    elif imbalance <= -threshold:
        events.append({
            "type": "ORDERBOOK_ASK_IMBALANCE",
            "timeframe": "realtime",
            "message": "Ask side orderbook imbalance",
            "value": imbalance,
        })


def _detect_market_status_events(events, summary):
    """Detect market-wide abnormal states such as sidecar/circuit breaker/VI."""
    market_context = summary.get("market_context") or {}
    market_status = market_context.get("market_status") or {}

    sidecar_status = _normalize_status(market_status.get("sidecar_status"))
    if sidecar_status in ("active", "triggered"):
        direction = market_status.get("sidecar_direction") or "unknown"
        events.append({
            "type": "MARKET_SIDECAR_ACTIVE",
            "timeframe": "market",
            "message": "Market sidecar is active",
            "value": direction,
        })
    elif sidecar_status == "ended":
        direction = market_status.get("sidecar_direction") or "unknown"
        events.append({
            "type": "MARKET_SIDECAR_RECENT",
            "timeframe": "market",
            "message": "Market sidecar occurred earlier in this session",
            "value": {
                "direction": direction,
                "started_at": market_status.get("sidecar_started_at"),
                "ended_at": market_status.get("sidecar_ended_at"),
            },
        })

    circuit_status = _normalize_status(market_status.get("circuit_breaker_status"))
    if circuit_status in ("active", "triggered"):
        events.append({
            "type": "MARKET_CIRCUIT_BREAKER_ACTIVE",
            "timeframe": "market",
            "message": "Market circuit breaker is active",
            "value": market_status.get("market") or "market",
        })

    vi_status = _normalize_status(market_status.get("vi_status"))
    if vi_status in ("active", "triggered"):
        events.append({
            "type": "MARKET_VI_ACTIVE",
            "timeframe": "market",
            "message": "Volatility interruption state is active",
            "value": market_status.get("market") or "market",
        })


def _detect_market_index_crash_events(events, summary, settings=None):
    """Infer market-wide crash/circuit risk from live index snapshots."""
    market_context = summary.get("market_context") or {}
    market_indices = market_context.get("market_indices") or {}
    if not market_indices:
        return

    warning_pct = _to_float(_setting(
        settings,
        "EVENT_MARKET_CRASH_WARNING_PCT",
        EVENT_MARKET_CRASH_WARNING_PCT,
    ))
    circuit_pct = _to_float(_setting(
        settings,
        "EVENT_MARKET_CIRCUIT_BREAKER_INFER_PCT",
        EVENT_MARKET_CIRCUIT_BREAKER_INFER_PCT,
    ))
    min_index_count = _setting(
        settings,
        "EVENT_MARKET_CRASH_MIN_INDEX_COUNT",
        EVENT_MARKET_CRASH_MIN_INDEX_COUNT,
    )
    try:
        min_index_count = max(int(min_index_count), 1)
    except (TypeError, ValueError):
        min_index_count = EVENT_MARKET_CRASH_MIN_INDEX_COUNT

    if warning_pct is None:
        warning_pct = EVENT_MARKET_CRASH_WARNING_PCT
    if circuit_pct is None:
        circuit_pct = EVENT_MARKET_CIRCUIT_BREAKER_INFER_PCT

    index_changes = _market_index_changes(market_indices)
    crash_items = {
        key: value
        for key, value in index_changes.items()
        if value <= warning_pct
    }
    circuit_items = {
        key: value
        for key, value in index_changes.items()
        if value <= circuit_pct
    }

    event_types = {event.get("type") for event in events or []}
    if (
        len(circuit_items) >= min_index_count
        and "MARKET_CIRCUIT_BREAKER_ACTIVE" not in event_types
    ):
        events.append({
            "type": "MARKET_CIRCUIT_BREAKER_ACTIVE",
            "timeframe": "market",
            "message": "Circuit-breaker-level market drop inferred from index snapshots",
            "value": {
                "source": "market_indices",
                "threshold_pct": circuit_pct,
                "indices": circuit_items,
            },
        })
        event_types.add("MARKET_CIRCUIT_BREAKER_ACTIVE")

    if len(crash_items) >= min_index_count and "MARKET_CRASH_RISK" not in event_types:
        events.append({
            "type": "MARKET_CRASH_RISK",
            "timeframe": "market",
            "message": "Broad market crash risk inferred from index snapshots",
            "value": {
                "source": "market_indices",
                "threshold_pct": warning_pct,
                "indices": crash_items,
            },
        })


def _market_index_changes(market_indices):
    changes = {}
    for key in (
        "kospi_change_pct",
        "kospi200_change_pct",
        "kosdaq_change_pct",
        "kosdaq150_change_pct",
        "kospi200_futures_change_pct",
    ):
        value = _to_float(market_indices.get(key))
        if value is not None:
            changes[key] = value
    return changes


def _detect_market_flow_events(events, summary, settings=None):
    """Detect broad sell pressure without assuming unverified OPT10051 units."""
    if not _setting(
        settings,
        "ENABLE_MARKET_FLOW_DIRECTION_RISK",
        ENABLE_MARKET_FLOW_DIRECTION_RISK
    ):
        return

    market_context = summary.get("market_context") or {}
    market_flow = market_context.get("market_investor_flow") or {}
    market_program = market_context.get("market_program_trading") or {}
    benchmark_etfs = market_context.get("benchmark_etfs") or {}

    foreign_net = _to_float(market_flow.get("combined_foreign_net_value"))
    program_net = _to_float(market_program.get("total_net_value"))
    required_weak_count = _setting(
        settings,
        "EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT",
        EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT
    )

    try:
        required_weak_count = max(int(required_weak_count), 0)
    except (TypeError, ValueError):
        required_weak_count = EVENT_MARKET_FLOW_REQUIRE_WEAK_ETF_COUNT

    weak_etf_count = 0
    for item in benchmark_etfs.values():
        snapshot = (item or {}).get("snapshot") or {}
        change_rate = _to_float(snapshot.get("change_rate"))
        if change_rate is not None and change_rate < 0:
            weak_etf_count += 1

    if (
        foreign_net is not None
        and foreign_net < 0
        and program_net is not None
        and program_net < 0
        and weak_etf_count >= required_weak_count
    ):
        events.append({
            "type": "MARKET_FOREIGN_SELL_PRESSURE",
            "timeframe": "market",
            "message": "Foreign selling, program selling, and weak benchmark ETFs align",
            "value": {
                "combined_foreign_net_value": foreign_net,
                "program_net_value": program_net,
                "weak_etf_count": weak_etf_count,
            },
        })


def _detect_force_gpt_intraday_event(events, timeframe, summary, settings=None):
    """Escalate sudden confirmed intraday moves to GPT review."""
    if not _setting(
        settings,
        "ENABLE_FORCE_GPT_INTRADAY_EVENT",
        ENABLE_FORCE_GPT_INTRADAY_EVENT
    ):
        return

    latest = timeframe.get("latest") or {}
    volume = timeframe.get("volume") or {}
    market_context = summary.get("market_context") or {}
    market_indices = market_context.get("market_indices") or {}

    return_threshold = _setting(
        settings,
        "FORCE_GPT_RETURN_1BAR_PCT",
        FORCE_GPT_RETURN_1BAR_PCT
    )
    volume_threshold = _setting(
        settings,
        "FORCE_GPT_VOLUME_RATIO",
        FORCE_GPT_VOLUME_RATIO
    )
    min_confirmations = _setting(
        settings,
        "FORCE_GPT_MIN_CONFIRMATIONS",
        FORCE_GPT_MIN_CONFIRMATIONS
    )

    try:
        min_confirmations = max(int(min_confirmations), 1)
    except (TypeError, ValueError):
        min_confirmations = FORCE_GPT_MIN_CONFIRMATIONS

    return_threshold = _to_float(return_threshold)
    if return_threshold is None:
        return_threshold = FORCE_GPT_RETURN_1BAR_PCT

    volume_threshold = _to_float(volume_threshold)
    if volume_threshold is None:
        volume_threshold = FORCE_GPT_VOLUME_RATIO

    return_1bar_pct = _to_float(latest.get("return_1bar_pct"))
    ratio_5 = _to_float(volume.get("volume_ratio_5"))
    ratio_20 = _to_float(volume.get("volume_ratio_20"))
    ratios = [ratio for ratio in (ratio_5, ratio_20) if ratio is not None]
    max_volume_ratio = max(ratios) if ratios else None

    confirmation_reasons = []
    if return_1bar_pct is not None and abs(return_1bar_pct) >= return_threshold:
        confirmation_reasons.append("rapid_price_move")
    if max_volume_ratio is not None and max_volume_ratio >= volume_threshold:
        confirmation_reasons.append("volume_expansion")

    event_types = {event.get("type") for event in events or []}
    confirming_event_types = {
        "VOLUME_SPIKE",
        "NEAR_BOX_HIGH",
        "NEAR_BOX_LOW",
        "MA5_MA20_GOLDEN_CROSS",
        "MA5_MA20_DEAD_CROSS",
        "CONSECUTIVE_UP_BARS",
        "CONSECUTIVE_DOWN_BARS",
        "MARKET_FOREIGN_SELL_PRESSURE",
    }
    if confirming_event_types.intersection(event_types):
        confirmation_reasons.append("technical_or_flow_event")

    for key in ("kospi200_change_pct", "kosdaq150_change_pct"):
        index_change = _to_float(market_indices.get(key))
        if index_change is not None and abs(index_change) >= return_threshold:
            confirmation_reasons.append("market_index_move")
            break

    if len(set(confirmation_reasons)) < min_confirmations:
        return

    events.append({
        "type": "FORCE_GPT_INTRADAY_EVENT",
        "timeframe": "1m",
        "message": "Sudden intraday move with confirmation; force GPT review",
        "value": {
            "return_1bar_pct": return_1bar_pct,
            "max_volume_ratio": max_volume_ratio,
            "confirmations": sorted(set(confirmation_reasons)),
        },
    })


def _to_float(value):
    """Best-effort conversion for event thresholds."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _setting(settings, key, default):
    if not settings:
        return default
    return settings.get(key, default)


def _normalize_status(value):
    if value is None:
        return ""
    return str(value).strip().lower()
