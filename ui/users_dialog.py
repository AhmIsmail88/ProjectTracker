"""ui/users_dialog.py

Manager-only account management: add users, change role / display name /
active state, and set or reset passwords. Accounts live in database.py; the
session and permission helpers live in auth.py.
"""

from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from PySide6.QtCore import Qt

from i18n import tr_text
import auth


def _role_label(role):
    return tr_text("Manager") if role == "manager" else tr_text("Engineer")


class UsersDialog(QDialog):
    """List accounts and let the manager create/edit them."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(tr_text("Users"))
        self.setMinimumSize(560, 400)

        layout = QVBoxLayout(self)
        hint = QLabel(tr_text("Accounts for this data folder. Engineers can edit only the projects assigned to them."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([tr_text("Username"), tr_text("Role"),
                                             tr_text("Projects"), tr_text("Active")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.add_btn = QPushButton(tr_text("Add User\u2026"))
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.clicked.connect(self._add)
        self.edit_btn = QPushButton(tr_text("Edit\u2026"))
        self.edit_btn.clicked.connect(self._edit)
        self.password_btn = QPushButton(tr_text("Set Password\u2026"))
        self.password_btn.clicked.connect(self._set_password)
        self.assign_btn = QPushButton(tr_text("Assign Projects…"))
        self.assign_btn.clicked.connect(self._assign_projects)
        self.delete_btn = QPushButton(tr_text("Delete User"))
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_user)
        close_btn = QPushButton(tr_text("Close"))
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.add_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.password_btn)
        row.addWidget(self.assign_btn)
        row.addWidget(self.delete_btn)
        row.addStretch()
        row.addWidget(close_btn)
        layout.addLayout(row)

        if not auth.is_manager(self.db):
            self.add_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            self.password_btn.setEnabled(False)
            self.assign_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

        self._reload()

    # ------------------------------------------------------------------ #
    def _reload(self):
        users = self.db.list_users()
        per_user = {}
        for project in self.db.get_projects():
            owner = project["assigned_user_id"]
            if owner:
                per_user[owner] = per_user.get(owner, 0) + 1
        self.table.setRowCount(len(users))
        for index, user in enumerate(users):
            name_item = QTableWidgetItem(user["username"])
            name_item.setData(Qt.UserRole, user["id"])
            self.table.setItem(index, 0, name_item)
            self.table.setItem(index, 1, QTableWidgetItem(_role_label(user["role"])))
            self.table.setItem(index, 2, QTableWidgetItem(str(per_user.get(user["id"], 0))))
            self.table.setItem(index, 3, QTableWidgetItem(tr_text("Yes") if user["is_active"] else tr_text("No")))
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(2)
        self.table.resizeColumnToContents(3)

    def _selected_user(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, tr_text("Users"), tr_text("Select a user first."))
            return None
        user_id = self.table.item(row, 0).data(Qt.UserRole)
        return self.db.get_user(user_id)

    # ------------------------------------------------------------------ #
    def _add(self):
        if not auth.is_manager(self.db):
            return
        dialog = _UserEditDialog(self, self.db, user=None)
        if dialog.exec() == QDialog.Accepted:
            self._reload()

    def _edit(self):
        if not auth.is_manager(self.db):
            return
        user = self._selected_user()
        if user is None:
            return
        dialog = _UserEditDialog(self, self.db, user=user)
        if dialog.exec() == QDialog.Accepted:
            self._reload()

    def _set_password(self):
        if not auth.is_manager(self.db):
            return
        user = self._selected_user()
        if user is None:
            return
        _PasswordDialog(self, self.db, user=user).exec()
    def _assign_projects(self):
        if not auth.is_manager(self.db):
            return
        user = self._selected_user()
        if user is None:
            return
        if _AssignProjectsDialog(self, self.db, user).exec() == QDialog.Accepted:
            self._reload()

    def _delete_user(self):
        if not auth.is_manager(self.db):
            return
        user = self._selected_user()
        if user is None:
            return
        current = auth.current_user()
        if current is not None and current["id"] == user["id"]:
            QMessageBox.information(
                self, tr_text("Users"),
                tr_text("You cannot delete the account you are signed in with."))
            return
        answer = QMessageBox.question(
            self, tr_text("Delete User"),
            tr_text("Delete user {name}? Projects assigned to them will be unassigned.")
                .format(name=user["username"]))
        if answer != QMessageBox.Yes or not auth.is_manager(self.db):
            return
        try:
            self.db.delete_user(user["id"])
        except ValueError as exc:
            QMessageBox.warning(self, tr_text("Users"), tr_text(str(exc)))
            return
        self._reload()



class _AssignProjectsDialog(QDialog):
    """Tick the projects one account may change (engineers edit only these)."""

    def __init__(self, parent, db, user):
        super().__init__(parent)
        self.db = db
        self.user = user
        self.setWindowTitle(tr_text("Assign Projects"))
        self.setMinimumSize(420, 460)

        layout = QVBoxLayout(self)
        title = QLabel(tr_text("Username") + ": " + user["username"])
        title.setObjectName("detailTitle")
        layout.addWidget(title)
        hint = QLabel(tr_text("Tick the projects this account may edit."))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        projects = self.db.get_projects()
        assigned = {p["id"] for p in projects if p["assigned_user_id"] == user["id"]}
        for project in projects:
            label = project["name"]
            if project["project_number"]:
                label += f"  ({project['project_number']})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, project["id"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if project["id"] in assigned else Qt.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _checked_ids(self):
        ids = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _on_accept(self):
        if not auth.is_manager(self.db):
            QMessageBox.warning(self, tr_text("Users"), tr_text("Only the manager can manage user accounts."))
            return
        self.db.assign_projects_to_user(self.user["id"], self._checked_ids())
        self.accept()


class _UserEditDialog(QDialog):
    """Add a new account, or edit an existing one's role/details."""

    def __init__(self, parent, db, user=None):
        super().__init__(parent)
        self.db = db
        self.user = user
        self.setWindowTitle(tr_text("Add User") if user is None else tr_text("Edit User"))
        self.setMinimumWidth(380)

        form = QFormLayout()
        self.username_edit = QLineEdit(user["username"] if user else "")
        form.addRow(tr_text("Username"), self.username_edit)
        self.display_edit = QLineEdit((user["display_name"] or "") if user else "")
        form.addRow(tr_text("Display name"), self.display_edit)
        self.role_combo = QComboBox()
        self.role_combo.addItem(tr_text("Engineer"), "user")
        self.role_combo.addItem(tr_text("Manager"), "manager")
        if user:
            self.role_combo.setCurrentIndex(max(0, self.role_combo.findData(user["role"])))
        form.addRow(tr_text("Role"), self.role_combo)
        self.active_check = QCheckBox(tr_text("Active"))
        self.active_check.setChecked(bool(user["is_active"]) if user else True)
        form.addRow("", self.active_check)
        if user is None:
            self.password_edit = QLineEdit()
            self.password_edit.setEchoMode(QLineEdit.Password)
            form.addRow(tr_text("Password"), self.password_edit)
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setEchoMode(QLineEdit.Password)
            form.addRow(tr_text("Confirm password"), self.confirm_edit)
        else:
            self.password_edit = None
            self.confirm_edit = None

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not auth.is_manager(self.db):
            QMessageBox.warning(self, tr_text("Users"), tr_text("Only the manager can manage user accounts."))
            return
        username = self.username_edit.text().strip()
        if not username:
            QMessageBox.warning(self, tr_text("Users"), tr_text("Please fill in all fields."))
            return
        role = self.role_combo.currentData()
        active = 1 if self.active_check.isChecked() else 0

        if self.user is None:
            password = self.password_edit.text()
            if not password or password != self.confirm_edit.text():
                message = ("Passwords do not match."
                           if (password or self.confirm_edit.text())
                           else "Please fill in all fields.")
                QMessageBox.warning(self, tr_text("Users"), tr_text(message))
                return
            try:
                self.db.add_user(username, password, role=role,
                                 display_name=self.display_edit.text().strip(), is_active=active)
            except ValueError as exc:
                QMessageBox.warning(self, tr_text("Users"), tr_text(str(exc)))
                return
            self.accept()
            return

        # Editing: never leave zero active managers behind.
        was_manager = self.user["role"] == "manager" and self.user["is_active"]
        stays_manager = role == "manager" and active == 1
        if was_manager and not stays_manager:
            managers = [u for u in self.db.list_users(active_only=True) if u["role"] == "manager"]
            if len(managers) <= 1:
                QMessageBox.warning(self, tr_text("Users"), tr_text("At least one active manager is required."))
                return
        try:
            self.db.update_user(
                self.user["id"], username=username, role=role,
                display_name=self.display_edit.text().strip(), is_active=active,
            )
        except ValueError as exc:
            QMessageBox.warning(self, tr_text("Users"), tr_text(str(exc)))
            return
        self.accept()


class _PasswordDialog(QDialog):
    """Set (or reset) one user's password."""

    def __init__(self, parent, db, user):
        super().__init__(parent)
        self.db = db
        self.user = user
        self.setWindowTitle(tr_text("Set Password"))
        self.setMinimumWidth(360)

        form = QFormLayout()
        form.addRow(tr_text("Username"), QLabel(user["username"]))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr_text("New password"), self.password_edit)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        form.addRow(tr_text("Confirm password"), self.confirm_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _on_accept(self):
        if not auth.is_manager(self.db):
            QMessageBox.warning(self, tr_text("Users"), tr_text("Only the manager can manage user accounts."))
            return
        password = self.password_edit.text()
        if not password:
            QMessageBox.warning(self, tr_text("Users"), tr_text("Please fill in all fields."))
            return
        if password != self.confirm_edit.text():
            QMessageBox.warning(self, tr_text("Users"), tr_text("Passwords do not match."))
            return
        self.db.set_password(self.user["id"], password)
        self.accept()
