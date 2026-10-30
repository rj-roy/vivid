"""Clickable display card used in the main window."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStyle, QVBoxLayout, QWidget

from ..models import DisplayStatus, DisplayView, format_percent

STATUS_LABELS = {
    DisplayStatus.ACTIVE: "Active",
    DisplayStatus.APPLYING: "Applying",
    DisplayStatus.APPLIED: "Applied",
    DisplayStatus.UNSUPPORTED: "Unsupported",
    DisplayStatus.FAILED: "Failed",
    DisplayStatus.DISCONNECTED: "Disconnected",
    DisplayStatus.CONFLICT: "Conflict",
    DisplayStatus.NEEDS_CONFIRMATION: "Needs confirmation",
}


class DisplayCard(QFrame):
    selected = Signal(object)

    def __init__(self, view: DisplayView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view = view
        self.setObjectName("displayCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{view.display.friendly_name}, {view.display.output_name}")
        self.setAccessibleDescription(
            f"Saturation saved at {view.preferred_saturation} percent. "
            f"Status {STATUS_LABELS.get(view.status, view.status.value)}."
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        self.icon_label = QLabel()
        icon = QIcon.fromTheme(
            "video-display",
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon),
        )
        self.icon_label.setPixmap(icon.pixmap(34, 34))
        self.icon_label.setFixedSize(38, 38)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = QLabel()
        self.title.setObjectName("displayTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("displaySubtitle")
        self.subtitle.setWordWrap(False)
        texts.addWidget(self.title)
        texts.addWidget(self.subtitle)
        layout.addLayout(texts, 1)
        right = QVBoxLayout()
        right.setSpacing(2)
        self.value = QLabel()
        self.value.setObjectName("displayValue")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status = QLabel()
        self.status.setObjectName("displayStatus")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self.value)
        right.addWidget(self.status)
        layout.addLayout(right)
        self.apply_view(view)

    def apply_view(self, view: DisplayView) -> None:
        self.view = view
        display = view.display
        self.title.setText(display.friendly_name)
        kind = "Internal" if display.internal else "External"
        self.subtitle.setText(f"{display.output_name}  ·  {kind}  ·  {display.mode_label}")
        self.value.setText(format_percent(view.preferred_saturation))
        self.status.setToolTip(
            f"{STATUS_LABELS.get(view.status, view.status.value)}: {view.message}"
        )
        self.status.setText(STATUS_LABELS.get(view.status, view.status.value))
        self.status.setAccessibleName(
            f"Status: {STATUS_LABELS.get(view.status, view.status.value)}"
        )
        self.setAccessibleDescription(
            f"Saturation saved at {view.preferred_saturation} percent. "
            f"Status {STATUS_LABELS.get(view.status, view.status.value)}. {view.message}"
        )
        self.setToolTip(view.message)
        self.setProperty("conflict", view.status in (DisplayStatus.CONFLICT, DisplayStatus.FAILED))
        self.style().unpolish(self)
        self.style().polish(self)

    def set_selected(self, is_selected: bool) -> None:
        self.setProperty("selected", is_selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.view.display)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit(self.view.display)
            event.accept()
            return
        super().keyPressEvent(event)
