"""Compact, read-only project/group summary for the project browser."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QFrame, QLabel, QPushButton, QProgressBar)
from i18n import tr, tr_text
from ui.widgets import ActionCard


class ProjectOverview(QWidget):
    open_requested = Signal()
    metric_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("projectOverview")
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(18)
        self.context = QLabel()
        self.context.setObjectName("breadcrumb")
        self.context.setWordWrap(True)
        self.context.setTextFormat(Qt.PlainText)
        layout.addWidget(self.context)
        heading = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.PlainText)
        heading.addWidget(self.title, 1)
        self.open_btn = QPushButton(tr("open_project"))
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.clicked.connect(self.open_requested)
        heading.addWidget(self.open_btn, 0, Qt.AlignTop)
        layout.addLayout(heading)

        self.metadata = QLabel()
        self.metadata.setTextFormat(Qt.PlainText)
        self.metadata.setWordWrap(True)
        self.metadata.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.metadata)

        metrics = QGridLayout()
        metrics.setSpacing(12)
        self.metrics = {}
        self.metric_cards = {}
        for index, (key, caption) in enumerate((
            ("items", "Items"), ("delivered", "Delivered"),
            ("pending", "Not requested"), ("blocked", "On Hold"),
        )):
            card = ActionCard()
            card.setObjectName("statCard")
            card.setAccessibleName(tr_text(caption))
            card.setToolTip(tr_text("View matching items"))
            card.clicked.connect(lambda key=key: self.metric_requested.emit(key))
            self.metric_cards[key] = card
            box = QVBoxLayout(card)
            value = QLabel("0")
            value.setObjectName("statValue")
            label = QLabel(tr_text(caption))
            label.setWordWrap(True)
            label.setObjectName("breadcrumb")
            box.addWidget(value)
            box.addWidget(label)
            metrics.addWidget(card, index // 2, index % 2)
            metrics.setColumnStretch(index % 2, 1)
            self.metrics[key] = value
        layout.addLayout(metrics)

        progress_card = QFrame()
        progress_card.setObjectName("detailPanel")
        progress_layout = QVBoxLayout(progress_card)
        progress_layout.setContentsMargins(16, 12, 16, 12)
        self.delivery_label = QLabel()
        self.delivery_label.setWordWrap(True)
        progress_layout.addWidget(self.delivery_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        progress_layout.addWidget(self.progress)
        self.statuses = QLabel()
        self.statuses.setWordWrap(True)
        self.statuses.setObjectName("breadcrumb")
        progress_layout.addWidget(self.statuses)
        layout.addWidget(progress_card)

        self.value = QLabel()
        self.value.setWordWrap(True)
        self.value.setTextFormat(Qt.PlainText)
        self.value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.value)
        self.notes = QLabel()
        self.notes.setTextFormat(Qt.PlainText)
        self.notes.setWordWrap(True)
        layout.addWidget(self.notes)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("breadcrumb")
        layout.addWidget(self.hint)
        layout.addStretch()

    def show_summary(self, title, context, summary, project=None, group=None):
        self.title.setText(title)
        self.context.setText(context)
        self.open_btn.setVisible(project is not None)
        entity = project or group
        fields = []
        if entity:
            for key, caption in (("project_number", "Project Number"), ("location", "Location"),
                                 ("contractor", "Contractor"), ("currency", "Currency")):
                if key in entity.keys() and entity[key]:
                    fields.append(f"{tr_text(caption)}: \u2068{entity[key]}\u2069")
        self.metadata.setText("    ·    ".join(fields))
        self.metadata.setVisible(bool(fields))
        counts = summary["status_counts"]
        total = summary["item_count"]
        delivered = counts.get("Delivered", 0)
        for key, count in (("items", total), ("delivered", delivered),
                           ("pending", counts.get("Not requested", 0)), ("blocked", counts.get("On Hold", 0))):
            self.metrics[key].setText(f"{count:,}")
        self.progress.setValue(round(delivered * 100 / total) if total else 0)
        self.delivery_label.setText(tr_text("Fully delivered items: {done} of {total}").format(done=delivered, total=total))
        self.statuses.setText("    ·    ".join(f"{tr_text(status)}: {count}" for status, count in counts.items()
                                             if status not in ("Delivered", "Not requested", "On Hold")))
        self.statuses.setVisible(bool(self.statuses.text()))
        amounts = "    ·    ".join(f"\u2066{value:,.2f} {currency}\u2069" for currency, value in sorted(summary["value_by_currency"].items()))
        self.value.setText(tr_text("Purchasing value") + ":  " + (amounts or "—"))
        notes = entity["notes"] if entity and "notes" in entity.keys() else ""
        self.notes.setText(tr_text("Notes") + ": " + notes if notes else "")
        self.notes.setVisible(bool(notes))
        if not total:
            self.hint.setText(tr_text("No items in this scope yet."))
        elif not project:
            self.hint.setText(tr_text("Select a project in the tree to view its details and open its BOQ."))
        else:
            self.hint.setText("")
