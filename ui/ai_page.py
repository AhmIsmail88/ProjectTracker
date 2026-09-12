"""
ui/ai_page.py
Standalone "AI Assistant" screen. Lets the user ask natural-language
questions about their projects/items; a compact JSON snapshot of the
current data PLUS a summary of recent changes (from the audit log) is
sent as context to OpenRouter, so the model can answer both "what's
pending?" and "what changed recently?" questions.

Conversations are persisted locally per "scope" (a specific project, or
the "All projects" scope) in the ai_chat_history table, so they survive
closing and reopening the app. Only a bounded, recent slice of the audit
log is ever sent per request — not the whole history — to keep requests
fast and within the model's context limits.

Network calls run in a QThread so the UI never freezes.
"""

import html
import json
import re
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QFileDialog, QMessageBox
)
from PySide6.QtCore import QThread, Signal, QTimer

from ai import openrouter_client
from i18n import tr

# Prompt used by the "Quick Report" button. Deliberately asks for plain
# text (no markdown/asterisks/tables) since the output is meant to be
# saved and read as a plain .txt file.
_REPORT_PROMPT = (
    "Write a concise plain-text status report from the data above (no markdown, "
    "no asterisks, no tables — just clear headings and short lines, suitable for "
    "a .txt file). Include: overall totals, items by status, anything overdue or "
    "over-supplied, and a short list of what still needs action. "
    "Respond in the same language as the rest of this conversation, or Arabic if unsure."
)

# How many recent audit-log entries to include as context per request.
# Kept small on purpose — this isn't meant to replace the visual Activity
# tab, just to give the AI enough to answer "what changed lately?".
_ACTIVITY_CONTEXT_LIMIT = 40
# How many turns of prior conversation to resend as context each request.
_HISTORY_CONTEXT_TURNS = 12


def _is_mostly_arabic(text):
    """True when a message carries more Arabic letters than Latin ones -
    used to pick the per-message reading direction in the chat log."""
    s = str(text or "")
    arabic = sum(1 for ch in s if "\u0600" <= ch <= "\u06FF")
    latin = sum(1 for ch in s if ch.isascii() and ch.isalpha())
    return arabic > latin


def _format_chat_html(text):
    """Escapes chat text, then applies a tiny, SAFE markdown-ish pass so
    AI replies stop showing raw markup:
      **bold** -> bold, `code` -> code,
      markdown table rows -> readable "a - b - c" lines (separators dropped).
    Escaping happens FIRST, so this can never inject live HTML from data."""
    safe = html.escape(str(text or ""))
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"`(.+?)`", r"<code>\1</code>", safe)
    rendered = []
    for line in safe.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if cells and all(re.fullmatch(r"[-: ]*", c) for c in cells):
                continue  # markdown table separator row -> drop
            rendered.append(" \u2014 ".join(c for c in cells if c))
        else:
            rendered.append(line)
    return "<br>".join(rendered)


def _build_context_snapshot(db, project_ids=None):
    """A compact, token-cheap JSON summary of the current tracker data.
    project_ids: None = every project; otherwise only those ids (a
    single project, or every project in a selected group)."""
    projects = db.get_projects()
    snapshot = []
    for p in projects:
        if project_ids is not None and p["id"] not in project_ids:
            continue
        items = db.get_items(p["id"])
        snapshot.append({
            "project": p["name"],
            "currency": p["currency"],
            "items": [
                {
                    "name": it["item_name"],
                    "supplier": it["supplier_name"],
                    "unit": it["unit"],
                    "total_qty": it["total_quantity"],
                    "requested_qty": it["requested_quantity"],
                    "delivered_qty": it["delivered_quantity"],
                    "status": it["status"],
                }
                for it in items
            ],
        })
    return snapshot


def _format_activity_for_ai(rows):
    """Plain-text summary of recent audit_log rows for the system prompt."""
    lines = []
    for r in rows:
        name = r["entity_name"] or f"#{r['entity_id']}"
        if r["action"] == "updated" and r["field"]:
            lines.append(
                f"{r['changed_at']}: {r['entity_type']} '{name}' - {r['field']} "
                f"changed from {r['old_value']} to {r['new_value']}"
            )
        else:
            lines.append(f"{r['changed_at']}: {r['entity_type']} '{name}' was {r['action']}")
    return "\n".join(lines) if lines else "No recorded changes yet."


class _ChatWorker(QThread):
    finished_ok = Signal(str)
    finished_err = Signal(str)

    def __init__(self, messages):
        super().__init__()
        self.messages = messages

    def run(self):
        try:
            reply = openrouter_client.chat(self.messages)
            self.finished_ok.emit(reply)
        except Exception as exc:  # noqa: broad-except — surfaced to the UI
            self.finished_err.emit(str(exc))


class _TestConnWorker(QThread):
    finished = Signal(dict)

    def run(self):
        self.finished.emit(openrouter_client.test_connection())


class AIPage(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self._history = []  # [{"role": "user"|"assistant", "content": str}, ...] for the current scope
        self._worker = None
        self._last_reply_text = None
        self._last_reply_project_name = None
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(450)
        self._thinking_timer.timeout.connect(self._tick_thinking)
        self._thinking_dots = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        title_row = QHBoxLayout()
        title = QLabel(tr("ai_assistant"))
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        test_conn_btn = QPushButton("\U0001F50C Test AI Connection")
        test_conn_btn.setToolTip("Send one quick test message to verify OPENROUTER_MODEL works before relying on it")
        test_conn_btn.clicked.connect(self._test_connection)
        title_row.addWidget(test_conn_btn)
        new_conv_btn = QPushButton(tr("new_conversation"))
        new_conv_btn.clicked.connect(self._new_conversation)
        title_row.addWidget(new_conv_btn)
        layout.addLayout(title_row)

        if not openrouter_client.is_configured():
            warn = QLabel(
                "OpenRouter is not configured yet. Create a .env file next to main.py "
                "(copy .env.example) and set OPENROUTER_API_KEY. This uses OpenRouter's "
                "free-tier models, so it stays free for personal use."
            )
            warn.setWordWrap(True)
            layout.addWidget(warn)

        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Scope:"))
        self.scope_combo = QComboBox()
        self._populate_scope_combo()
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        self.scope_combo.setMaximumWidth(460)
        scope_row.addWidget(self.scope_combo, 1)
        layout.addLayout(scope_row)

        memory_hint = QLabel(
            "Conversations are saved locally per scope (a project, a Main Project group, or "
            "\u201cAll projects\u201d) and reloaded automatically — the assistant also sees a short "
            "summary of recent changes for this scope."
        )
        memory_hint.setObjectName("breadcrumb")
        memory_hint.setWordWrap(True)
        layout.addWidget(memory_hint)

        self.chat_log = QTextEdit()
        self.chat_log.setReadOnly(True)
        layout.addWidget(self.chat_log, 1)

        self.thinking_label = QLabel("")
        self.thinking_label.setObjectName("breadcrumb")
        self.thinking_label.setVisible(False)
        layout.addWidget(self.thinking_label)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Ask about your projects, e.g. 'what's still pending on Site A?'")
        self.input_edit.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input_edit, 1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        # ---- Report tools ----
        report_row = QHBoxLayout()
        self.report_btn = QPushButton("\U0001F4C4 " + tr("quick_report"))
        self.report_btn.setToolTip("Ask the AI for a short plain-text status report for the selected scope")
        self.report_btn.clicked.connect(self._generate_report)
        self.save_txt_btn = QPushButton("\U0001F4BE " + tr("save_as_txt"))
        self.save_txt_btn.setToolTip("Save the last AI reply above as a .txt file")
        self.save_txt_btn.clicked.connect(self._save_last_reply)
        self.save_txt_btn.setEnabled(False)
        report_row.addWidget(self.report_btn)
        report_row.addWidget(self.save_txt_btn)
        report_row.addStretch()
        layout.addLayout(report_row)

        if not openrouter_client.is_configured():
            self.report_btn.setEnabled(False)

        # Load whatever was already saved for the initial scope (All projects).
        self._load_scope_history(*self._scope_db_ids())

    # ------------------------------------------------------------------ #
    # Scope handling / persisted memory
    # ------------------------------------------------------------------ #
    def _populate_scope_combo(self):
        self.scope_combo.addItem("All projects", ("all", None))
        for g in self.db.get_project_groups():
            self.scope_combo.addItem(f"\U0001F4C1 {g['name']} (Group)", ("group", g["id"]))
        for p in self.db.get_projects():
            self.scope_combo.addItem(p["name"], ("project", p["id"]))

    def refresh_projects(self):
        """Called every time the sidebar navigates to this page, so newly
        added/renamed projects and groups show up in the scope dropdown."""
        current = self.scope_combo.currentData()
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        self._populate_scope_combo()
        idx = self.scope_combo.findData(current)
        self.scope_combo.setCurrentIndex(max(idx, 0))
        self.scope_combo.blockSignals(False)

    def _scope_project_ids(self):
        """None = every project; otherwise a list of project ids this
        scope covers (a single project, or every project in the
        selected group)."""
        kind, ident = self.scope_combo.currentData()
        if kind == "project":
            return [ident]
        if kind == "group":
            return [p["id"] for p in self.db.get_projects_in_group(ident)]
        return None

    def _scope_db_ids(self):
        """(scope_project_id, scope_group_id) pair matching the chat
        history methods' signature — exactly one is set, or neither for
        the "All projects" scope."""
        kind, ident = self.scope_combo.currentData()
        if kind == "project":
            return ident, None
        if kind == "group":
            return None, ident
        return None, None

    def _activity_for_scope(self, project_ids, limit):
        if project_ids is None:
            return self.db.get_activity(limit=limit)
        if len(project_ids) == 1:
            return self.db.get_activity(project_id=project_ids[0], limit=limit)
        rows = []
        for pid in project_ids:
            rows.extend(self.db.get_activity(project_id=pid, limit=limit))
        rows.sort(key=lambda r: (r["changed_at"], r["id"]), reverse=True)
        return rows[:limit]

    def _on_scope_changed(self, _index):
        self._load_scope_history(*self._scope_db_ids())

    def _load_scope_history(self, scope_project_id, scope_group_id=None):
        """Rebuild the chat log + in-memory context from what's saved on
        disk for this scope."""
        self.chat_log.clear()
        self._history = []
        for m in self.db.get_chat_history(scope_project_id, scope_group_id=scope_group_id):
            who = "You" if m["role"] == "user" else "AI"
            self._append(who, m["content"], persist=False)
            self._history.append({"role": m["role"], "content": m["content"]})
        self._last_reply_text = None
        self.save_txt_btn.setEnabled(False)

    def _new_conversation(self):
        scope_project_id, scope_group_id = self._scope_db_ids()
        confirm = QMessageBox.question(
            self, tr("new_conversation"),
            "This clears the saved conversation for the current scope. Continue?"
        )
        if confirm != QMessageBox.Yes:
            return
        self.db.clear_chat_history(scope_project_id, scope_group_id=scope_group_id)
        self._load_scope_history(scope_project_id, scope_group_id)

    # ------------------------------------------------------------------ #
    def _append(self, who, text, persist=True, role=None):
        # Chat text is data, not markup: escape it, apply the tiny
        # markdown-ish polish, and let each message pick its own reading
        # direction (Arabic messages read right-to-left) so mixed
        # Arabic/English replies stop looking scrambled.
        body = _format_chat_html(text)
        direction = "rtl" if _is_mostly_arabic(text) else "ltr"
        align = "right" if direction == "rtl" else "left"
        self.chat_log.append(
            f'<div dir="{direction}" style="text-align:{align};"><b>{who}:</b> {body}</div>'
        )
        if persist and role is not None:
            scope_project_id, scope_group_id = self._scope_db_ids()
            self.db.save_chat_message(scope_project_id, role, text, scope_group_id=scope_group_id)

    def _start_thinking(self):
        self._thinking_dots = 0
        self.thinking_label.setVisible(True)
        self.thinking_label.setText("\U0001F914 AI is thinking...")
        self.input_edit.setEnabled(False)
        self._thinking_timer.start()

    def _stop_thinking(self):
        self._thinking_timer.stop()
        self.thinking_label.setVisible(False)
        self.input_edit.setEnabled(True)

    def _tick_thinking(self):
        self._thinking_dots = (self._thinking_dots + 1) % 4
        self.thinking_label.setText("\U0001F914 AI is thinking" + "." * self._thinking_dots)

    def _send(self):
        question = self.input_edit.text().strip()
        if not question:
            return
        self.input_edit.clear()
        self._ask(question, shown_as="You")

    def _generate_report(self):
        """Ask the AI for a short plain-text status report, then offer to
        save it as a .txt file as soon as it arrives."""
        scope_name = self.scope_combo.currentText()
        self._append("You", f"[{tr('quick_report')}] {scope_name}", persist=True, role="user")
        self._ask(_REPORT_PROMPT, shown_as=None, is_report=True, already_shown=True)

    def _ask(self, question, shown_as="You", is_report=False, already_shown=False):
        if not openrouter_client.is_configured():
            self._append("System", "AI is not configured. Add OPENROUTER_API_KEY to your .env file.", persist=False)
            return

        if shown_as and not already_shown:
            self._append(shown_as, question, persist=True, role="user")
        self.send_btn.setEnabled(False)
        self.report_btn.setEnabled(False)

        project_ids = self._scope_project_ids()
        self._last_reply_project_name = self.scope_combo.currentText()

        snapshot = _build_context_snapshot(self.db, project_ids)
        activity_rows = self._activity_for_scope(project_ids, limit=_ACTIVITY_CONTEXT_LIMIT)
        activity_text = _format_activity_for_ai(activity_rows)

        system_prompt = (
            "You are a helpful assistant for a construction materials/procurement tracker. "
            "Answer using ONLY the data provided below; if something isn't in the data, say so. "
            "Be concise and use the same language the user asks in (Arabic or English).\n\n"
            f"CURRENT DATA:\n{json.dumps(snapshot, ensure_ascii=False)}\n\n"
            f"RECENT ACTIVITY (most recent first, may be partial):\n{activity_text}"
        )
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._history[-_HISTORY_CONTEXT_TURNS:])
        messages.append({"role": "user", "content": question})

        self._history.append({"role": "user", "content": question})

        self._start_thinking()
        self._worker = _ChatWorker(messages)
        self._worker.finished_ok.connect(lambda text: self._on_reply(text, is_report))
        self._worker.finished_err.connect(self._on_error)
        self._worker.start()

    def _on_reply(self, text, is_report=False):
        self._stop_thinking()
        self._append("AI", text, persist=True, role="assistant")
        self._history.append({"role": "assistant", "content": text})
        self._last_reply_text = text
        self.send_btn.setEnabled(True)
        self.report_btn.setEnabled(openrouter_client.is_configured())
        self.save_txt_btn.setEnabled(True)
        if is_report:
            self._save_last_reply()

    def _on_error(self, err):
        self._stop_thinking()
        self._append("System", f"Error: {err}", persist=False)
        self.send_btn.setEnabled(True)
        self.report_btn.setEnabled(openrouter_client.is_configured())

    def _test_connection(self):
        if not openrouter_client.is_configured():
            QMessageBox.information(
                self, "Not configured",
                "OPENROUTER_API_KEY is not set — add it to your .env file first (see .env.example)."
            )
            return
        self._append("System", f"Testing connection to model: {openrouter_client.get_model()}\u2026", persist=False)
        self._start_thinking()
        self._test_worker = _TestConnWorker()
        self._test_worker.finished.connect(self._on_test_connection_result)
        self._test_worker.start()

    def _on_test_connection_result(self, result):
        self._stop_thinking()
        env_note = (
            f"(.env found at: {result['env_path']})" if result["env_exists"]
            else f"\u26A0 (.env NOT found at: {result['env_path']} \u2014 this is almost always the real "
                 f"problem if the model looks wrong: check the file really exists there with exactly "
                 f"that name, e.g. via 'dir .env*' in Command Prompt \u2014 Windows sometimes silently "
                 f"saves it as '.env.txt')"
        )
        if result["ok"]:
            self._append(
                "System",
                f"\u2705 Connected OK ({result['seconds']:.1f}s, model: {result['model']}). "
                f"Reply: \u201c{result['reply']}\u201d\n{env_note}",
                persist=False,
            )
        else:
            self._append(
                "System",
                f"\u274C Connection failed (model: {result['model']}): {result['error']}\n{env_note}",
                persist=False,
            )

    def _save_last_reply(self):
        if not self._last_reply_text:
            QMessageBox.information(self, tr("save_as_txt"), "No AI reply to save yet.")
            return
        safe_scope = re.sub(r"[^\w\- ]+", "", self._last_reply_project_name or "report").strip() or "report"
        default_name = f"{safe_scope} - {datetime.now().strftime('%Y-%m-%d %H%M')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, tr("save_as_txt"), default_name, "Text Files (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._last_reply_text)
            QMessageBox.information(self, "Saved", f"Report saved:\n{path}")
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
