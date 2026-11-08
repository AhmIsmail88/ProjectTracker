from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
                               QDialogButtonBox, QMessageBox)
from ai.settings import read_settings, save_settings
from i18n import tr_text


class AISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr_text("AI Settings"))
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        hint = QLabel(tr_text("Enter your OpenRouter key. Settings are saved for your Windows user and are not included when sharing the app."))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        settings = read_settings()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        self.key_edit.setPlaceholderText(tr_text("Leave blank to keep the saved key") if settings["api_key"] else "sk-or-…")
        form.addRow(tr_text("API key"), self.key_edit)
        self.model_edit = QLineEdit(settings["model"])
        self.model_edit.setLayoutDirection(Qt.LeftToRight)
        form.addRow(tr_text("Model"), self.model_edit)
        layout.addLayout(form)
        note = QLabel(tr_text("Internet access and a valid API key are required. Model availability and usage limits depend on OpenRouter."))
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr_text("Save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr_text("Cancel"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        try:
            save_settings(self.key_edit.text(), self.model_edit.text())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr_text("AI Settings"), tr_text(str(exc)))
            return
        self.accept()
