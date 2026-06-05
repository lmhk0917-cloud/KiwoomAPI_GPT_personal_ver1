"""Reusable custom widgets for the PyQt dashboard."""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QWidget

class PriceVolumeChart(QWidget):
    """Small dependency-free price/volume chart for recent DB ticks."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.code = ""
        self.name = ""
        self.setMinimumHeight(330)

    def set_data(self, rows, code="", name=""):
        self.rows = []
        self.code = code or ""
        self.name = name or ""

        for row in rows or []:
            price = self._to_float(row["price"])
            volume = self._to_float(row["tick_volume"])
            if price is None:
                continue
            self.rows.append({
                "time": row["received_at"],
                "price": price,
                "volume": volume or 0.0,
            })

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(255, 255, 255))

        width = self.width()
        height = self.height()
        left = 64
        right = 24
        top = 34
        bottom = 30
        gap = 18
        price_bottom = int(height * 0.68)
        volume_top = price_bottom + gap
        chart_width = max(1, width - left - right)

        title = "가격/거래량 차트"
        if self.code:
            title = "{}  {} {}".format(title, self.code, self.name)
        painter.setPen(QColor(20, 24, 31))
        painter.drawText(left, 22, title)

        if len(self.rows) < 2:
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(left, int(height / 2), "차트 데이터가 부족합니다.")
            return

        prices = [row["price"] for row in self.rows]
        volumes = [row["volume"] for row in self.rows]
        min_price = min(prices)
        max_price = max(prices)
        if min_price == max_price:
            min_price -= 1
            max_price += 1
        max_volume = max(volumes) if volumes else 0
        max_volume = max(max_volume, 1)

        self._draw_grid(painter, left, top, chart_width, price_bottom - top, min_price, max_price)
        self._draw_volume_bars(painter, left, volume_top, chart_width, height - volume_top - bottom, max_volume)
        self._draw_line(painter, prices, left, top, chart_width, price_bottom - top, min_price, max_price, QColor(35, 102, 210), 2)

        ma5 = self._moving_average(prices, 5)
        ma20 = self._moving_average(prices, 20)
        self._draw_line(painter, ma5, left, top, chart_width, price_bottom - top, min_price, max_price, QColor(235, 126, 44), 1)
        self._draw_line(painter, ma20, left, top, chart_width, price_bottom - top, min_price, max_price, QColor(34, 150, 95), 1)

        painter.setPen(QColor(80, 80, 80))
        painter.drawText(left, height - 8, str(self.rows[0]["time"]))
        painter.drawText(max(left, width - 220), height - 8, str(self.rows[-1]["time"]))
        painter.drawText(width - 170, 22, "현재가: {:,.0f}".format(prices[-1]))

        legend_left = max(left + 260, width - 360)
        painter.setPen(QColor(35, 102, 210))
        painter.drawText(legend_left, 22, "가격")
        painter.setPen(QColor(235, 126, 44))
        painter.drawText(legend_left + 42, 22, "MA5")
        painter.setPen(QColor(34, 150, 95))
        painter.drawText(legend_left + 82, 22, "MA20")

    def _draw_grid(self, painter, left, top, width, height, min_price, max_price):
        painter.setPen(QPen(QColor(224, 228, 235), 1))
        for idx in range(5):
            y = top + int(height * idx / 4)
            painter.drawLine(left, y, left + width, y)
            value = max_price - ((max_price - min_price) * idx / 4)
            painter.setPen(QColor(95, 95, 95))
            painter.drawText(6, y + 4, "{:,.0f}".format(value))
            painter.setPen(QPen(QColor(224, 228, 235), 1))
        painter.drawRect(left, top, width, height)

    def _draw_volume_bars(self, painter, left, top, width, height, max_volume):
        if not self.rows:
            return
        bar_width = max(1, int(width / len(self.rows)))
        previous_price = self.rows[0]["price"]
        for idx, row in enumerate(self.rows):
            x = left + int(width * idx / max(1, len(self.rows) - 1))
            bar_height = int(height * row["volume"] / max_volume)
            color = QColor(210, 70, 70) if row["price"] >= previous_price else QColor(55, 120, 210)
            painter.fillRect(x, top + height - bar_height, max(1, bar_width - 1), bar_height, color)
            previous_price = row["price"]
        painter.setPen(QPen(QColor(224, 228, 235), 1))
        painter.drawRect(left, top, width, height)
        painter.setPen(QColor(95, 95, 95))
        painter.drawText(6, top + 14, "거래량")

    def _draw_line(self, painter, values, left, top, width, height, min_price, max_price, color, pen_width):
        points = []
        for idx, value in enumerate(values):
            if value is None:
                points = []
                continue
            x = left + int(width * idx / max(1, len(values) - 1))
            y = top + int((max_price - value) / (max_price - min_price) * height)
            points.append((x, y))

            if len(points) >= 2:
                painter.setPen(QPen(color, pen_width))
                painter.drawLine(points[-2][0], points[-2][1], points[-1][0], points[-1][1])

    def _moving_average(self, values, period):
        averaged = []
        for idx in range(len(values)):
            if idx + 1 < period:
                averaged.append(None)
                continue
            window = values[idx + 1 - period:idx + 1]
            averaged.append(sum(window) / len(window))
        return averaged

    def _to_float(self, value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None


class IndicatorGaugeWidget(QWidget):
    """Visualize the latest technical indicators as compact gauges."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.indicators = {}
        self.setMinimumHeight(220)

    def set_indicators(self, indicators):
        self.indicators = indicators or {}
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(255, 255, 255))

        rows = self._indicator_rows()
        if not rows:
            painter.setPen(QColor(120, 120, 120))
            painter.drawText(18, 34, "표시할 최신 지표가 없습니다.")
            return

        painter.setPen(QColor(20, 24, 31))
        painter.drawText(18, 22, "핵심 지표")

        top = 44
        row_height = 31
        label_width = 120
        bar_left = 150
        bar_width = max(160, self.width() - bar_left - 130)

        for idx, item in enumerate(rows):
            label, value, min_value, max_value, color, centered = item
            y = top + idx * row_height
            painter.setPen(QColor(70, 70, 70))
            painter.drawText(18, y + 18, label)
            painter.drawText(bar_left + bar_width + 12, y + 18, self._format_value(value))
            painter.setPen(QPen(QColor(220, 224, 230), 1))
            painter.drawRect(bar_left, y + 6, bar_width, 12)

            if value is None:
                continue

            if centered:
                zero_x = bar_left + int((0 - min_value) / (max_value - min_value) * bar_width)
                value_x = bar_left + int((value - min_value) / (max_value - min_value) * bar_width)
                painter.setPen(QPen(QColor(120, 120, 120), 1))
                painter.drawLine(zero_x, y + 3, zero_x, y + 21)
                left = min(zero_x, value_x)
                width = max(1, abs(value_x - zero_x))
                painter.fillRect(left, y + 7, width, 11, color)
            else:
                ratio = (value - min_value) / (max_value - min_value)
                ratio = max(0.0, min(1.0, ratio))
                painter.fillRect(bar_left, y + 7, int(bar_width * ratio), 11, color)

    def _indicator_rows(self):
        row = self.indicators
        if not row:
            return []

        rsi = self._to_float(row.get("rsi14"))
        volume = self._to_float(row.get("volume_ratio_20"))
        vwap_distance = self._to_float(row.get("vwap_distance_pct"))
        box_position = self._to_float(row.get("box_position"))
        strength = self._to_float(row.get("strength"))

        return [
            ("RSI14", rsi, 0.0, 100.0, self._rsi_color(rsi), False),
            ("거래량 배율", volume, 0.0, 5.0, QColor(94, 135, 220), False),
            ("VWAP 이격률", vwap_distance, -3.0, 3.0, self._signed_color(vwap_distance), True),
            ("박스 위치", box_position, 0.0, 1.0, QColor(130, 95, 190), False),
            ("체결강도", strength, 0.0, 200.0, QColor(45, 160, 110), False),
        ]

    def _format_value(self, value):
        if value is None:
            return "-"
        return "{:.2f}".format(float(value))

    def _rsi_color(self, value):
        if value is None:
            return QColor(150, 150, 150)
        if value >= 70:
            return QColor(205, 85, 65)
        if value <= 30:
            return QColor(65, 110, 205)
        return QColor(45, 155, 105)

    def _signed_color(self, value):
        if value is None:
            return QColor(150, 150, 150)
        if value >= 0:
            return QColor(205, 85, 65)
        return QColor(65, 110, 205)

    def _to_float(self, value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None


