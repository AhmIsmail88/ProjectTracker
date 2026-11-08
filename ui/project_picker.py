from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox
from i18n import tr_text


class ProjectPicker(QComboBox):
    project_requested = Signal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setMinimumWidth(210)
        self.setMaximumWidth(420)
        self.setAccessibleName(tr_text("Current Project"))
        self.activated.connect(self._activated)
        self.set_project(None)

    def set_project(self, project_id):
        self.blockSignals(True)
        self.clear()
        self.addItem(tr_text("Choose a project…"), None)
        projects = list(self.db.get_projects())
        groups = list(self.db.get_project_groups())
        for group_id, label in [(g["id"], g["name"]) for g in groups] + [(None, tr_text("Ungrouped"))]:
            members = [p for p in projects if p["group_id"] == group_id]
            if not members:
                continue
            self.addItem(label, None)
            self.model().item(self.count() - 1).setEnabled(False)
            for project in members:
                number = f" · {project['project_number']}" if project["project_number"] else ""
                self.addItem(f"    {project['name']}{number}", project["id"])
        self.setCurrentIndex(max(0, self.findData(project_id)))
        self.model().item(0).setEnabled(project_id is None)
        self.blockSignals(False)

    def _activated(self, _index):
        project_id = self.currentData()
        if project_id is not None:
            self.project_requested.emit(project_id)
