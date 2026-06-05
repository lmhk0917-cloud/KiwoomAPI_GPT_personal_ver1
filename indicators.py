"""Tick-to-bar conversion and technical indicator summaries.

All GPT/event decisions should use completed candles by default. The
``drop_last`` option removes the still-forming candle so intrabar noise does
not look like a confirmed 1/3/5-minute signal.
"""

import pandas as pd
import numpy as np


def ticks_to_dataframe(ticks):
    """Convert raw tick dictionaries into a sorted pandas DataFrame."""
    df = pd.DataFrame(ticks)

    if df.empty:
        return df

    df["received_at"] = pd.to_datetime(df["received_at"])
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["tick_volume"] = pd.to_numeric(df["tick_volume"], errors="coerce")

    df = df.dropna(subset=["received_at", "price"])
    df = df.sort_values("received_at")

    return df


def make_ohlcv_from_ticks(ticks, interval="1min", drop_last=True):
    """Aggregate ticks into OHLCV bars for a pandas resample interval."""
    df = ticks_to_dataframe(ticks)

    if df.empty:
        return pd.DataFrame()

    df = df.set_index("received_at")

    ohlcv = df.resample(interval).agg({
        "price": ["first", "max", "min", "last"],
        "tick_volume": "sum"
    })

    ohlcv.columns = ["open", "high", "low", "close", "volume"]
    ohlcv = ohlcv.dropna()

    # 현재 진행 중인 미완성 봉 제거.
    if drop_last and len(ohlcv) > 1:
        ohlcv = ohlcv.iloc[:-1]

    return ohlcv


def calculate_rsi(close, period=14):
    """Calculate a simple rolling RSI."""
    delta = close.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_macd(close, fast=12, slow=26, signal=9):
    """Calculate MACD line, signal line, and histogram."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_atr(df, period=14):
    """Calculate Average True Range for intraday volatility checks."""
    previous_close = df["close"].shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)

    return true_range.rolling(period).mean()


def add_bollinger_bands(df, period=20, std_multiplier=2):
    """Add Bollinger Band columns based on closing price."""
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = mid + (std * std_multiplier)
    lower = mid - (std * std_multiplier)

    df["bb_mid"] = mid
    df["bb_upper"] = upper
    df["bb_lower"] = lower
    df["bb_width_pct"] = (upper - lower) / mid.replace(0, np.nan) * 100
    df["bb_position"] = (df["close"] - lower) / (upper - lower).replace(0, np.nan)

    return df


def add_indicators(ohlcv):
    """Add moving averages, RSI, MACD, volatility, returns, and VWAP."""
    if ohlcv.empty:
        return ohlcv

    df = ohlcv.copy()

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma5_distance_pct"] = _distance_pct(df["close"], df["ma5"])
    df["ma20_distance_pct"] = _distance_pct(df["close"], df["ma20"])
    df["ma60_distance_pct"] = _distance_pct(df["close"], df["ma60"])

    df["rsi14"] = calculate_rsi(df["close"], 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = calculate_macd(df["close"])
    df["macd_hist_prev"] = df["macd_hist"].shift(1)

    df["volume_ma5"] = df["volume"].rolling(5).mean()
    df["volume_ma20"] = df["volume"].rolling(20).mean()

    df["volume_ratio_5"] = df["volume"] / df["volume_ma5"]
    df["volume_ratio_20"] = df["volume"] / df["volume_ma20"]

    df["return_1bar_pct"] = df["close"].pct_change() * 100
    df["atr14"] = calculate_atr(df, 14)
    df["atr14_pct"] = df["atr14"] / df["close"].replace(0, np.nan) * 100
    df = add_bollinger_bands(df, period=20, std_multiplier=2)

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    volume_sum = df["volume"].cumsum().replace(0, np.nan)
    df["vwap"] = (typical_price * df["volume"]).cumsum() / volume_sum
    df["vwap_distance_pct"] = (df["close"] - df["vwap"]) / df["vwap"] * 100

    return df


def _distance_pct(value, base):
    """Return percentage distance from a reference series."""
    return (value - base) / base.replace(0, np.nan) * 100


def estimate_box_range(df, lookback=30):
    """Estimate the recent range box and current position inside it."""
    if df.empty or len(df) < 5:
        return None

    recent = df.tail(min(lookback, len(df)))

    box_high = recent["high"].max()
    box_low = recent["low"].min()
    box_mid = (box_high + box_low) / 2
    current = recent["close"].iloc[-1]

    if box_high == box_low:
        position = None
    else:
        position = (current - box_low) / (box_high - box_low)

    return {
        "box_high": round(float(box_high), 2),
        "box_low": round(float(box_low), 2),
        "box_mid": round(float(box_mid), 2),
        "current_price": round(float(current), 2),
        "current_position_in_box": round(float(position), 3) if position is not None else None,
        "is_near_box_high": bool(current >= box_high * 0.995),
        "is_near_box_low": bool(current <= box_low * 1.005),
        "box_width_pct": round(float((box_high - box_low) / box_mid * 100), 3) if box_mid != 0 else None,
    }


def summarize_for_gpt(code, name, indicator_df):
    """Create a compact per-timeframe summary for GPT and event detection."""
    if indicator_df.empty or len(indicator_df) < 5:
        return None

    latest = indicator_df.iloc[-1]
    prev = indicator_df.iloc[-2] if len(indicator_df) >= 2 else latest

    box = estimate_box_range(indicator_df, lookback=30)

    summary = {
        "code": code,
        "name": name,
        "latest": {
            "close": round(float(latest["close"]), 2),
            "open": round(float(latest["open"]), 2),
            "high": round(float(latest["high"]), 2),
            "low": round(float(latest["low"]), 2),
            "volume": round(float(latest["volume"]), 2),
            "return_1bar_pct": round(float(latest["return_1bar_pct"]), 3)
            if pd.notna(latest["return_1bar_pct"]) else None,
        },
        "moving_average": {
            "ma5": round(float(latest["ma5"]), 2) if pd.notna(latest["ma5"]) else None,
            "ma20": round(float(latest["ma20"]), 2) if pd.notna(latest["ma20"]) else None,
            "ma60": round(float(latest["ma60"]), 2) if pd.notna(latest["ma60"]) else None,
            "price_above_ma5": bool(latest["close"] > latest["ma5"]) if pd.notna(latest["ma5"]) else None,
            "price_above_ma20": bool(latest["close"] > latest["ma20"]) if pd.notna(latest["ma20"]) else None,
            "price_above_ma60": bool(latest["close"] > latest["ma60"]) if pd.notna(latest["ma60"]) else None,
            "ma5_distance_pct": round(float(latest["ma5_distance_pct"]), 3)
            if pd.notna(latest["ma5_distance_pct"]) else None,
            "ma20_distance_pct": round(float(latest["ma20_distance_pct"]), 3)
            if pd.notna(latest["ma20_distance_pct"]) else None,
            "ma60_distance_pct": round(float(latest["ma60_distance_pct"]), 3)
            if pd.notna(latest["ma60_distance_pct"]) else None,
        },
        "momentum": {
            "rsi14": round(float(latest["rsi14"]), 2) if pd.notna(latest["rsi14"]) else None,
            "rsi_prev": round(float(prev["rsi14"]), 2) if pd.notna(prev["rsi14"]) else None,
            "rsi_rising": bool(latest["rsi14"] > prev["rsi14"])
            if pd.notna(latest["rsi14"]) and pd.notna(prev["rsi14"]) else None,
            "macd": round(float(latest["macd"]), 3) if pd.notna(latest["macd"]) else None,
            "macd_signal": round(float(latest["macd_signal"]), 3) if pd.notna(latest["macd_signal"]) else None,
            "macd_hist": round(float(latest["macd_hist"]), 3) if pd.notna(latest["macd_hist"]) else None,
            "macd_hist_rising": bool(latest["macd_hist"] > prev["macd_hist"])
            if pd.notna(latest["macd_hist"]) and pd.notna(prev["macd_hist"]) else None,
        },
        "volume": {
            "volume_ma5": round(float(latest["volume_ma5"]), 2) if pd.notna(latest["volume_ma5"]) else None,
            "volume_ma20": round(float(latest["volume_ma20"]), 2) if pd.notna(latest["volume_ma20"]) else None,
            "volume_ratio_5": round(float(latest["volume_ratio_5"]), 2) if pd.notna(latest["volume_ratio_5"]) else None,
            "volume_ratio_20": round(float(latest["volume_ratio_20"]), 2) if pd.notna(latest["volume_ratio_20"]) else None,
        },
        "vwap": {
            "vwap": round(float(latest["vwap"]), 2) if pd.notna(latest["vwap"]) else None,
            "price_above_vwap": bool(latest["close"] > latest["vwap"]) if pd.notna(latest["vwap"]) else None,
            "vwap_distance_pct": round(float(latest["vwap_distance_pct"]), 3)
            if pd.notna(latest["vwap_distance_pct"]) else None,
        },
        "trend": {
            "ma5_crossed_above_ma20": _crossed_above(indicator_df, "ma5", "ma20"),
            "ma5_crossed_below_ma20": _crossed_below(indicator_df, "ma5", "ma20"),
            "macd_crossed_above_signal": _crossed_above(indicator_df, "macd", "macd_signal"),
            "macd_crossed_below_signal": _crossed_below(indicator_df, "macd", "macd_signal"),
            "consecutive_up_bars": _count_consecutive_direction(indicator_df["close"], direction="up"),
            "consecutive_down_bars": _count_consecutive_direction(indicator_df["close"], direction="down"),
        },
        "volatility": {
            "atr14": round(float(latest["atr14"]), 3) if pd.notna(latest["atr14"]) else None,
            "atr14_pct": round(float(latest["atr14_pct"]), 3) if pd.notna(latest["atr14_pct"]) else None,
            "bb_mid": round(float(latest["bb_mid"]), 2) if pd.notna(latest["bb_mid"]) else None,
            "bb_upper": round(float(latest["bb_upper"]), 2) if pd.notna(latest["bb_upper"]) else None,
            "bb_lower": round(float(latest["bb_lower"]), 2) if pd.notna(latest["bb_lower"]) else None,
            "bb_width_pct": round(float(latest["bb_width_pct"]), 3) if pd.notna(latest["bb_width_pct"]) else None,
            "bb_position": round(float(latest["bb_position"]), 3) if pd.notna(latest["bb_position"]) else None,
            "price_above_bb_upper": bool(latest["close"] > latest["bb_upper"]) if pd.notna(latest["bb_upper"]) else None,
            "price_below_bb_lower": bool(latest["close"] < latest["bb_lower"]) if pd.notna(latest["bb_lower"]) else None,
        },
        "box_range": box,
        "recent_closes": [
            round(float(x), 2) for x in indicator_df["close"].tail(10).tolist()
        ],
        "recent_volumes": [
            round(float(x), 2) for x in indicator_df["volume"].tail(10).tolist()
        ],
    }

    return summary


def _crossed_above(df, left_col, right_col):
    """Return True only on the candle where left crosses above right."""
    if len(df) < 2:
        return False

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    if pd.isna(latest[left_col]) or pd.isna(latest[right_col]):
        return False
    if pd.isna(prev[left_col]) or pd.isna(prev[right_col]):
        return False

    return bool(prev[left_col] <= prev[right_col] and latest[left_col] > latest[right_col])


def _crossed_below(df, left_col, right_col):
    """Return True only on the candle where left crosses below right."""
    if len(df) < 2:
        return False

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    if pd.isna(latest[left_col]) or pd.isna(latest[right_col]):
        return False
    if pd.isna(prev[left_col]) or pd.isna(prev[right_col]):
        return False

    return bool(prev[left_col] >= prev[right_col] and latest[left_col] < latest[right_col])


def _count_consecutive_direction(series, direction):
    """Count consecutive rising or falling closes from the latest bar."""
    values = series.dropna().tail(10).tolist()

    if len(values) < 2:
        return 0

    count = 0
    for idx in range(len(values) - 1, 0, -1):
        if direction == "up" and values[idx] > values[idx - 1]:
            count += 1
        elif direction == "down" and values[idx] < values[idx - 1]:
            count += 1
        else:
            break

    return count


def make_market_snapshot(ticks):
    """Extract latest day-level tick fields supplied by Kiwoom."""
    df = ticks_to_dataframe(ticks)

    if df.empty:
        return {}

    latest = df.iloc[-1]

    return {
        "trade_time": latest.get("trade_time"),
        "current_price": _round_or_none(latest.get("price")),
        "change_rate": _round_or_none(latest.get("change_rate"), digits=3),
        "acc_volume": _round_or_none(latest.get("acc_volume"), digits=0),
        "day_open": _round_or_none(latest.get("open_price")),
        "day_high": _round_or_none(latest.get("high_price")),
        "day_low": _round_or_none(latest.get("low_price")),
        "strength": _round_or_none(latest.get("strength"), digits=3),
        "received_at": latest.get("received_at").strftime("%Y-%m-%d %H:%M:%S.%f")
        if pd.notna(latest.get("received_at")) else None,
    }


def _round_or_none(value, digits=2):
    """Safely round pandas/numpy values into JSON-friendly Python numbers."""
    try:
        if pd.isna(value):
            return None
        rounded = round(float(value), digits)
        if digits == 0:
            return int(rounded)
        return rounded
    except (TypeError, ValueError):
        return None


def summarize_multi_timeframes_for_gpt(code, name, ticks, drop_last=True):
    """Build synchronized 1m/3m/5m summaries from the same tick buffer."""
    timeframes = {
        "1m": "1min",
        "3m": "3min",
        "5m": "5min",
    }

    summary = {
        "code": code,
        "name": name,
        "market_snapshot": make_market_snapshot(ticks),
        "timeframes": {},
    }

    for label, interval in timeframes.items():
        ohlcv = make_ohlcv_from_ticks(
            ticks=ticks,
            interval=interval,
            drop_last=drop_last
        )
        indicator_df = add_indicators(ohlcv)

        timeframe_summary = summarize_for_gpt(
            code=code,
            name=name,
            indicator_df=indicator_df
        )

        if timeframe_summary:
            summary["timeframes"][label] = {
                "bar_count": len(indicator_df),
                "latest": timeframe_summary.get("latest"),
                "moving_average": timeframe_summary.get("moving_average"),
                "momentum": timeframe_summary.get("momentum"),
                "volume": timeframe_summary.get("volume"),
                "vwap": timeframe_summary.get("vwap"),
                "trend": timeframe_summary.get("trend"),
                "volatility": timeframe_summary.get("volatility"),
                "box_range": timeframe_summary.get("box_range"),
                "recent_closes": timeframe_summary.get("recent_closes"),
                "recent_volumes": timeframe_summary.get("recent_volumes"),
            }

    if not summary["timeframes"]:
        return None

    return summary
