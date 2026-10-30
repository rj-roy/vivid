"""System tray integration with direct per-display saturation controls."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from ..models import DisplayView, format_percent


class VividTray(QSystemTrayIcon):
    def __init__(self, window) -> None:
        icon = window.windowIcon()
        if icon.isNull():
            icon = QIcon.fromTheme("preferences-desktop-display")
        super().__init__(icon, window)
        self.window = window
        self.setToolTip("Vivid — independent display saturation")
        self.menu = QMenu()
        self.open_action = QAction("Open Vivid", self.menu)
        self.open_action.triggered.connect(self.window.show_from_tray)
        self.menu.addAction(self.open_action)
        self.menu.addSeparator()
        self.display_menu = self.menu.addMenu("Adjust displays")
        self._display_controls: dict[str, tuple[QMenu, QLabel, QSlider, QLabel, QAction]] = {}
        self.menu.addSeparator()
        self.reset_all_action = QAction("Reset all displays…", self.menu)
        self.reset_all_action.triggered.connect(self.window.reset_all_with_confirmation)
        self.menu.addAction(self.reset_all_action)
        self.menu.addSeparator()
        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(QApplication.quit)
        self.menu.addAction(quit_action)
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)

    def update_displays(self, views: list[DisplayView], selected_id: str | None) -> None:
        connected = [view for view in views if view.display.connected]
        backend_supported = self.window.service.capabilities.supported
        identities = [
            view.display.identity.stable_id if view.display.identity else ""
            for view in connected
        ]
        if identities != list(self._display_controls):
            self.display_menu.clear()
            self._display_controls.clear()
            for view in connected:
                self._add_display_control(view)

        for view in connected:
            stable_id = view.display.identity.stable_id if view.display.identity else ""
            submenu, heading, slider, value_label, reset_action = self._display_controls[
                stable_id
            ]
            selection = " · Selected" if stable_id == selected_id else ""
            heading.setText(
                f"{view.display.output_name} · "
                f"{'Internal' if view.display.internal else 'External'}{selection}"
            )
            slider.setAccessibleName(f"Saturation adjustment for {view.display.friendly_name}")
            slider.setEnabled(view.display.enabled and backend_supported)
            signals_blocked = slider.blockSignals(True)
            slider.setValue(view.preferred_saturation)
            slider.blockSignals(signals_blocked)
            value_label.setText(format_percent(view.preferred_saturation))
            reset_action.setEnabled(
                view.preferred_saturation != 0 or view.display.profile_owned_by_vivid
            )
            submenu.setEnabled(view.display.enabled and backend_supported)

        self.display_menu.setEnabled(bool(connected))
        self.reset_all_action.setEnabled(
            any(
                view.preferred_saturation != 0 or view.display.profile_owned_by_vivid
                for view in connected
            )
        )

    def _add_display_control(self, view: DisplayView) -> None:
        stable_id = view.display.identity.stable_id if view.display.identity else ""
        submenu = self.display_menu.addMenu(view.display.friendly_name)
        submenu.setToolTipsVisible(True)
        submenu.setToolTip(
            f"{view.display.output_name} · {format_percent(view.preferred_saturation)}"
        )

        control = QWidget(submenu)
        layout = QVBoxLayout(control)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        heading = QLabel()
        layout.addWidget(heading)

        value_row = QHBoxLayout()
        value_row.addWidget(QLabel("-100%"))
        slider = QSlider(control)
        slider.setOrientation(Qt.Orientation.Horizontal)
        slider.setRange(-100, 100)
        slider.setSingleStep(1)
        slider.setPageStep(10)
        slider.setAccessibleDescription(
            "Minus 100 percent is grayscale; zero is the normal baseline; "
            "plus 100 percent doubles saturation."
        )
        slider.setToolTip("−100% grayscale · 0% baseline · +100% maximum")
        value_label = QLabel()
        value_label.setMinimumWidth(44)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        value_row.addWidget(slider, 1)
        value_row.addWidget(value_label)
        layout.addLayout(value_row)

        slider.valueChanged.connect(
            lambda value, label=value_label, stable_id=stable_id: (
                label.setText(format_percent(value)),
                self.window.queue_quick_saturation(stable_id, value),
            )
        )

        widget_action = QWidgetAction(submenu)
        widget_action.setDefaultWidget(control)
        submenu.addAction(widget_action)
        submenu.addSeparator()
        reset_action = QAction("Reset to baseline", submenu)
        reset_action.triggered.connect(
            lambda checked=False, stable_id=stable_id: self.window.queue_quick_saturation(
                stable_id, 0
            )
        )
        submenu.addAction(reset_action)
        open_display = QAction("Open in Vivid", submenu)
        open_display.triggered.connect(
            lambda checked=False, stable_id=stable_id: self.window.show_and_select(stable_id)
        )
        submenu.addAction(open_display)
        self._display_controls[stable_id] = (
            submenu,
            heading,
            slider,
            value_label,
            reset_action,
        )

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.window.show_from_tray()
