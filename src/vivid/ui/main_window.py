"""Vivid main window."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .. import APP_ID, APP_VERSION
from ..application import VividService
from ..logging_utils import get_logger, setup_logging
from ..models import ApplyResult, DisplayInfo, DisplayStatus, DisplayView, format_percent
from .diagnostics_dialog import DiagnosticsDialog
from .display_card import DisplayCard
from .identify import show_identify
from .settings_dialog import SettingsDialog
from .tray import VividTray

PRESETS = (
    ("Grayscale", -100),
    ("Muted", -50),
    ("Natural", 0),
    ("Mild", 15),
    ("Vivid", 30),
    ("Strong", 45),
)


def _view_stable_id(view: DisplayView) -> str:
    return view.display.identity.stable_id if view.display.identity else ""


class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(str)


class Task(QRunnable):
    def __init__(self, function: Callable[[], Any]) -> None:
        super().__init__()
        self.function = function
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # report to the UI thread
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.result.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, service: VividService | None = None) -> None:
        super().__init__()
        self.log = get_logger("ui")
        self.service = service or VividService()
        self.views: list[DisplayView] = []
        self.inactive_views: list[DisplayView] = []
        self.selected_id: str | None = None
        self.cards: dict[str, DisplayCard] = {}
        self._updating_slider = False
        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.setInterval(180)
        self._apply_timer.timeout.connect(self._flush_apply)
        self._pending_percent: int | None = None
        self._apply_token = 0
        self._apply_in_flight = False
        self._quick_pending: dict[str, int] = {}
        self._quick_apply_timer = QTimer(self)
        self._quick_apply_timer.setSingleShot(True)
        self._quick_apply_timer.setInterval(180)
        self._quick_apply_timer.timeout.connect(self._flush_quick_apply)
        self._refresh_in_flight = False
        self._refresh_again = False
        self._confirmed_ambiguous: set[str] = set()
        self._tasks: set[Task] = set()
        self._tray: VividTray | None = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("Vivid — Display Saturation")
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop-display"))
        self.setMinimumSize(680, 640)
        self.resize(820, 720)
        self._build_ui()
        self._build_menus()
        self._connect_hotplug()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(30000)
        self._poll_timer.timeout.connect(lambda: self.refresh_displays(quiet=True))
        self._poll_timer.start()
        QTimer.singleShot(0, self.refresh_displays)
        QTimer.singleShot(350, self._setup_tray)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(1)
        title = QLabel("Vivid")
        title.setObjectName("appTitle")
        subtitle = QLabel("Independent display saturation")
        subtitle.setObjectName("appSubtitle")
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header.addLayout(header_text, 1)
        self.backend_badge = QLabel()
        self.backend_badge.setObjectName("backendBadge")
        self.backend_badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.backend_badge)
        layout.addLayout(header)
        self.error_banner = QLabel()
        self.error_banner.setObjectName("errorBanner")
        self.error_banner.setWordWrap(True)
        self.error_banner.setVisible(False)
        layout.addWidget(self.error_banner)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(150)
        self.scroll.setMaximumHeight(240)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 4, 0)
        self.cards_layout.setSpacing(8)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_container)
        layout.addWidget(self.scroll)
        self.empty_label = QLabel(
            "No displays were discovered. Check the KScreen configuration and refresh."
        )
        self.empty_label.setWordWrap(True)
        self.empty_label.setObjectName("hintLabel")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)
        self.detail = QFrame()
        self.detail.setObjectName("detailPanel")
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(18, 16, 18, 16)
        detail_layout.setSpacing(8)
        self.display_title = QLabel()
        self.display_title.setObjectName("detailTitle")
        self.display_meta = QLabel()
        self.display_meta.setObjectName("detailMeta")
        self.display_meta.setWordWrap(True)
        self.display_status = QLabel()
        self.display_status.setObjectName("detailStatus")
        self.display_status.setWordWrap(True)
        detail_layout.addWidget(self.display_title)
        detail_layout.addWidget(self.display_meta)
        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)
        low = QLabel("-100%")
        low.setObjectName("hintLabel")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-100, 100)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(5)
        self.slider.setTickInterval(25)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider.setAccessibleName("Saturation adjustment for the selected display")
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.slider.sliderReleased.connect(self._flush_apply)
        self.value_label = QLabel("0%")
        self.value_label.setObjectName("valueLabel")
        self.value_label.setMinimumWidth(72)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        slider_row.addWidget(low)
        slider_row.addWidget(self.slider, 1)
        slider_row.addWidget(self.value_label)
        high = QLabel("+100%")
        high.setObjectName("hintLabel")
        slider_row.addWidget(high)
        detail_layout.addLayout(slider_row)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        preset_label = QLabel("Presets")
        preset_label.setObjectName("hintLabel")
        preset_row.addWidget(preset_label)
        for name, value in PRESETS:
            button = QPushButton(name)
            button.setObjectName("presetButton")
            button.setToolTip(f"Set saturation to {format_percent(value)}")
            button.clicked.connect(lambda checked=False, percent=value: self._set_preset(percent))
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        detail_layout.addLayout(preset_row)
        detail_layout.addWidget(self.display_status)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.restore_button = QPushButton("Restore saved")
        self.restore_button.clicked.connect(self._restore_selected)
        self.reset_button = QPushButton("Reset display")
        self.reset_button.clicked.connect(self.reset_selected)
        self.identify_button = QPushButton("Identify display")
        self.identify_button.clicked.connect(self.identify_selected)
        action_row.addWidget(self.restore_button)
        action_row.addWidget(self.reset_button)
        action_row.addWidget(self.identify_button)
        action_row.addStretch(1)
        detail_layout.addLayout(action_row)
        hint = QLabel(
            "Changes apply to the selected physical display only. Vivid generates a "
            "synthetic ICC profile and asks KScreen/KWin to use it."
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        detail_layout.addWidget(hint)
        layout.addWidget(self.detail)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda: self.refresh_displays())
        reset_all = QPushButton("Reset all…")
        reset_all.clicked.connect(self.reset_all_with_confirmation)
        settings = QPushButton("Settings…")
        settings.clicked.connect(self.open_settings)
        diagnostics = QPushButton("Diagnostics…")
        diagnostics.clicked.connect(self.open_diagnostics)
        footer.addWidget(refresh)
        footer.addWidget(reset_all)
        footer.addStretch(1)
        footer.addWidget(settings)
        footer.addWidget(diagnostics)
        layout.addLayout(footer)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")
        self._apply_style()
        self._set_detail_enabled(False)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QLabel#appTitle { font-size: 24px; font-weight: 600; }
            QLabel#appSubtitle { color: palette(mid); }
            QLabel#backendBadge { padding: 3px 9px; border-radius: 8px;
                                  background: palette(alternate-base); }
            QLabel#backendBadge[error="true"] { border: 1px solid palette(bright-text); }
            QLabel#errorBanner { padding: 8px 10px; border: 1px solid palette(mid);
                                 border-radius: 6px; background: palette(alternate-base); }
            QFrame#detailPanel { border: 1px solid palette(mid); border-radius: 10px; }
            QLabel#detailTitle { font-size: 18px; font-weight: 600; }
            QLabel#detailMeta, QLabel#hintLabel { color: palette(mid); }
            QLabel#detailStatus { padding-top: 2px; }
            QLabel#valueLabel { font-size: 20px; font-weight: 600; }
            QFrame#displayCard { border: 1px solid palette(mid); border-radius: 9px;
                                 background: palette(alternate-base); }
            QFrame#displayCard[selected="true"] { border: 2px solid palette(highlight); }
            QFrame#displayCard[conflict="true"] { border: 1px solid palette(bright-text); }
            QLabel#displayTitle { font-size: 14px; font-weight: 600; }
            QLabel#displaySubtitle { color: palette(mid); }
            QLabel#displayValue { font-size: 15px; font-weight: 600; }
            QLabel#displayStatus { color: palette(mid); }
            QPushButton#presetButton { padding: 3px 10px; }
            """
        )

    def _build_menus(self) -> None:
        menu = self.menuBar()
        file_menu = menu.addMenu("&File")
        refresh = QAction("Refresh displays", self)
        refresh.setShortcut("F5")
        refresh.triggered.connect(lambda: self.refresh_displays())
        file_menu.addAction(refresh)
        settings = QAction("Settings…", self)
        settings.triggered.connect(self.open_settings)
        file_menu.addAction(settings)
        diagnostics = QAction("Diagnostics…", self)
        diagnostics.triggered.connect(self.open_diagnostics)
        file_menu.addAction(diagnostics)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_action)
        display_menu = menu.addMenu("&Display")
        identify = QAction("Identify selected display", self)
        identify.setShortcut("Ctrl+I")
        identify.triggered.connect(self.identify_selected)
        display_menu.addAction(identify)
        reset = QAction("Reset selected display", self)
        reset.triggered.connect(self.reset_selected)
        display_menu.addAction(reset)
        reset_all = QAction("Reset all displays…", self)
        reset_all.triggered.connect(self.reset_all_with_confirmation)
        display_menu.addAction(reset_all)
        help_menu = menu.addMenu("&Help")
        docs = QAction("Recovery guide", self)
        docs.triggered.connect(self._open_recovery_guide)
        help_menu.addAction(docs)
        about = QAction("About Vivid", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    def _connect_hotplug(self) -> None:
        app = QGuiApplication.instance()
        if app is None:
            return
        app.screenAdded.connect(self._on_screen_added)
        app.screenRemoved.connect(self._on_screen_removed)

    def _on_screen_added(self, screen) -> None:
        self.statusBar().showMessage(f"Display connected: {screen.name()}", 5000)
        QTimer.singleShot(1200, lambda: self.refresh_displays(after_hotplug=True))

    def _on_screen_removed(self, screen) -> None:
        self.statusBar().showMessage(f"Display disconnected: {screen.name()}", 5000)
        QTimer.singleShot(500, lambda: self.refresh_displays())

    def _setup_tray(self) -> None:
        if not self._tray and VividTray.isSystemTrayAvailable():
            try:
                self._tray = VividTray(self)
                self._tray.update_displays(self._all_views(), self.selected_id)
                self._tray.show()
            except Exception as exc:  # tray is optional
                self.log.warning("system tray unavailable: %s", exc)
                self._tray = None

    # -------------------------------------------------------------- helpers
    def _all_views(self) -> list[DisplayView]:
        return self.views + self.inactive_views

    def _view_for(self, stable_id: str | None) -> DisplayView | None:
        if stable_id is None:
            return None
        for view in self._all_views():
            if view.display.identity and view.display.identity.stable_id == stable_id:
                return view
        return None

    def _active_view_for(self, stable_id: str | None) -> DisplayView | None:
        view = self._view_for(stable_id)
        if view is not None and view.display.connected:
            return view
        return None

    def _set_detail_enabled(self, enabled: bool) -> None:
        for widget in (
            self.slider,
            self.reset_button,
            self.identify_button,
            self.restore_button,
        ):
            widget.setEnabled(enabled)

    def _show_error(self, message: str) -> None:
        self.error_banner.setText(f"<b>Action failed.</b> {message}")
        self.error_banner.setVisible(True)
        self.statusBar().showMessage("Error — see message above", 8000)

    def _clear_error(self) -> None:
        self.error_banner.clear()
        self.error_banner.setVisible(False)

    def _run(self, function: Callable[[], Any], on_result: Callable[[Any], None]) -> None:
        task = Task(function)
        task.setAutoDelete(False)
        self._tasks.add(task)

        def finish() -> None:
            self._tasks.discard(task)
            if self._quick_pending:
                self._quick_apply_timer.start()

        def handle_result(result: Any) -> None:
            try:
                on_result(result)
            finally:
                finish()

        def handle_error(message: str) -> None:
            try:
                self._show_error(message)
            finally:
                finish()

        task.signals.result.connect(handle_result)
        task.signals.error.connect(handle_error)
        self.pool.start(task)

    def _wait_for_tasks(self, timeout_ms: int = 8000) -> bool:
        return self.pool.waitForDone(timeout_ms)

    # ------------------------------------------------------------- refresh
    def refresh_displays(
        self,
        after_hotplug: bool = False,
        quiet: bool = False,
        select_id: str | None = None,
    ) -> None:
        if self._refresh_in_flight:
            self._refresh_again = True
            return
        if (
            self._apply_in_flight
            or self._pending_percent is not None
            or self._apply_timer.isActive()
            or self.slider.isSliderDown()
        ):
            QTimer.singleShot(
                900,
                lambda: self.refresh_displays(
                    after_hotplug=after_hotplug, quiet=quiet, select_id=select_id
                ),
            )
            return
        self._refresh_in_flight = True
        if not quiet:
            self.statusBar().showMessage("Discovering displays…")

        def work() -> tuple[Any, list[DisplayView], list[DisplayView], Any]:
            restore_report = None
            if after_hotplug:
                restore_report = self.service.restore_saved(quiet=True)
            discovery = self.service.discover()
            return (
                discovery,
                self.service.views(discovery),
                self.service.inactive_views(discovery),
                restore_report,
            )

        self._run(work, lambda result: self._refresh_done(result, select_id))

    def _refresh_done(self, result: tuple[Any, list, list, Any], select_id: str | None) -> None:
        self._refresh_in_flight = False
        discovery, views, inactive, restore_report = result
        self.views = views
        self.inactive_views = inactive
        wanted = select_id or self.selected_id
        all_views = self._all_views()
        available = {
            _view_stable_id(view) for view in all_views if view.display.identity is not None
        }
        if wanted not in available:
            wanted = next(
                (_view_stable_id(view) for view in all_views if view.display.identity is not None),
                None,
            )
        self._rebuild_cards(wanted)
        self._update_backend_badge()
        if getattr(discovery, "warnings", None):
            self.statusBar().showMessage("; ".join(discovery.warnings), 8000)
        elif not self.views:
            self.statusBar().showMessage("No connected displays found", 8000)
        else:
            self.statusBar().showMessage(f"{len(self.views)} connected display(s)", 4000)
        if restore_report is not None:
            if restore_report.errors:
                messages = "; ".join(error.get("message", "") for error in restore_report.errors)
                self._show_error(f"Automatic restore had errors: {messages}")
            elif restore_report.changed:
                self.statusBar().showMessage(
                    f"Restored saved settings on {restore_report.changed} display(s)",
                    6000,
                )
        if self._refresh_again:
            self._refresh_again = False
            QTimer.singleShot(250, lambda: self.refresh_displays(quiet=True))

    def _update_backend_badge(self) -> None:
        capabilities = self.service.capabilities
        if capabilities.supported:
            self.backend_badge.setText(f"KScreen ready · Plasma {capabilities.plasma_version}")
            self.backend_badge.setProperty("error", False)
            self.backend_badge.setToolTip(
                f"Backend {self.service.backend.name}; Little CMS {capabilities.lcms_version}"
            )
        else:
            self.backend_badge.setText("Backend unavailable — open Diagnostics")
            self.backend_badge.setProperty("error", True)
            self.backend_badge.setToolTip("; ".join(capabilities.reasons))
        self.backend_badge.style().unpolish(self.backend_badge)
        self.backend_badge.style().polish(self.backend_badge)

    def _rebuild_cards(self, wanted_id: str | None) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.cards.clear()
        all_views = self._all_views()
        for view in all_views:
            stable_id = view.display.identity.stable_id if view.display.identity else ""
            card = DisplayCard(view)
            card.selected.connect(self._on_card_selected)
            self.cards[stable_id] = card
            self.cards_layout.addWidget(card)
        self.cards_layout.addStretch(1)
        self.empty_label.setVisible(not all_views)
        self.selected_id = wanted_id
        if wanted_id is not None:
            self._select_display(wanted_id)
        elif all_views and all_views[0].display.identity:
            self._select_display(all_views[0].display.identity.stable_id)
        else:
            self.selected_id = None
            self._set_detail_enabled(False)
            self.display_title.setText("No display selected")
            self.display_meta.setText("")
            self.display_status.setText("")
        if self._tray is not None:
            self._tray.update_displays(self._all_views(), self.selected_id)

    def _on_card_selected(self, display: DisplayInfo) -> None:
        if display.identity is not None:
            self._select_display(display.identity.stable_id)

    def _select_display(self, stable_id: str) -> None:
        view = self._view_for(stable_id)
        if view is None:
            return
        self._apply_timer.stop()
        self._pending_percent = None
        self.selected_id = stable_id
        for card_id, card in self.cards.items():
            card.set_selected(card_id == stable_id)
        self.display_title.setText(view.display.friendly_name)
        kind = "Internal" if view.display.internal else "External"
        self.display_meta.setText(
            f"{view.display.output_name}  ·  {kind}  ·  {view.display.mode_label}"
        )
        self._updating_slider = True
        self.slider.setValue(view.preferred_saturation)
        self._updating_slider = False
        self._update_value_label(view.preferred_saturation)
        self._update_detail_status(view)
        active = view.display.connected and self.service.capabilities.supported
        self._set_detail_enabled(active)
        self.restore_button.setEnabled(
            active
            and view.saved
            and view.preferred_saturation != 0
            and view.status != DisplayStatus.APPLIED
        )
        if not view.display.connected:
            self.display_status.setText(
                "This saved display is not connected. Its preference will be available "
                "when it reconnects."
            )
        elif not self.service.capabilities.supported:
            self.display_status.setText("; ".join(self.service.capabilities.reasons))
        if self._tray is not None:
            self._tray.update_displays(self._all_views(), self.selected_id)

    def _update_detail_status(self, view: DisplayView) -> None:
        prefix = ""
        if view.status in (DisplayStatus.CONFLICT, DisplayStatus.FAILED):
            prefix = "Attention: "
        elif view.status == DisplayStatus.NEEDS_CONFIRMATION:
            prefix = "Confirmation needed: "
        elif view.status == DisplayStatus.APPLIED:
            prefix = "Applied: "
        self.display_status.setText(prefix + (view.message or "Ready."))
        self.display_status.setToolTip(view.message)
        self._set_detail_enabled(view.display.connected and self.service.capabilities.supported)
        self.restore_button.setEnabled(
            view.display.connected
            and view.saved
            and view.preferred_saturation != 0
            and view.status != DisplayStatus.APPLIED
        )

    def _update_value_label(self, percent: int) -> None:
        self.value_label.setText(format_percent(percent))

    # --------------------------------------------------------------- apply
    def _on_slider_changed(self, value: int) -> None:
        if self._updating_slider:
            return
        self._pending_percent = value
        self._update_value_label(value)
        view = self._active_view_for(self.selected_id)
        if view is None:
            return
        self.display_status.setText(
            f"Pending {format_percent(value)}… release the slider or wait a moment to apply."
        )
        self._apply_timer.start()

    def _set_preset(self, percent: int) -> None:
        if not self.slider.isEnabled():
            return
        self._updating_slider = True
        self.slider.setValue(percent)
        self._updating_slider = False
        self._pending_percent = percent
        self._update_value_label(percent)
        self._flush_apply()

    def _flush_apply(self) -> None:
        self._apply_timer.stop()
        if self._pending_percent is None:
            return
        view = self._active_view_for(self.selected_id)
        if view is None:
            self._pending_percent = None
            return
        percent = self._pending_percent
        self._pending_percent = None
        stable_id = view.display.identity.stable_id if view.display.identity else ""
        if view.status == DisplayStatus.APPLIED and view.applied_saturation == percent:
            self._update_detail_status(view)
            return
        if (
            percent != 0
            and view.display.identity_ambiguous
            and stable_id not in self._confirmed_ambiguous
        ):
            answer = QMessageBox.question(
                self,
                "Confirm display identity",
                "This monitor does not expose a unique hardware identity, so Vivid "
                f"cannot distinguish it from another output with the same EDID.\n\n"
                f"Apply {format_percent(percent)} to {view.display.output_name} "
                f"({view.display.friendly_name})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._updating_slider = True
                self.slider.setValue(view.preferred_saturation)
                self._updating_slider = False
                self._update_value_label(view.preferred_saturation)
                self._update_detail_status(view)
                return
            self._confirmed_ambiguous.add(stable_id)
        self._apply_token += 1
        token = self._apply_token
        self._apply_in_flight = True
        output_name = view.display.output_name
        self.display_status.setText(
            f"Applying {format_percent(percent)} to {output_name}…"
        )
        self.statusBar().showMessage(
            f"Applying {format_percent(percent)} to {output_name}…"
        )
        self._clear_error()
        self._run(
            lambda: self.service.set_saturation(output_name, percent, confirm_ambiguous=True),
            lambda result: self._apply_done(token, stable_id, percent, result),
        )

    def _apply_done(self, token: int, stable_id: str, percent: int, result: ApplyResult) -> None:
        if token == self._apply_token:
            self._apply_in_flight = False
        if token != self._apply_token:
            return
        view = self._view_for(stable_id)
        if result.success:
            self.statusBar().showMessage(f"Applied {format_percent(percent)}", 4000)
            self._clear_error()
            if view is not None:
                updated = replace(
                    view,
                    preferred_saturation=percent,
                    applied_saturation=percent,
                    status=DisplayStatus.APPLIED,
                    message=result.message,
                    applied_profile_path=result.profile_path,
                    saved=True,
                )
                self._replace_view(updated)
                if self.selected_id == stable_id:
                    self._update_detail_status(updated)
        else:
            if view is not None:
                updated = replace(
                    view,
                    status=result.status,
                    message=result.message,
                )
                self._replace_view(updated)
                if self.selected_id == stable_id:
                    self._update_detail_status(updated)
            self._show_error(result.message)

    def _replace_view(self, updated: DisplayView) -> None:
        stable_id = updated.display.identity.stable_id if updated.display.identity else ""
        for index, view in enumerate(self.views):
            if view.display.identity and view.display.identity.stable_id == stable_id:
                self.views[index] = updated
                break
        else:
            for index, view in enumerate(self.inactive_views):
                if view.display.identity and view.display.identity.stable_id == stable_id:
                    self.inactive_views[index] = updated
                    break
        card = self.cards.get(stable_id)
        if card is not None:
            card.apply_view(updated)
        if self._tray is not None:
            self._tray.update_displays(self._all_views(), self.selected_id)

    def queue_quick_saturation(self, stable_id: str, percent: int) -> None:
        self._quick_pending[stable_id] = percent
        self._quick_apply_timer.start()

    def _flush_quick_apply(self) -> None:
        if not self._quick_pending:
            return
        if self._apply_in_flight or self._refresh_in_flight:
            return
        if self._pending_percent is not None or self._apply_timer.isActive():
            return
        if self.slider.isSliderDown():
            self._quick_apply_timer.start(200)
            return

        stable_id, percent = next(iter(self._quick_pending.items()))
        del self._quick_pending[stable_id]
        view = self._active_view_for(stable_id)
        if view is None:
            self._quick_apply_timer.start()
            return
        if view.status == DisplayStatus.APPLIED and view.applied_saturation == percent:
            self._quick_apply_timer.start()
            return
        if (
            percent != 0
            and view.display.identity_ambiguous
            and stable_id not in self._confirmed_ambiguous
        ):
            answer = QMessageBox.question(
                self,
                "Confirm display identity",
                "This monitor does not expose a unique hardware identity, so Vivid "
                f"cannot distinguish it from another output with the same EDID.\n\n"
                f"Apply {format_percent(percent)} to {view.display.output_name} "
                f"({view.display.friendly_name})?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._quick_apply_timer.start()
                return
            self._confirmed_ambiguous.add(stable_id)

        self._apply_token += 1
        token = self._apply_token
        self._apply_in_flight = True
        output_name = view.display.output_name
        if self.selected_id == stable_id:
            self.display_status.setText(
                f"Applying {format_percent(percent)} to {output_name}…"
            )
        self._clear_error()
        self._run(
            lambda: self.service.set_saturation(
                output_name, percent, confirm_ambiguous=True
            ),
            lambda result: self._apply_done(token, stable_id, percent, result),
        )

    # --------------------------------------------------------------- actions
    def _restore_selected(self) -> None:
        view = self._active_view_for(self.selected_id)
        if view is None or not view.saved or view.preferred_saturation == 0:
            return
        percent = view.preferred_saturation
        output_name = view.display.output_name
        self.statusBar().showMessage(
            f"Restoring saved {format_percent(percent)} to {output_name}…"
        )
        self._clear_error()
        stable_id = view.display.identity.stable_id if view.display.identity else ""
        self._apply_token += 1
        token = self._apply_token
        self._apply_in_flight = True
        self._run(
            lambda: self.service.set_saturation(output_name, percent, confirm_ambiguous=True),
            lambda result: self._apply_done(token, stable_id, percent, result),
        )

    def reset_selected(self) -> None:
        view = self._active_view_for(self.selected_id)
        if view is None:
            return
        output_name = view.display.output_name
        stable_id = view.display.identity.stable_id if view.display.identity else ""
        self.statusBar().showMessage(f"Restoring the original profile for {output_name}…")
        self._clear_error()
        self._run(
            lambda: self.service.reset_display(output_name),
            lambda result: self._reset_done(stable_id, result),
        )

    def _reset_done(self, stable_id: str, result: ApplyResult) -> None:
        if not result.success:
            self._show_error(result.message)
            return
        view = self._view_for(stable_id)
        if view is not None:
            updated = replace(
                view,
                preferred_saturation=0,
                applied_saturation=0,
                status=DisplayStatus.ACTIVE,
                message=result.message,
                applied_profile_path="",
                saved=False,
            )
            self._replace_view(updated)
            if self.selected_id == stable_id:
                self._updating_slider = True
                self.slider.setValue(0)
                self._updating_slider = False
                self._update_value_label(0)
                self._update_detail_status(updated)
        self.statusBar().showMessage("Original profile restored", 5000)

    def reset_all_with_confirmation(self) -> None:
        if not self.views:
            self.statusBar().showMessage("No connected displays to reset", 4000)
            return
        answer = QMessageBox.question(
            self,
            "Reset all displays?",
            "Restore the original colour profile assignment for every display that "
            "Vivid changed? Displays that Vivid did not change are left untouched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.statusBar().showMessage("Restoring original profiles…")
        self._clear_error()
        self._run(
            lambda: self.service.reset_all(),
            self._reset_all_done,
        )

    def _reset_all_done(self, results: list[ApplyResult]) -> None:
        failures = [result for result in results if not result.success]
        if failures:
            self._show_error("; ".join(result.message for result in failures))
        else:
            self.statusBar().showMessage(f"Restored {len(results)} display(s)", 5000)
        self.refresh_displays(quiet=True, select_id=self.selected_id)

    def identify_selected(self) -> None:
        view = self._active_view_for(self.selected_id)
        if view is None:
            return
        try:
            show_identify([view.display], application=QApplication.instance())
        except Exception as exc:
            self._show_error(f"Could not show the identification overlay: {exc}")

    def open_settings(self) -> None:
        if not self._wait_for_tasks(5000):
            self.statusBar().showMessage("Waiting for the current display operation…", 4000)
            return
        dialog = SettingsDialog(self.service, self)
        if dialog.exec():
            self.statusBar().showMessage("Settings saved", 4000)
            self.refresh_displays(quiet=True, select_id=self.selected_id)

    def open_diagnostics(self) -> None:
        if not self._wait_for_tasks(8000):
            self.statusBar().showMessage("Waiting for the current display operation…", 4000)
            return
        DiagnosticsDialog(self.service, self).exec()

    def show_from_tray(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def show_and_select(self, stable_id: str) -> None:
        self.show_from_tray()
        self._select_display(stable_id)

    def _open_recovery_guide(self) -> None:
        docs = Path(__file__).resolve().parents[3] / "docs" / "RECOVERY.md"
        QMessageBox.information(
            self,
            "Recovery guide",
            f"See {docs}\n\n"
            "You can also reset every Vivid-adjusted display from Settings, or run:\n"
            "  vivid reset --all",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Vivid",
            f"<h3>Vivid {APP_VERSION}</h3>"
            "<p>Independent display saturation control for Fedora KDE Plasma Wayland.</p>"
            f"<p>Application ID: {APP_ID}<br>License: MIT</p>"
            "<p>Vivid generates colour profiles with Little CMS and applies them "
            "through KScreen and KWin. It is not affiliated with the KDE project.</p>",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._apply_timer.stop()
        self._quick_apply_timer.stop()
        self._poll_timer.stop()
        if self._tray is not None:
            self._tray.hide()
        self.pool.clear()
        if not self._wait_for_tasks(5000):
            self.log.warning("display worker still running while closing")
        super().closeEvent(event)

    def set_tray(self, tray: VividTray | None) -> None:
        self._tray = tray


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vivid-gui", description="Vivid display saturation GUI")
    parser.add_argument(
        "--screenshot",
        metavar="PATH",
        help="render the window to PATH and exit (testing aid)",
    )
    parser.add_argument("--identify", metavar="DISPLAY", help="show the identify overlay and exit")
    parser.add_argument("--version", action="version", version=f"Vivid {APP_VERSION}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_args(argv)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    setup_logging()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Vivid")
    app.setApplicationDisplayName("Vivid")
    app.setOrganizationName("Vivid")
    app.setDesktopFileName(APP_ID)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon.fromTheme("preferences-desktop-display"))
    service = VividService()
    if arguments.identify:
        try:
            display = service.identify(arguments.identify)
        except Exception as exc:
            print(f"Could not identify display: {exc}", file=sys.stderr)
            return 1
        show_identify([display], application=app)
        QTimer.singleShot(2400, app.quit)
        return app.exec()
    window = MainWindow(service)
    window.show()
    if arguments.screenshot:
        target = Path(arguments.screenshot)
        target.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(12):
            app.processEvents()
        QTimer.singleShot(
            1200,
            lambda: _save_screenshot(window, target, app),
        )
    return app.exec()


def _save_screenshot(window: MainWindow, target: Path, app: QApplication) -> None:
    pixmap = window.grab()
    if not pixmap.save(str(target)):
        print(f"Could not save screenshot to {target}", file=sys.stderr)
        app.exit(1)
        return
    print(str(target))
    window.close()
    app.quit()


if __name__ == "__main__":
    raise SystemExit(main())
