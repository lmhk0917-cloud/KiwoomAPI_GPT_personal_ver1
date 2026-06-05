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
    _detect_market_flow_events(events, summary, settings)

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
