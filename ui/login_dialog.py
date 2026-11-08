"""ui/login_dialog.py

Startup sign-in gate: create the very first manager account when no accounts
exist yet, otherwise ask for username + password. Exposed as a single helper
(run_login_flow) so main.py needs only one minimal hook.

The screen follows the app's saved language (defaults to English) and can be
switched between Arabic and English right here, before signing in.
"""

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

import auth
import i18n
from i18n import tr, tr_text


def _settings():
    return QSettings("ProjectTracker", "MainWindow")


def _login_language():
    """Language for the sign-in screen: the saved setting, else English."""
    value = _settings().value("language", "en")
    return "ar" if value == "ar" else "en"


def _apply_app_style():
    """Match the rest of the app before the main window exists."""
    app = QApplication.instance()
    if app is None:
        return
    from constants import get_theme, set_theme
    from ui.styles import get_stylesheet
    set_theme(_settings().value("theme", "dark"))
    scale = _settings().value("interface_scale", 1.0, type=float)
    rtl = i18n.get_language() == "ar"
    app.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    app.setStyleSheet(get_stylesheet(get_theme(), rtl=rtl, scale=scale))


class LoginDialog(QDialog):
    """Sign-in dialog; also used in "first run" mode to create the manager."""

    def __init__(self, db, parent=None, first_run=False, establish_session=True):
        super().__init__(parent)
        self.db = db
        self.first_run = first_run
        self.establish_session = establish_session
        self.user = None
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        self.heading = QLabel()
        self.heading.setObjectName("pageTitle")
        layout.addWidget(self.heading)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        form = QFormLayout()
        self.username_label = QLabel()
        self.username_edit = QLineEdit()
        form.addRow(self.username_label, self.username_edit)
        self.password_label = QLabel()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow(self.password_label, self.password_edit)
        self.confirm_label = QLabel()
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        form.addRow(self.confirm_label, self.confirm_edit)
        layout.addLayout(form)

        buttons_row = QHBoxLayout()
        self.lang_btn = QPushButton()
        self.lang_btn.setObjectName("linkButton")
        self.lang_btn.setCursor(Qt.PointingHandCursor)
        self.lang_btn.clicked.connect(self._switch_language)
        buttons_row.addWidget(self.lang_btn)
        buttons_row.addStretch()
        buttons = QDialogButtonBox()
        self.ok_btn = buttons.addButton("", QDialogButtonBox.AcceptRole)
        self.ok_btn.setObjectName("primaryButton")
        self.exit_btn = buttons.addButton("", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons_row.addWidget(buttons)
        layout.addLayout(buttons_row)

        self.password_edit.returnPressed.connect(self._on_accept)

        self._retranslate()

    # ------------------------------------------------------------------ #
    def _retranslate(self):
        """(Re)apply every label in the currently selected language."""
        arabic = i18n.get_language() == "ar"
        self.setLayoutDirection(Qt.RightToLeft if arabic else Qt.LeftToRight)
        self.setWindowTitle(
            tr_text("Create the first manager account") if self.first_run else tr("app_title")
        )
        self.heading.setText(tr("app_title"))
        self.hint.setText(tr_text("There are no accounts yet. Create the manager account to get started."))
        self.hint.setVisible(self.first_run)
        self.username_label.setText(tr_text("Username"))
        self.password_label.setText(tr_text("Password"))
        self.confirm_label.setText(tr_text("Confirm password"))
        self.confirm_label.setVisible(self.first_run)
        self.confirm_edit.setVisible(self.first_run)
        self.ok_btn.setText(tr_text("Create manager account") if self.first_run else tr_text("Sign in"))
        self.exit_btn.setText(tr_text("Exit"))
        self.lang_btn.setText(tr("login_lang_switch"))

    def _switch_language(self):
        new_lang = "en" if i18n.get_language() == "ar" else "ar"
        i18n.set_language(new_lang)
        _settings().setValue("language", new_lang)
        _apply_app_style()
        self._retranslate()

    def _on_accept(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, tr("app_title"), tr_text("Please fill in all fields."))
            return
        if self.first_run:
            if password != self.confirm_edit.text():
                QMessageBox.warning(self, tr("app_title"), tr_text("Passwords do not match."))
                return
            try:
                user_id = self.db.add_user(username, password, role="manager")
            except ValueError:
                QMessageBox.warning(self, tr("app_title"), tr_text("Username already exists."))
                return
            self.user = self.db.get_user(user_id)
        else:
            self.user = self.db.verify_user(username, password)
            if self.user is None:
                QMessageBox.warning(self, tr("app_title"), tr_text("Wrong username or password."))
                self.password_edit.selectAll()
                self.password_edit.setFocus()
                return
        if self.establish_session:
            auth.login(self.user, self.db)
        self.accept()


def run_login_flow(db, parent=None):
    """Show the startup gate. Returns True when a user is signed in."""
    i18n.set_language(_login_language())
    _apply_app_style()
    dialog = LoginDialog(db, parent=parent, first_run=db.count_users() == 0)
    return dialog.exec() == QDialog.Accepted
