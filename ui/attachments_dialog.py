import os
import auth
from collections import Counter
from PySide6.QtCore import Qt, QUrl, QTimer, QEvent
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QSplitter,
                               QStackedWidget, QFileDialog, QMessageBox, QWidget, QSizePolicy)
from constants import ATTACHMENT_CATEGORIES, POST_DELIVERY_CATEGORIES_SET, get_theme
from ui.widgets import UndoBar
from ui.icons import make_icon
from ui.styles import DARK_TOKENS, LIGHT_TOKENS
from i18n import tr_text

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    PDF_PREVIEW_AVAILABLE = True
except ImportError:
    PDF_PREVIEW_AVAILABLE = False


class _CompactTitle(QLabel):
    """Keep long item/file names on one line without widening the dialog."""
    def __init__(self, text=""):
        super().__init__()
        self._full_text = ""
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setText(text)

    def setText(self, text):
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(
            self._full_text.replace("\n", " "), Qt.ElideRight, max(0, self.contentsRect().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class AttachmentsDialog(QDialog):
    def __init__(self, parent, db, item_id, item_name, read_only=False):
        super().__init__(parent)
        self.db, self.item_id = db, item_id
        self.read_only = read_only
        self._current_pixmap = None
        self.setWindowTitle(tr_text("Documents & Attachments") + " · " + item_name)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(760, 520)
        self.resize(1060, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        self.item_title = _CompactTitle(item_name)
        self.item_title.setObjectName("detailTitle")
        self.item_title.setAccessibleName(item_name)
        layout.addWidget(self.item_title)
        self.summary_label = QLabel()
        self.summary_label.setObjectName("breadcrumb")
        self.summary_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.summary_label)
        toolbar = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.setAccessibleName(tr_text("All Documents"))
        self.filter_combo.setMinimumWidth(160)
        self.filter_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.filter_combo.addItem(tr_text("All Documents"), None)
        for category in ATTACHMENT_CATEGORIES:
            self.filter_combo.addItem(tr_text(category), category)
        self.filter_combo.currentIndexChanged.connect(self._reload_list)
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch()
        toolbar.addWidget(QLabel(tr_text("Upload as:")))
        self.category_combo = QComboBox()
        self.category_combo.setAccessibleName(tr_text("Upload as:"))
        self.category_combo.setMinimumWidth(150)
        self.category_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for category in ATTACHMENT_CATEGORIES:
            self.category_combo.addItem(tr_text(category), category)
        toolbar.addWidget(self.category_combo)
        upload = QPushButton(tr_text("Upload Files…"))
        upload.setObjectName("primaryButton")
        tokens = DARK_TOKENS if get_theme() == "dark" else LIGHT_TOKENS
        upload.setIcon(make_icon("upload", tokens["on_accent"]))
        upload.clicked.connect(self._upload_file)
        toolbar.addWidget(upload)
        self.upload_btn = upload
        layout.addLayout(toolbar)
        self.list_widget = QTreeWidget()
        self.list_widget.setHeaderLabels([tr_text("File Name"), tr_text("Uploaded")])
        self.list_widget.setMinimumWidth(260)
        self.list_widget.setUniformRowHeights(True)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setAccessibleName(tr_text("All Documents"))
        self.list_widget.setColumnWidth(0, 240)
        self.list_widget.setColumnWidth(1, 110)
        self.list_widget.currentItemChanged.connect(self._selection_changed)
        self.list_widget.itemDoubleClicked.connect(lambda *_: self._open_selected())
        self.preview_title = _CompactTitle(tr_text("Preview"))
        self.preview_title.setObjectName("detailTitle")
        self.preview_meta = QLabel()
        self.preview_meta.setObjectName("breadcrumb")
        self.preview_meta.setWordWrap(True)
        self.preview_meta.setTextFormat(Qt.PlainText)
        self.preview_meta.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.preview_label = QLabel(tr_text("Select a file to preview."))
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setWordWrap(True)
        self.preview_label.setMinimumHeight(160)
        self.preview_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview_label.setTextFormat(Qt.PlainText)
        self.preview_label.installEventFilter(self)
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview_label)
        self.pdf_document = self.pdf_view = None
        if PDF_PREVIEW_AVAILABLE:
            self.pdf_document = QPdfDocument(self)
            self.pdf_view = QPdfView()
            self.pdf_view.setDocument(self.pdf_document)
            self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.preview_stack.addWidget(self.pdf_view)
        preview = QWidget()
        preview.setObjectName("detailPanel")
        preview.setMinimumWidth(320)
        preview_layout = QVBoxLayout(preview)
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_meta)
        preview_layout.addWidget(self.preview_stack, 1)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self.list_widget)
        self.splitter.addWidget(preview)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([350, 670])
        layout.addWidget(self.splitter, 1)
        self.undo_bar = UndoBar(self)
        layout.addWidget(self.undo_bar)
        actions = QHBoxLayout()
        self.open_btn = QPushButton(tr_text("Open"))
        self.open_btn.setIcon(make_icon("folder", tokens["text2"]))
        self.open_btn.clicked.connect(self._open_selected)
        self.delete_btn = QPushButton(tr_text("Delete"))
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.setIcon(make_icon("trash", tokens["danger"]))
        self.delete_btn.clicked.connect(self._delete_selected)
        if read_only:
            self.upload_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.category_combo.setEnabled(False)
            self.upload_btn.setToolTip(tr_text("View only"))
            self.delete_btn.setToolTip(tr_text("View only"))
        actions.addWidget(self.open_btn)
        actions.addWidget(self.delete_btn)
        actions.addStretch()
        close = QPushButton(tr_text("Close"))
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        layout.addLayout(actions)
        self._reload_list()

    def _reload_list(self, *_args, selected_id=None):
        current = self._selected_attachment()
        selected_id = selected_id or (current["id"] if current else None)
        files = self.db.get_attachments(self.item_id)
        counts = Counter(file["category"] for file in files)
        # Old/imported databases can contain categories outside today's list.
        # Keep every stored document visible and filterable.
        categories = list(ATTACHMENT_CATEGORIES)
        categories.extend(category for category in counts if category not in categories)
        for category in categories:
            for combo in (self.filter_combo, self.category_combo):
                if combo.findData(category) < 0:
                    combo.blockSignals(True)
                    combo.addItem(tr_text(category or "Other"), category)
                    combo.blockSignals(False)
        procurement = [category for category in ("PR", "PO") if counts[category]]
        self.summary_label.setText(tr_text("{count} files · Procurement: {documents}").format(
            count=len(files), documents=", ".join(procurement) or tr_text("Missing")))
        self.list_widget.clear()
        filter_category = self.filter_combo.currentData()
        if filter_category is not None:
            self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(filter_category)))
        tokens = DARK_TOKENS if get_theme() == "dark" else LIGHT_TOKENS
        for category in categories:
            members = [file for file in files if file["category"] == category]
            if not members or filter_category is not None and category != filter_category:
                continue
            group = QTreeWidgetItem([f"{tr_text(category or 'Other')} ({len(members)})"])
            group.setData(0, Qt.UserRole + 1, category)
            group.setIcon(0, make_icon("folder", tokens["accent"]))
            self.list_widget.addTopLevelItem(group)
            group.setExpanded(True)
            for file in members:
                item = QTreeWidgetItem([file["original_name"], (file["uploaded_date"] or "")[:10]])
                item.setData(0, Qt.UserRole, file)
                item.setToolTip(0, file["original_name"])
                item.setIcon(0, make_icon("file", tokens["text2"]))
                group.addChild(item)
                if file["id"] == selected_id:
                    self.list_widget.setCurrentItem(item)
        self._selection_changed()
        if not files:
            self._show_preview_message(tr_text("No attachments yet. Choose a category and upload files."))

    def _selected_attachment(self):
        current = self.list_widget.currentItem()
        return current.data(0, Qt.UserRole) if current else None

    def _selection_changed(self, *_):
        file = self._selected_attachment()
        self.open_btn.setEnabled(bool(file))
        self.delete_btn.setEnabled(bool(file) and not self.read_only)
        self.preview_title.setText(file["original_name"] if file else tr_text("Preview"))
        self.preview_meta.setText("")
        if file:
            self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(file["category"])))
            path = file["file_path"]
            size = f"{os.path.getsize(path) / 1024:,.1f} KB" if path and os.path.isfile(path) else tr_text("File missing")
            self.preview_meta.setText(f"{tr_text(file['category'])} · {file['uploaded_date'] or ''} · {size}")
        else:
            current = self.list_widget.currentItem()
            category = current.data(0, Qt.UserRole + 1) if current else None
            if category:
                self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(category)))
        self._update_preview()

    def _show_preview_message(self, text):
        self._current_pixmap = None
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText(text)
        self.preview_stack.setCurrentIndex(0)

    def _scaled_preview(self):
        return self._current_pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)

    def _update_preview(self):
        file = self._selected_attachment()
        if not file:
            self._show_preview_message(tr_text("Select a file to preview."))
            return
        path = file["file_path"]
        if not path or not os.path.isfile(path):
            self._show_preview_message(tr_text("The attachment is missing from this data folder."))
            return
        extension = os.path.splitext(path)[1].lower()
        if extension in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self._current_pixmap = pixmap
                self.preview_label.setText("")
                self.preview_label.setPixmap(self._scaled_preview())
                self.preview_stack.setCurrentIndex(0)
                QTimer.singleShot(0, self._refresh_image)
                return
        if extension == ".pdf" and PDF_PREVIEW_AVAILABLE:
            self.pdf_document.load(path)
            if self.pdf_document.status() == QPdfDocument.Status.Ready:
                self._current_pixmap = None
                self.preview_stack.setCurrentIndex(1)
                return
        self._show_preview_message(tr_text("Preview unavailable. Use Open to view this file."))

    def _refresh_image(self):
        if self._current_pixmap is not None:
            self.preview_label.setPixmap(self._scaled_preview())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_image()

    def eventFilter(self, watched, event):
        if watched is self.preview_label and event.type() == QEvent.Resize:
            self._refresh_image()
        return super().eventFilter(watched, event)

    def _upload_file(self):
        if self.read_only or not auth.can_edit_items(self.db, [self.item_id]):
            return
        paths, _ = QFileDialog.getOpenFileNames(self, tr_text("Upload Files…"))
        if not paths:
            return
        category = self.category_combo.currentData()
        if category in POST_DELIVERY_CATEGORIES_SET:
            item = self.db.get_item(self.item_id)
            if item and item["status"] != "Delivered":
                answer = QMessageBox.question(self, tr_text("Delivery Documents"), tr_text("This item is not fully delivered. Upload these documents anyway?"))
                if answer != QMessageBox.Yes:
                    return
        try:
            for path in paths:
                if not auth.can_edit_items(self.db, [self.item_id]):
                    return
                self.db.add_attachment(self.item_id, category, path)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, tr_text("Upload failed"), str(exc))
        self.filter_combo.setCurrentIndex(0)
        self._reload_list()

    def _open_selected(self):
        file = self._selected_attachment()
        if file:
            path = file["file_path"]
            if not path or not os.path.isfile(path):
                QMessageBox.information(self, tr_text("File missing"), tr_text("The attachment is missing from this data folder."))
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _delete_selected(self):
        if self.read_only or not auth.can_edit_items(self.db, [self.item_id]):
            return
        file = self._selected_attachment()
        if not file:
            return
        self.db.delete_attachment(file["id"])
        self._reload_list()
        def undo():
            if not auth.can_edit_items(self.db, [self.item_id]):
                return
            self.db.restore_attachment(file["id"])
            self._reload_list(selected_id=file["id"])
        self.undo_bar.show_message(tr_text("Attachment removed. You can undo this."), undo)
