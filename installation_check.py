"""Optional, data-free diagnostic for a redistributed executable."""
import json
from pathlib import Path
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontInfo
from PySide6.QtCore import qVersion
from PySide6.QtPdf import QPdfDocument
from ui.fonts import install_cairo
from ai import openrouter_client
from constants import APP_VERSION


def run_ui_smoke(app, output_dir):
    """Exercise the packaged UI against disposable accounts and project data."""
    import tempfile
    from PySide6.QtCore import QSettings, Qt, QCoreApplication, QEvent
    from PySide6.QtWidgets import QDialog
    from reportlab.pdfgen import canvas
    import auth
    import config
    import i18n
    from database import Database
    from main import MainWindow
    from ui.login_dialog import LoginDialog
    from ui.attachments_dialog import AttachmentsDialog

    previous_config = config.CONFIG_PATH
    previous_format = QSettings.defaultFormat()
    checks = {}
    window = attachments = login = None
    with tempfile.TemporaryDirectory(prefix="installation-check-", dir=output_dir) as root:
        try:
            # Do not read or overwrite the user's real preferences or projects.
            config.CONFIG_PATH = str(Path(root) / "config.json")
            QSettings.setDefaultFormat(QSettings.IniFormat)
            for scope in (QSettings.UserScope, QSettings.SystemScope):
                QSettings.setPath(QSettings.IniFormat, scope, root)
            QSettings("ProjectTracker", "MainWindow").setValue("language", "en")
            i18n.set_language("en")
            app.setLayoutDirection(Qt.LeftToRight)
            db = Database(str(Path(root) / "check.db"), str(Path(root) / "attachments"))
            login = LoginDialog(db, first_run=True)
            login.username_edit.setText("installation-manager")
            login.password_edit.setText("temporary-check-password")
            login.confirm_edit.setText("temporary-check-password")
            login._on_accept()
            checks["first_manager_login"] = login.result() == QDialog.Accepted and auth.is_manager(db)
            manager = auth.current_user()
            engineer = db.add_user("installation-engineer", "temporary-check-password")
            project = db.add_project("Installation Check")
            other = db.add_project("View-only project")
            db.set_project_assignee(project, engineer)
            item = db.add_item(project, "Demo pump", total_quantity=2)
            db.add_schedule_activity(project, "Installation", start_date="2026-01-01",
                                     end_date="2026-03-31", progress=50)
            window = MainWindow(db, root)
            window.resize(1280, 820)
            window.show()
            window._open_project(project)
            app.processEvents()
            checks["manager_can_edit"] = window.tracker_page._can_edit()
            for theme in ("dark", "light"):
                window._apply_theme(theme)
                window._navigate(5, "schedule")
                app.processEvents()
                checks["schedule_header_" + theme] = window.schedule_page.timeline_header.isVisible()
                window.grab().save(str(Path(output_dir) / ("schedule-en-" + theme + ".png")))
            window._toggle_language()
            app.processEvents()
            checks["arabic_navigation"] = (i18n.get_language() == "ar"
                                           and window.stack.currentIndex() == 5)
            window.grab().save(str(Path(output_dir) / "schedule-ar.png"))
            pdf_path = Path(root) / "sample.pdf"
            pdf = canvas.Canvas(str(pdf_path))
            pdf.drawString(72, 720, "Project Tracker installation check")
            pdf.save()
            db.add_attachment(item, "PR", str(pdf_path))
            doc = QPdfDocument(app)
            checks["pdf_load"] = doc.load(str(pdf_path)) == QPdfDocument.Error.None_
            app.processEvents()
            checks["pdf_page"] = doc.pageCount() == 1
            doc.close()
            attachments = AttachmentsDialog(window, db, item, "Demo pump")
            attachments.resize(1000, 650)
            attachments.show()
            app.processEvents()
            checks["attachments_window"] = attachments.isVisible()
            attachments.grab().save(str(Path(output_dir) / "attachments.png"))
            attachments.close()
            auth.login(db.get_user(engineer), db)
            window._build_central_widget()
            window.tracker_page.open_project(project)
            checks["assigned_engineer_can_edit"] = window.tracker_page._can_edit()
            window.tracker_page.open_project(other)
            checks["unassigned_engineer_read_only"] = not window.tracker_page._can_edit()
            db.update_user(engineer, is_active=0)
            checks["disabled_account_blocked"] = not auth.can_edit_project(db, project)
            auth.login(manager, db)
            checks["ai_settings_available"] = window.ai_page.settings_btn.isEnabled()
        finally:
            for widget in (attachments, window, login):
                if widget is not None:
                    widget.close()
                    widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            auth.logout()
            config.CONFIG_PATH = previous_config
            QSettings.setDefaultFormat(previous_format)
    return checks


def run_check(output, test_ai=False, smoke_ui=False):
    app = QApplication.instance() or QApplication([])
    install_cairo(app)
    report = {"version": APP_VERSION, "standalone": bool(getattr(sys, "frozen", False)),
              "font": QFontInfo(app.font()).family(), "qt": qVersion(),
              "pdf_preview": QPdfDocument(app) is not None,
              "ai_configured": openrouter_client.is_configured()}
    if smoke_ui:
        try:
            report["ui_checks"] = run_ui_smoke(app, str(Path(output).resolve().parent))
        except Exception as exc:
            report["ui_checks"] = {"completed": False}
            report["ui_error"] = str(exc)
    if test_ai:
        result = openrouter_client.test_connection()
        report["ai_connection"] = {k: result[k] for k in ("ok", "model", "reply", "seconds", "error")}
    report["ok"] = (report["font"] == "Cairo" and report["pdf_preview"]
                    and (not smoke_ui or all(report["ui_checks"].values()))
                    and (not test_ai or report["ai_connection"]["ok"]))
    Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["ok"] else 1
