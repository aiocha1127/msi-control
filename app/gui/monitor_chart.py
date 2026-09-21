"""
Wykres monitoringu czasu rzeczywistego (czysty QPainter, zero zależności).

Rysuje ostatnie N próbek temperatury CPU/GPU oraz obrotów wentylatorów.
Dwie skale pionowe:
  - lewa  : temperatura (°C)   - prawa: obroty (RPM).

Użycie w GUI:
    chart = MonitorChart()
    chart.init_series([("cpu_temp","CPU temp","#4fc3f7","temp"),
                       ("cpu_fan","CPU fan","#81c784","rpm")])
    chart.push({"cpu_temp": 52.3, "cpu_fan": 2100})

Próbka z pominięciem klucza nie przesuwa serii (punkt krokowy).
"""

from collections import deque

from PySide6.QtCore import Qt, QRectF, QPointF, QRect
from PySide6.QtGui import (
    QPainter,
    QPainterPath,
    QColor,
    QPen,
    QFont,
)
from PySide6.QtWidgets import QWidget, QSizePolicy

WINDOW = 240  # liczba próbek trzymanych na wykresie (ok. 4 min przy 1 s)


class MonitorChart(QWidget):
    """Rysuje linie trendów temperatur i obrotów w oknie przesuwnym."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series: list[tuple] = []
        self._buffers: dict[str, deque] = {}
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    # ------------- API -------------

    def init_series(
        self,
        series: list[tuple[str, str, str, str]],
    ) -> None:
        """
        series: lista (klucz, etykieta, kolor_hex, typ) gdzie typ to
                'temp' lub 'rpm'. Wywołaj przed pierwszym push().
        """
        self._series = list(series)
        self._buffers = {
            key: deque(maxlen=WINDOW)
            for key, _name, _color, _typ in self._series
        }
        self.update()

    def push(self, sample: dict) -> None:
        """Dopnij nową próbkę. Puste wartości nie przesuwają serii."""
        for key in self._buffers:
            value = sample.get(key)
            if value is None:
                continue
            self._buffers[key].append(float(value))
        self.update()

    def clear(self) -> None:
        for buf in self._buffers.values():
            buf.clear()
        self.update()

    # ------------- rysowanie -------------

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # marginesy: etykiety osi + legenda
        left = 34
        right = 44
        top = 20
        bottom = 12
        plot_w = max(10, w - left - right)
        plot_h = max(10, h - top - bottom)

        font = QFont(p.font())
        font.setPointSize(8)
        p.setFont(font)
        fh = p.fontMetrics().height()

        # ------ zakresy ------
        t_lo, t_hi = 30.0, 105.0
        f_lo, f_hi = 0.0, 2000.0

        tbuf = self._buffers.get("cpu_temp") or self._buffers.get("gpu_temp")
        if any(self._buffers.get(k) for k in ("cpu_temp", "gpu_temp")):
            all_t = list(self._buffers.get("cpu_temp") or []) + \
                    list(self._buffers.get("gpu_temp") or [])
            if all_t:
                t_lo = max(30.0, min(all_t) - 5.0)
                t_hi = min(110.0, max(all_t) + 5.0)
                if t_hi - t_lo < 15:
                    t_hi = t_lo + 15

        all_f = list(self._buffers.get("cpu_fan") or []) + \
                list(self._buffers.get("gpu_fan") or [])
        if all_f:
            f_hi = max(1000.0, max(all_f) * 1.15)

        def plot_x(i: int, n: int) -> float:
            if n <= 1:
                return float(left)
            return left + (i / (n - 1)) * plot_w

        def value_y(v: float, lo: float, hi: float) -> float:
            ratio = (v - lo) / (hi - lo) if hi > lo else 0.0
            return top + (1.0 - ratio) * plot_h

        # ------ tło i siatka ------
        p.fillRect(QRect(left, top, int(plot_w), int(plot_h)), QColor("#1b1b1b"))
        p.setPen(QPen(QColor("#2f2f2f"), 1))
        steps = 5
        for i in range(steps + 1):
            y = top + (i / steps) * plot_h
            p.drawLine(int(left), int(y), int(left + plot_w), int(y))
            if i < steps:
                t_label = t_hi - (i / steps) * (t_hi - t_lo)
                p.setPen(QPen(QColor("#9e9e9e"), 1))
                p.drawText(QRect(0, int(y - fh / 2), int(left - 6), int(fh)),
                           Qt.AlignRight | Qt.AlignVCenter, f"{t_label:.0f}")
                r_label = f_hi - (i / steps) * (f_hi - f_lo)
                p.drawText(
                    QRect(int(left + plot_w + 4), int(y - fh / 2),
                          int(right - 4), int(fh)),
                    Qt.AlignLeft | Qt.AlignVCenter, f"{r_label:.0f}")

        # ------ ościeżnice osi ------
        p.drawLine(int(left), int(top + plot_h), int(left + plot_w), int(top + plot_h))
        p.drawLine(int(left), int(top), int(left), int(top + plot_h))

        # ------ serie ------
        for key, name, color, typ in self._series:
            buf = self._buffers.get(key)
            if not buf:
                continue
            lines_colors = QColor(color)
            p.setPen(QPen(lines_colors, 2))
            pts: list[QPointF] = []
            n = len(buf)
            for i, v in enumerate(buf):
                if typ == "temp":
                    y = value_y(v, t_lo, t_hi)
                else:
                    y = value_y(v, f_lo, f_hi)
                pts.append(QPointF(plot_x(i, n), y))

            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            p.drawPath(path)

        # ------ legenda ------
        p.setPen(QColor("#e0e0e0"))
        x = left
        for key, name, color, _typ in self._series:
            buf = self._buffers.get(key)
            last = buf[-1] if buf else None
            swatch = QColor(color)
            p.setPen(QPen(swatch, 7))
            p.drawLine(int(x), int(6), int(x + 12), int(6))
            text = name if last is None else f"{name} {last:.0f}"
            p.setPen(QColor("#e0e0e0"))
            p.drawText(QRect(int(x + 16), 0, 200, fh + 160 and 14),
                       Qt.AlignLeft, text)
            x += 30 + p.fontMetrics().horizontalAdvance(text)

        p.end()
