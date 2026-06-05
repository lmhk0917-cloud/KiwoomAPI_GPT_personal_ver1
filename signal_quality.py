"""Paper-trade feedback based quality adjustments for validation signals."""


def apply_quality_tuning(summary, event_types, action_hint, confidence_score, risk_level, reasons):
    """Down-weight validation patterns that underperformed in paper results."""
    code = str(summary.get("code") or "")

    if action_hint == "WATCH_SUPPORT" and not _has_support_confirmation(summary, event_types):
        confidence_score -= 12
        risk_level = "high"
        reasons.append("VWAP support lacks confirmation from orderbook, MA cross, or multi-timeframe recovery.")
        if confidence_score < 55:
            action_hint = "OBSERVE_EVENT"
            reasons.append("Treat unconfirmed VWAP support as observation until stronger demand appears.")

    if action_hint == "WATCH_MOMENTUM" and event_types == {"CONSECUTIVE_UP_BARS"}:
        confidence_score -= 12
        risk_level = "high"
        reasons.append("Consecutive up bars alone need volume or trend confirmation before momentum validation.")
        if confidence_score < 55:
            action_hint = "OBSERVE_EVENT"

    if code == "000660" and action_hint in ("WATCH_SUPPORT", "WATCH_MOMENTUM"):
        confidence_score -= 8
        risk_level = "high"
        reasons.append("SK hynix support/momentum signals are down-weighted after weak recent paper validation.")
        if confidence_score < 55:
            action_hint = "OBSERVE_EVENT"

    return action_hint, confidence_score, risk_level, reasons


def pullback_stop_loss(current_price, fallback_stop_loss):
    """Give pullback validation room when the setup tends to recover later."""
    if current_price is None:
        return fallback_stop_loss

    wider_stop = round(current_price * 0.99, 2)

    if fallback_stop_loss is None:
        return wider_stop

    return min(fallback_stop_loss, wider_stop)


def _has_support_confirmation(summary, event_types):
    if "ORDERBOOK_BID_IMBALANCE" in event_types:
        return True
    if "MA5_MA20_GOLDEN_CROSS" in event_types:
        return True
    if "RSI_OVERSOLD" in event_types and _count_bullish_timeframes(summary) >= 1:
        return True
    if "CONSECUTIVE_UP_BARS" in event_types and _count_bullish_timeframes(summary) >= 2:
        return True
    return False


def _count_bullish_timeframes(summary):
    timeframes = summary.get("timeframes") or {}
    bullish_timeframes = 0

    for label in ("1m", "3m", "5m"):
        timeframe = timeframes.get(label) or {}
        latest = timeframe.get("latest") or {}
        moving_average = timeframe.get("moving_average") or {}
        vwap = timeframe.get("vwap") or {}
        bullish_votes = 0

        return_1bar = _to_float(latest.get("return_1bar_pct"))
        if return_1bar is not None and return_1bar > 0:
            bullish_votes += 1
        if moving_average.get("price_above_ma5") is True:
            bullish_votes += 1
        if vwap.get("price_above_vwap") is True:
            bullish_votes += 1

        if bullish_votes >= 2:
            bullish_timeframes += 1

    return bullish_timeframes


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
