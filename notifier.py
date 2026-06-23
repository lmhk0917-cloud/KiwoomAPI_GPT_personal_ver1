"""Event notification channels.

The project currently supports console alerts and optional Telegram alerts.
Notification results are returned to callers so they can be saved in SQLite.
"""

import json
import os
import urllib.parse
import urllib.request

from config import (
    ENABLE_NOTIFICATIONS,
    NOTIFICATION_CHANNELS,
    NOTIFICATION_MAX_EVENTS,
    TELEGRAM_COMPACT_EVENT_MESSAGE,
    TELEGRAM_MAX_MESSAGE_CHARS,
    TELEGRAM_TIMEOUT_SEC,
)
from env_loader import load_project_env


EVENT_LABELS = {
    "RSI_OVERSOLD": "RSI 과매도",
    "RSI_OVERBOUGHT": "RSI 과매수",
    "VOLUME_SPIKE": "거래량 급증",
    "NEAR_BOX_HIGH": "박스권 상단 근접",
    "NEAR_BOX_LOW": "박스권 하단 근접",
    "NEAR_VWAP_SUPPORT": "VWAP 지지 근접",
    "NEAR_VWAP_RESISTANCE": "VWAP 저항 근접",
    "MA5_MA20_GOLDEN_CROSS": "5일/20일 골든크로스",
    "MA5_MA20_DEAD_CROSS": "5일/20일 데드크로스",
    "CONSECUTIVE_UP_BARS": "연속 상승봉",
    "CONSECUTIVE_DOWN_BARS": "연속 하락봉",
    "ORDERBOOK_BID_IMBALANCE": "매수호가 우위",
    "ORDERBOOK_ASK_IMBALANCE": "매도호가 우위",
    "MARKET_SIDECAR_ACTIVE": "시장 사이드카 발동",
    "MARKET_CIRCUIT_BREAKER_ACTIVE": "시장 서킷브레이커 발동",
    "MARKET_CRASH_RISK": "시장 급락 위험",
    "MARKET_VI_ACTIVE": "시장 VI 발동",
    "MARKET_FOREIGN_SELL_PRESSURE": "시장 외국인 매도 압력",
}


SIGNAL_LABELS = {
    "OBSERVE_EVENT": "이벤트 관찰",
    "WATCH_REBOUND": "반등 관찰",
    "WATCH_PULLBACK": "눌림목 관찰",
    "WATCH_BREAKOUT": "돌파 관찰",
    "WATCH_SUPPORT": "지지 확인 관찰",
    "WATCH_RESISTANCE": "저항 확인 필요",
    "WATCH_MOMENTUM": "모멘텀 관찰",
    "AVOID_CHASE": "추격매수 주의",
    "AVOID_SUPPLY": "매도물량 주의",
    "AVOID_DOWNTREND": "하락추세 회피",
    "AVOID_MARKET_RISK": "시장 리스크 회피",
}


RISK_LABELS = {
    "low": "낮음",
    "medium": "중간",
    "high": "높음",
}


STATUS_LABELS = {
    "active": "발동",
    "triggered": "발동",
    "inactive": "없음",
    "regular": "정규",
    "unknown": "알 수 없음",
    None: "없음",
}


class Notifier:
    """Send event messages to configured channels."""

    def __init__(self, settings=None):
        load_project_env()
        self.enabled = ENABLE_NOTIFICATIONS
        self.channels = list(NOTIFICATION_CHANNELS)
        self.notification_max_events = NOTIFICATION_MAX_EVENTS
        self.telegram_timeout_sec = TELEGRAM_TIMEOUT_SEC
        self.telegram_max_message_chars = TELEGRAM_MAX_MESSAGE_CHARS
        self.telegram_compact_event_message = TELEGRAM_COMPACT_EVENT_MESSAGE
        self.telegram_bot_token = None
        self.telegram_chat_id = None
        self._reload_telegram_credentials()

        if settings:
            self.configure(settings)

    def configure(self, settings):
        """Apply runtime settings loaded from SQLite."""
        self.enabled = bool(settings.get("ENABLE_NOTIFICATIONS", self.enabled))
        self.channels = list(settings.get("NOTIFICATION_CHANNELS", self.channels))
        self.notification_max_events = int(settings.get(
            "NOTIFICATION_MAX_EVENTS",
            self.notification_max_events,
        ))
        self.telegram_timeout_sec = int(settings.get(
            "TELEGRAM_TIMEOUT_SEC",
            self.telegram_timeout_sec,
        ))
        self.telegram_max_message_chars = int(settings.get(
            "TELEGRAM_MAX_MESSAGE_CHARS",
            self.telegram_max_message_chars,
        ))
        self.telegram_compact_event_message = bool(settings.get(
            "TELEGRAM_COMPACT_EVENT_MESSAGE",
            self.telegram_compact_event_message,
        ))
        self._reload_telegram_credentials()

    def notify_event(self, summary, events, signal=None, skip_reason=None, channels=None):
        """Build one event message and deliver it to every configured channel."""
        if not self.enabled or not events:
            return []

        message = self._build_event_message(summary, events, signal, skip_reason)
        return self.notify_text(message, channels=channels)

    def notify_text(self, message, channels=None):
        """Deliver an already-built message to selected notification channels."""
        if not self.enabled:
            return []

        results = []
        active_channels = list(channels or self.channels)

        for channel in active_channels:
            if channel == "console":
                results.append(self._send_console(message))
            elif channel == "telegram":
                results.append(self._send_telegram(message))
            else:
                results.append({
                    "channel": channel,
                    "status": "skipped",
                    "error_message": "unknown channel",
                })

        for result in results:
            result["message"] = message

        return results

    def _build_event_message(self, summary, events, signal=None, skip_reason=None):
        """Build a compact plain-text message suitable for console/Telegram."""
        code = summary.get("code", "")
        name = summary.get("name", "")
        primary = self._get_primary_timeframe(summary)
        latest = primary.get("latest", {})
        momentum = primary.get("momentum", {})
        volume = primary.get("volume", {})
        box_range = primary.get("box_range") or {}
        vwap = primary.get("vwap", {})
        market_context = summary.get("market_context") or {}
        market_status = market_context.get("market_status") or {}

        event_texts = []
        for event in events[:self.notification_max_events]:
            value = event.get("value")
            event_label = self._event_label(event.get("type", "UNKNOWN"))
            if value is None:
                event_texts.append(event_label)
            else:
                event_texts.append("{}({})".format(event_label, self._format_value(value)))

        lines = [
            "[실시간 이벤트 알림]",
            "종목: {} ({})".format(name, code),
            "감지 이벤트: {}".format(", ".join(event_texts)),
            "현재가: {}".format(self._format_value(latest.get("close"))),
            "RSI14: {}".format(self._format_value(momentum.get("rsi14"))),
            "거래량 배율(20봉): {}".format(self._format_value(volume.get("volume_ratio_20"))),
            "박스권 위치: {}".format(self._format_value(box_range.get("current_position_in_box"))),
            "VWAP 거리(%): {}".format(self._format_value(vwap.get("vwap_distance_pct"))),
        ]

        if self._has_market_status(market_status):
            lines.append(
                "시장상태: 사이드카={} {} / 서킷브레이커={} / VI={}".format(
                    self._status_label(market_status.get("sidecar_status")),
                    self._direction_label(market_status.get("sidecar_direction")),
                    self._status_label(market_status.get("circuit_breaker_status")),
                    self._status_label(market_status.get("vi_status")),
                )
            )
            if market_status.get("summary"):
                lines.append("시장 메모: {}".format(market_status.get("summary")))

        if self.telegram_compact_event_message:
            lines = [
                "[이벤트] {}({})".format(name, code),
                "이벤트: {}".format(", ".join(event_texts)),
                "가격: {} / RSI: {} / VWAP%: {}".format(
                    self._format_value(latest.get("close")),
                    self._format_value(momentum.get("rsi14")),
                    self._format_value(vwap.get("vwap_distance_pct")),
                ),
            ]

        if signal:
            lines.extend([
                "신호: {} / 점수={} / 위험도={}".format(
                    self._signal_label(signal.get("action_hint")),
                    signal.get("confidence_score"),
                    self._risk_label(signal.get("risk_level")),
                ),
                "관찰 기준선: 하단={} / 1차상단={} / 2차상단={}".format(
                    self._format_value(signal.get("stop_loss")),
                    self._format_value(signal.get("target_1")),
                    self._format_value(signal.get("target_2")),
                ),
            ])

        if skip_reason:
            lines.append("생략 사유: {}".format(self._skip_reason_label(skip_reason)))

        return "\n".join(lines)

    def _event_label(self, event_type):
        return EVENT_LABELS.get(event_type, event_type or "알 수 없음")

    def _signal_label(self, action_hint):
        return SIGNAL_LABELS.get(action_hint, action_hint or "알 수 없음")

    def _risk_label(self, risk_level):
        return RISK_LABELS.get(risk_level, risk_level or "알 수 없음")

    def _status_label(self, status):
        return STATUS_LABELS.get(status, status or "알 수 없음")

    def _direction_label(self, direction):
        labels = {
            "buy": "매수",
            "sell": "매도",
            "up": "상승",
            "down": "하락",
            "unknown": "방향 미확인",
            None: "",
        }
        return labels.get(direction, direction or "")

    def _skip_reason_label(self, skip_reason):
        labels = {
            "cooldown": "쿨다운 적용 중",
            "no_event": "감지 이벤트 없음",
        }
        return labels.get(skip_reason, skip_reason or "알 수 없음")

    def _format_value(self, value):
        if value is None:
            return "없음"
        return value

    def _has_market_status(self, market_status):
        if not market_status:
            return False

        active_values = ("active", "triggered")
        statuses = (
            market_status.get("sidecar_status"),
            market_status.get("circuit_breaker_status"),
            market_status.get("vi_status"),
        )
        return any(str(status).strip().lower() in active_values for status in statuses)

    def _send_console(self, message):
        """Print notification to stdout for local debugging."""
        print("\n========== Notification ==========")
        print(message)
        print("==================================\n")
        return {
            "channel": "console",
            "status": "success",
            "error_message": None,
        }

    def _send_telegram(self, message):
        """Send Telegram message when TELEGRAM_BOT_TOKEN/CHAT_ID are configured."""
        message = self._trim_telegram_message(message)

        if not self.telegram_bot_token or not self.telegram_chat_id:
            return {
                "channel": "telegram",
                "status": "skipped",
                "error_message": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing",
            }

        url = "https://api.telegram.org/bot{}/sendMessage".format(self.telegram_bot_token)
        payload = urllib.parse.urlencode({
            "chat_id": self.telegram_chat_id,
            "text": message,
        }).encode("utf-8")

        try:
            request = urllib.request.Request(url, data=payload, method="POST")
            with urllib.request.urlopen(request, timeout=self.telegram_timeout_sec) as response:
                response_body = response.read().decode("utf-8")
                parsed = json.loads(response_body)

            if parsed.get("ok"):
                return {
                    "channel": "telegram",
                    "status": "success",
                    "error_message": None,
                }

            return {
                "channel": "telegram",
                "status": "failed",
                "error_message": response_body,
            }
        except Exception as exc:
            return {
                "channel": "telegram",
                "status": "failed",
                "error_message": str(exc),
            }

    def _reload_telegram_credentials(self):
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def _trim_telegram_message(self, message):
        max_chars = min(max(self.telegram_max_message_chars, 500), 4096)

        if len(message) <= max_chars:
            return message

        suffix = "\n\n[길이 제한으로 일부 생략]"
        return message[:max_chars - len(suffix)] + suffix

    def _get_primary_timeframe(self, summary):
        """Use 1m as notification source when available."""
        timeframes = summary.get("timeframes") or {}

        if timeframes.get("1m"):
            return timeframes["1m"]

        for timeframe_summary in timeframes.values():
            return timeframe_summary

        return summary
