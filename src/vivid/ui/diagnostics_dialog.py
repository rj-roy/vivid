"""Read-only diagnostics report dialog."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..application import VividService


class DiagnosticsDialog(QDialog):
    def __init__(self, service: VividService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Vivid Diagnostics")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.text, 1)
        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        copy = QPushButton("Copy report")
        copy.clicked.connect(self.copy_report)
        save = QPushButton("Save report…")
        save.clicked.connect(self.save_report)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(refresh)
        buttons.addWidget(copy)
        buttons.addWidget(save)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self) -> None:
        try:
            report = self.service.doctor()
        except Exception as exc:  # diagnostics must never crash the app
            report = {"error": str(exc)}
        self.text.setPlainText(json.dumps(report, indent=2, sort_keys=True))

    def copy_report(self) -> None:
        QGuiApplication.clipboard().setText(self.text.toPlainText())

    def save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save diagnostics report", "vivid-diagnostics.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            Path(path).write_text(self.text.toPlainText() + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Could not save report", str(exc))
