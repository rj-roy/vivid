"""Settings dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..application import VividService
from ..autostart import disable as disable_autostart
from ..autostart import enable as enable_autostart
from ..autostart import is_enabled


class SettingsDialog(QDialog):
    def __init__(self, service: VividService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Vivid Settings")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        title = QLabel("<h2>Settings</h2>")
        layout.addWidget(title)
        intro = QLabel(
            "Vivid stores preferences in your XDG config directory and keeps "
            "recovery snapshots until a display is safely restored."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.autostart = QCheckBox("Restore saved settings when I log in")
        self.autostart.setChecked(is_enabled())
        form.addRow("Automatic startup", self.autostart)
        self.safe_mode = QCheckBox("Safe mode (never change displays automatically)")
        self.safe_mode.setChecked(service.settings.safe_mode)
        form.addRow("Safe mode", self.safe_mode)
        layout.addLayout(form)
        actions = QHBoxLayout()
        export_button = QPushButton("Export settings…")
        export_button.clicked.connect(self.export_settings)
        import_button = QPushButton("Import settings…")
        import_button.clicked.connect(self.import_settings)
        open_button = QPushButton("Open config folder")
        open_button.clicked.connect(self.open_config_folder)
        actions.addWidget(export_button)
        actions.addWidget(import_button)
        actions.addWidget(open_button)
        layout.addLayout(actions)
        restore_button = QPushButton("Restore all displays to their original profiles")
        restore_button.clicked.connect(self.restore_all)
        layout.addWidget(restore_button)
        note = QLabel(
            "Restoring changes only displays that Vivid adjusted. Displays without "
            "a recovery snapshot are left untouched."
        )
        note.setWordWrap(True)
        note.setObjectName("hintLabel")
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def open_config_folder(self) -> None:
        folder = Path(self.service.settings_store.path).parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def export_settings(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Vivid settings", "vivid-settings.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            target = self.service.export_settings(Path(path))
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        QMessageBox.information(self, "Settings exported", f"Saved to {target}")

    def import_settings(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Vivid settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            settings = self.service.import_settings(Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        applied = self.service.restore_saved(quiet=True)
        QMessageBox.information(
            self,
            "Settings imported",
            f"Imported settings for {len(settings.displays)} display(s). "
            f"{applied.changed} display(s) updated, {len(applied.errors)} error(s).",
        )

    def restore_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore all displays?",
            "This restores the original colour profile assignments for every display "
            "that Vivid changed. Other displays are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        results = self.service.reset_all()
        failures = [result for result in results if not result.success]
        if failures:
            details = "\n".join(result.message for result in failures)
            QMessageBox.warning(
                self,
                "Restore incomplete",
                f"{len(failures)} display(s) could not be restored:\n\n{details}\n\n"
                "Read docs/RECOVERY.md for manual recovery.",
            )
        else:
            QMessageBox.information(
                self, "Restore complete", f"Restored {len(results)} display(s)."
            )

    def accept(self) -> None:
        try:
            if self.autostart.isChecked():
                enable_autostart()
            else:
                disable_autostart()
            self.service.set_safe_mode(self.safe_mode.isChecked())
        except OSError as exc:
            QMessageBox.critical(self, "Could not save settings", str(exc))
            return
        super().accept()
