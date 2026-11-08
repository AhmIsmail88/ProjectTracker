"""
ui/find_replace_dialog.py
"Find & Replace" — fix a recurring typo or standardize inconsistent
wording (e.g. "Pice" -> "Piece", or making everyone's "DN 75" match)
across several selected items' same field at once, instead of opening
each item individually.
"""

from i18n import tr_text
import auth

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QCheckBox, QMessageBox
)


class FindReplaceDialog(QDialog):
    def __init__(self, parent, db, item_ids):
        super().__init__(parent)
        self.db = db
        self.item_ids = list(item_ids)

        self.setWindowTitle(tr_text("Find & Replace"))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"<b>{len(self.item_ids)} item(s) selected</b><br>"
            f"Only items whose field actually contains the text below will be changed."
        ))

        form = QFormLayout()

        self.field_combo = QComboBox()
        for key, label in self.db.BULK_REPLACE_FIELDS:
            self.field_combo.addItem(tr_text(label), key)
        self.field_combo.currentIndexChanged.connect(self._update_preview)
        form.addRow(tr_text("Field:"), self.field_combo)

        self.find_edit = QLineEdit()
        self.find_edit.textChanged.connect(self._update_preview)
        form.addRow(tr_text("Find:"), self.find_edit)

        self.replace_edit = QLineEdit()
        form.addRow(tr_text("Replace with:"), self.replace_edit)

        self.case_check = QCheckBox(tr_text("Case-sensitive"))
        self.case_check.stateChanged.connect(self._update_preview)
        form.addRow("", self.case_check)

        layout.addLayout(form)

        self.preview_label = QLabel(tr_text("Type something in \u201cFind\u201d to see how many items match."))
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton(tr_text("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        self.apply_btn = QPushButton(tr_text("Apply"))
        self.apply_btn.setObjectName("primaryButton")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.apply_btn)
        layout.addLayout(btn_row)

        self._update_preview()

    def _update_preview(self):
        find_text = self.find_edit.text()
        if not find_text:
            self.preview_label.setText("Type something in \u201cFind\u201d to see how many items match.")
            self.apply_btn.setEnabled(False)
            return
        field = self.field_combo.currentData()
        count = self.db.count_find_replace_matches(
            self.item_ids, field, find_text, case_sensitive=self.case_check.isChecked()
        )
        if count == 0:
            self.preview_label.setText("No selected items contain that text \u2014 nothing would change.")
        else:
            self.preview_label.setText(f"\u2713 {count} of {len(self.item_ids)} selected item(s) will be updated.")
        self.apply_btn.setEnabled(count > 0)

    def _apply(self):
        if not auth.can_edit_items(self.db, self.item_ids):
            return
        field = self.field_combo.currentData()
        find_text = self.find_edit.text()
        replace_text = self.replace_edit.text()
        if not find_text:
            return
        updated = self.db.bulk_find_replace(
            self.item_ids, field, find_text, replace_text,
            case_sensitive=self.case_check.isChecked()
        )
        QMessageBox.information(self, "Done", f"Updated {updated} item(s).")
        self.accept()
