"""Full-screen identification overlay for a physical display."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from ..models import DisplayInfo

_OPEN_OVERLAYS: list[QWidget] = []


def _screen_for(display: DisplayInfo):
    screens = QGuiApplication.screens()
    for screen in screens:
        if screen.name() == display.output_name:
            return screen
    point = (display.x, display.y)
    for screen in screens:
        if screen.geometry().contains(*point):
            return screen
    return None


class IdentifyOverlay(QWidget):
    def __init__(self, display: DisplayInfo) -> None:
        super().__init__(None)
        self.display = display
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAccessibleName(f"Identifying {display.friendly_name}")
        screen = _screen_for(display)
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))
        painter.setPen(QPen(QColor(61, 174, 233), 10))
        margin = 12
        painter.drawRect(self.rect().adjusted(margin, margin, -margin, -margin))
        font = QFont()
        font.setPointSize(max(22, min(54, self.width() // 28)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        title = self.display.friendly_name
        subtitle = f"{self.display.output_name}  ·  {self.display.mode_label}"
        hint = "This is the display Vivid will adjust"
        metrics = painter.fontMetrics()
        total_height = metrics.height() * 3 + 48
        top = (self.height() - total_height) // 2
        for index, text in enumerate((title, subtitle, hint)):
            if index == 2:
                font.setBold(False)
                font.setPointSize(max(12, font.pointSize() // 2))
                painter.setFont(font)
                metrics = painter.fontMetrics()
            rect = QRect(24, top, self.width() - 48, metrics.height() + 12)
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text
            )
            top += metrics.height() + (24 if index == 0 else 12)
        painter.end()


def show_identify(
    displays: Iterable[DisplayInfo],
    duration_ms: int = 2200,
    application: QApplication | None = None,
) -> list[QWidget]:
    created_app = False
    app = application or QApplication.instance()
    if app is None:
        app = QApplication([])
        created_app = True
    overlays: list[QWidget] = []
    for display in displays:
        overlay = IdentifyOverlay(display)
        overlay.showFullScreen()
        overlays.append(overlay)
        _OPEN_OVERLAYS.append(overlay)
    QTimer.singleShot(duration_ms, lambda: _close_overlays(overlays))
    if created_app:
        QTimer.singleShot(duration_ms + 100, app.quit)
        app.exec()
    return overlays


def _close_overlays(overlays: list[QWidget]) -> None:
    for overlay in overlays:
        overlay.close()
        overlay.deleteLater()
        if overlay in _OPEN_OVERLAYS:
            _OPEN_OVERLAYS.remove(overlay)
