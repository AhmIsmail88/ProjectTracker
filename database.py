"""
database.py
Data layer for Project Tracker (SQLite).

Key additions in this version:
 - Soft delete + restore for projects / items / suppliers / attachments,
   so every delete action in the UI can be undone (see ui/widgets.py).
 - Automatic status calculation from quantities (constants.compute_status),
   plus an explicit "manual_hold" and "po_issued" flag.
 - Over-supply detection + a required variance note.
 - Per-item currency (defaults to the project's currency).
 - Explicit sort_order for items so drag/move-up/move-down keeps a clean
   1..N sequence instead of leaving gaps.
 - Audit log: every create/update/delete/restore on a project, item, or
   supplier is recorded (field, old value, new value, timestamp) so the
   app — and the AI assistant — can answer "what changed and when".
 - Persistent AI chat history, stored locally per "scope" (a single
   project, or the "all projects" scope), so conversations survive
   restarting the app.
"""

import logging
import re
import sqlite3
import os
import shutil
import threading
import uuid
import ntpath
from datetime import datetime, timedelta
from collections import defaultdict
from contextlib import contextmanager

from constants import (
    ATTACHMENT_CATEGORIES,
    ALLOWED_PROJECT_COLS, ALLOWED_SUPPLIER_COLS, ALLOWED_ITEM_COLS,
    ALLOWED_SCHEDULE_COLS,
    compute_status, is_over_supplied, is_over_requested,
)
from app_paths import get_app_dir
import auth

logger = logging.getLogger(__name__)

# Default paths — used only when no explicit path is passed to Database().
_APP_DIR = get_app_dir()
_DEFAULT_DB_PATH = os.path.join(_APP_DIR, "project_tracker.db")
_DEFAULT_ATTACHMENTS_DIR = os.path.join(_APP_DIR, "attachments")

# Fields we deliberately never write to the audit log because they are
# either purely mechanical (last_updated always changes) or would just add
# noise without helping anyone understand "what happened".
_AUDIT_EXCLUDED_FIELDS = frozenset({"last_updated"})

# Bump when a migration step is added to _migrate_schema. Stored in the
# database file (PRAGMA user_version).
SCHEMA_VERSION = 1

# How long a write waits for another user's write to finish (seconds).
LOCK_TIMEOUT_SECONDS = 30


def is_database_busy_error(exc):
    """True for SQLite's "database is locked / busy" errors - another user
    or computer kept the file busy longer than LOCK_TIMEOUT_SECONDS."""
    return isinstance(exc, sqlite3.OperationalError) and (
        "locked" in str(exc).lower() or "busy" in str(exc).lower())


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_update(allowed_cols, fields):
    """Filter *fields* to only contain keys in *allowed_cols*, build the
    SET clause fragments, and return (sql_fragment, values_list, safe_dict).

    Raises ValueError if no valid columns remain after filtering.
    """
    safe = {k: v for k, v in fields.items() if k in allowed_cols}
    if not safe:
        raise ValueError(
            f"No valid columns to update. "
            f"Received: {set(fields)}, allowed: {allowed_cols}"
        )
    cols_sql = ", ".join(f"{k} = ?" for k in safe)
    return cols_sql, list(safe.values()), safe


def _same_value(old, new):
    """True when writing *new* over *old* would not change anything real:
    NULL and "" count as equal, and so do 5 and 5.0 / True and 1."""
    if old in (None, "") and new in (None, ""):
        return True
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(float(old) - float(new)) < 1e-12
    return old == new


def _log_change(conn, entity_type, entity_id, entity_name, project_id,
                 action, field=None, old_value=None, new_value=None):
    """Insert one audit_log row on the given (already-open) connection, so
    it commits atomically together with the change that triggered it."""
    conn.execute(
        """INSERT INTO audit_log
           (entity_type, entity_id, entity_name, project_id, action, field,
            old_value, new_value, changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entity_type, entity_id, entity_name, project_id, action, field,
            None if old_value is None else str(old_value),
            None if new_value is None else str(new_value),
            now_str(),
        ),
    )


def _log_field_diffs(conn, entity_type, entity_id, entity_name, project_id, current_row, safe_fields):
    """Compare *safe_fields* (the columns actually being written) against
    *current_row* (the row before the update) and log one audit_log entry
    per field that actually changed value."""
    if current_row is None:
        return
    for field, new_val in safe_fields.items():
        if field in _AUDIT_EXCLUDED_FIELDS:
            continue
        try:
            old_val = current_row[field]
        except (IndexError, KeyError):
            continue
        if old_val != new_val:
            _log_change(conn, entity_type, entity_id, entity_name, project_id,
                        "updated", field=field, old_value=old_val, new_value=new_val)


class Database:
    """Thin wrapper around sqlite3 that exposes simple, explicit methods.

    Keeping the DB access behind this one class means that if the tool
    ever moves to a real client/server database (PostgreSQL, etc.), only
    this file needs to change - none of the UI code has to be rewritten.
    """

    def __init__(self, db_path=_DEFAULT_DB_PATH, attachments_dir=None):
        self.db_path = db_path
        self._tx = threading.local()
        self.attachments_dir = attachments_dir or _DEFAULT_ATTACHMENTS_DIR
        os.makedirs(self.attachments_dir, exist_ok=True)
        logger.info("Database opened: %s", self.db_path)
        self._init_schema()
        self._migrate_schema()
        self._migrate_attachment_paths()

    def _migrate_attachment_paths(self):
        """Make legacy attachment paths portable, including restored Windows DBs."""
        with self._connect() as conn:
            for row in conn.execute("SELECT id, item_id, file_path FROM attachments").fetchall():
                path = row["file_path"] or ""
                if ntpath.isabs(path):
                    parts = path.replace("\\", "/").split("/")
                    if len(parts) >= 2 and parts[-2] == f"item_{row['item_id']}" and parts[-1] not in ("", ".", ".."):
                        conn.execute("UPDATE attachments SET file_path = ? WHERE id = ?",
                                     (f"{parts[-2]}/{parts[-1]}", row["id"]))

    def resolve_attachment_path(self, stored_path):
        """Resolve only files inside this database's attachment root."""
        root = os.path.realpath(self.attachments_dir)
        if not stored_path or ntpath.isabs(stored_path):
            raise ValueError("Attachment path must be relative to the data folder")
        path = os.path.realpath(os.path.join(root, stored_path.replace("\\", "/")))
        if os.path.commonpath([root, path]) != root or path == root:
            raise ValueError("Attachment path escapes the data folder")
        return path

    def _resolved_attachments(self, rows):
        result = []
        for row in rows:
            attachment = dict(row)
            try:
                attachment["file_path"] = self.resolve_attachment_path(row["file_path"])
            except ValueError:
                logger.warning("Ignoring unsafe attachment path for id=%s", row["id"])
                attachment["file_path"] = ""
            result.append(attachment)
        return result

    def _open_connection(self):
        # Wait up to LOCK_TIMEOUT_SECONDS for another computer/user to finish
        # its write instead of failing at once with "database is locked"
        # (Python's default is 5 s). WAL mode is deliberately NOT used: it
        # is unsafe when the data folder is on a network/shared drive.
        conn = sqlite3.connect(self.db_path, timeout=LOCK_TIMEOUT_SECONDS)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connect(self):
        # Inside transaction() every call on this thread shares one
        # connection, so nothing is committed until the whole batch is done.
        shared = getattr(getattr(self, "_tx", None), "conn", None)
        if shared is not None:
            yield shared
            return
        conn = self._open_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """All-or-nothing block: every write made through this Database on
        the current thread inside the block commits together at the end, or
        is rolled back entirely if anything raises. Used for imports and
        bulk edits, so a failure half-way never leaves half the rows
        changed. Nesting is allowed (inner blocks join the outer one).
        The connection is per-thread, so a background import never shares
        a connection with the UI thread."""
        if getattr(self, "_tx", None) is None:
            self._tx = threading.local()
        if getattr(self._tx, "conn", None) is not None:
            yield
            return
        conn = self._open_connection()
        self._tx.conn = conn
        try:
            with conn:
                yield
        finally:
            self._tx.conn = None
            conn.close()

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    location TEXT,
                    contractor TEXT,
                    project_number TEXT,
                    currency TEXT DEFAULT 'SAR',
                    notes TEXT,
                    created_date TEXT
                );

                CREATE TABLE IF NOT EXISTS suppliers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    contact_person TEXT,
                    phone TEXT,
                    email TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    pump_station TEXT,
                    supplier_id INTEGER,
                    unit TEXT,
                    total_quantity REAL DEFAULT 0,
                    requested_quantity REAL DEFAULT 0,
                    delivered_quantity REAL DEFAULT 0,
                    unit_cost REAL DEFAULT 0,
                    remarks TEXT,
                    status TEXT DEFAULT 'Not requested',
                    last_updated TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    original_name TEXT,
                    uploaded_date TEXT,
                    FOREIGN KEY (item_id) REFERENCES items (id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    display_name TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_date TEXT
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    entity_id INTEGER NOT NULL,
                    entity_name TEXT,
                    project_id INTEGER,
                    action TEXT NOT NULL,
                    field TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_log(project_id);
                CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
                CREATE INDEX IF NOT EXISTS idx_audit_changed_at ON audit_log(changed_at);

                CREATE TABLE IF NOT EXISTS ai_chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_project_id INTEGER,
                    scope_group_id INTEGER,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_scope ON ai_chat_history(scope_project_id);

                CREATE TABLE IF NOT EXISTS schedule_activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    phase TEXT DEFAULT '',
                    start_date TEXT,
                    end_date TEXT,
                    progress INTEGER DEFAULT 0,
                    milestone INTEGER DEFAULT 0,
                    notes TEXT,
                    sort_order INTEGER DEFAULT 0,
                    is_deleted INTEGER DEFAULT 0,
                    deleted_at TEXT,
                    last_updated TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_schedule_project ON schedule_activities(project_id);

                CREATE TABLE IF NOT EXISTS project_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    location TEXT,
                    contractor TEXT,
                    currency TEXT DEFAULT 'SAR',
                    notes TEXT,
                    created_date TEXT,
                    is_deleted INTEGER DEFAULT 0,
                    deleted_at TEXT
                );
                """
            )

    def _migrate_schema(self):
        """Add any columns introduced after the initial release.
        Safe to run every startup: it only ADD COLUMNs that are missing."""
        migrations = {
            "projects": [
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("deleted_at", "TEXT"),
                ("project_group", "TEXT"),
                ("group_id", "INTEGER"),
                ("assigned_user_id", "INTEGER"),
            ],
            "suppliers": [
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("deleted_at", "TEXT"),
            ],
            "items": [
                ("sort_order", "INTEGER DEFAULT 0"),
                ("currency", "TEXT"),
                ("manual_hold", "INTEGER DEFAULT 0"),
                ("po_issued", "INTEGER DEFAULT 0"),
                ("variance_note", "TEXT"),
                ("deleted_with_project", "INTEGER"),
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("deleted_at", "TEXT"),
            ],
            "attachments": [
                ("is_deleted", "INTEGER DEFAULT 0"),
                ("deleted_at", "TEXT"),
            ],
            "ai_chat_history": [
                ("scope_group_id", "INTEGER"),
            ],
        }
        with self._connect() as conn:
            for table, cols in migrations.items():
                existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                for col_name, col_def in cols:
                    if col_name not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                        logger.info("Migrated schema: %s.%s added", table, col_name)

            # Only safe to create once the column above is guaranteed to
            # exist — on a database from before scope_group_id existed,
            # creating this index inside _init_schema (which only runs
            # CREATE TABLE IF NOT EXISTS, a no-op on an already-existing
            # older table) would fail with "no such column".
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_scope_group ON ai_chat_history(scope_group_id)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(lower(username))")

            # One-time backfill: turn the old free-text "project_group" tag
            # into a real project_groups row + group_id foreign key, so
            # projects already tagged (e.g. several "QUBA MOSQUE EXPANSION
            # PROJECT" sections) come out the other side properly grouped
            # with zero manual re-entry. Only touches rows that still have
            # a text tag but no group_id yet, so it's safe every startup.
            legacy_tags = conn.execute(
                "SELECT DISTINCT project_group FROM projects "
                "WHERE group_id IS NULL AND project_group IS NOT NULL AND project_group != ''"
            ).fetchall()
            for row in legacy_tags:
                name = row["project_group"]
                existing_group = conn.execute(
                    "SELECT id FROM project_groups WHERE name = ? AND is_deleted = 0", (name,)
                ).fetchone()
                if existing_group:
                    group_id = existing_group["id"]
                else:
                    cur = conn.execute(
                        "INSERT INTO project_groups (name, currency, created_date) VALUES (?, 'SAR', ?)",
                        (name, now_str()),
                    )
                    group_id = cur.lastrowid
                    logger.info("Migrated legacy project_group %r into project_groups id=%d", name, group_id)
                conn.execute(
                    "UPDATE projects SET group_id = ? WHERE project_group = ? AND group_id IS NULL",
                    (group_id, name),
                )

            # Backfill sort_order for pre-existing items (id order) so old
            # databases immediately get a sane, gap-free sequence.
            rows = conn.execute(
                "SELECT id, project_id FROM items WHERE sort_order IS NULL OR sort_order = 0 ORDER BY project_id, id"
            ).fetchall()
            per_project_counter = {}
            for r in rows:
                per_project_counter[r["project_id"]] = per_project_counter.get(r["project_id"], 0) + 1
                conn.execute(
                    "UPDATE items SET sort_order = ? WHERE id = ?",
                    (per_project_counter[r["project_id"]], r["id"]),
                )

            # Retroactively close any existing gaps left over from BEFORE
            # delete_item started compacting on every delete (see
            # delete_item/_compact_sort_order). This runs every startup and
            # is cheap/idempotent — on an already-clean database it's a
            # no-op UPDATE for every row, so it never leaves stale gaps
            # around no matter how they were introduced.
            project_ids = [r["project_id"] for r in conn.execute("SELECT DISTINCT project_id FROM items")]
            for pid in project_ids:
                self._compact_sort_order(conn, pid)

            # Record the schema generation inside the file itself, so a
            # future migration can tell exactly which steps already ran
            # (PRAGMA user_version is stored in the database header).
            if conn.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
                logger.info("Database schema version set to %d", SCHEMA_VERSION)

    # ------------------------------------------------------------------ #
    #  Internal helpers for cleaning up attachment files on disk
    # ------------------------------------------------------------------ #
    def _collect_attachment_paths(self, conn, where_clause, params):
        rows = conn.execute(
            f"SELECT id, file_path FROM attachments WHERE {where_clause}",
            params,
        ).fetchall()
        return [r["file_path"] for r in self._resolved_attachments(rows) if r["file_path"]]

    def _remove_files(self, paths):
        for p in paths:
            try:
                root = os.path.realpath(self.attachments_dir)
                if os.path.commonpath([root, os.path.realpath(p)]) != root:
                    logger.warning("Refusing to remove attachment outside data folder")
                    continue
                if os.path.exists(p):
                    os.remove(p)
                    logger.debug("Removed attachment file: %s", p)
            except (OSError, ValueError) as exc:
                logger.warning("Could not remove attachment file %s: %s", p, exc)

    # ---------------- Projects ----------------
    def add_project(self, name, location="", contractor="", project_number="", currency="SAR",
                     notes="", group_id=None):
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO projects (name, location, contractor, project_number, currency, notes, "
                "group_id, created_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, location, contractor, project_number, currency, notes, group_id, now_str()),
            )
            new_id = cur.lastrowid
            _log_change(conn, "project", new_id, name, new_id, "created")
            logger.info("Added project id=%d name=%r", new_id, name)
            return new_id

    def update_project(self, project_id, **fields):
        if not fields:
            return
        current = self.get_project(project_id)
        cols_sql, values, safe_fields = _safe_update(ALLOWED_PROJECT_COLS, fields)
        values.append(project_id)
        entity_name = safe_fields.get("name", current["name"] if current else None)
        with self._connect() as conn:
            conn.execute(f"UPDATE projects SET {cols_sql} WHERE id = ?", values)
            if "group_id" in safe_fields:
                conn.execute("UPDATE projects SET project_group = NULL WHERE id = ?", (project_id,))
            _log_field_diffs(conn, "project", project_id, entity_name, project_id, current, safe_fields)
        logger.info("Updated project id=%d fields=%s", project_id, set(fields))

    def delete_project(self, project_id):
        """Soft delete: the project (and its items/attachments) is hidden
        but not destroyed, so it can be restored via undo/trash."""
        project = self.get_project(project_id)
        if project is None or project["is_deleted"]:
            return
        deleted_at = now_str()
        with self._connect() as conn:
            conn.execute(
                "UPDATE projects SET is_deleted = 1, deleted_at = ? WHERE id = ?",
                (deleted_at, project_id),
            )
            # Record deletion provenance explicitly: timestamps can collide
            # when an item and its project are deleted in the same second.
            conn.execute(
                "UPDATE items SET is_deleted = 1, deleted_at = ?, deleted_with_project = 1 "
                "WHERE project_id = ? AND is_deleted = 0",
                (deleted_at, project_id),
            )
            _log_change(conn, "project", project_id, project["name"] if project else None, project_id, "deleted")
        logger.info("Soft-deleted project id=%d", project_id)

    def restore_project(self, project_id):
        project = self.get_project(project_id)
        with self._connect() as conn:
            row = conn.execute("SELECT deleted_at FROM projects WHERE id = ?", (project_id,)).fetchone()
            deleted_at = row["deleted_at"] if row else None
            conn.execute("UPDATE projects SET is_deleted = 0, deleted_at = NULL WHERE id = ?", (project_id,))
            if deleted_at:
                # NULL provenance is only for legacy records, where the
                # original timestamp-based restoration remains the fallback.
                conn.execute(
                    "UPDATE items SET is_deleted = 0, deleted_at = NULL, deleted_with_project = 0 "
                    "WHERE project_id = ? AND is_deleted = 1 AND "
                    "(deleted_with_project = 1 OR (deleted_with_project IS NULL AND deleted_at = ?))",
                    (project_id, deleted_at),
                )
                # An item deleted on its own earlier and tied to the project
                # by restore_item may carry a stale number; renumber cleanly.
                self._compact_sort_order(conn, project_id)
            _log_change(conn, "project", project_id, project["name"] if project else None, project_id, "restored")
        logger.info("Restored project id=%d", project_id)

    def purge_project(self, project_id):
        """Permanently delete a soft-deleted project and its files. Used by
        the Trash screen's 'Delete Forever' action."""
        project = self.get_project(project_id)
        with self._connect() as conn:
            paths = self._collect_attachment_paths(
                conn, "item_id IN (SELECT id FROM items WHERE project_id = ?)", (project_id,)
            )
            # Explicit deletes (not relying on ON DELETE CASCADE) so this
            # stays correct even on old databases whose tables predate the
            # cascade foreign keys.
            conn.execute(
                "DELETE FROM attachments WHERE item_id IN (SELECT id FROM items WHERE project_id = ?)",
                (project_id,),
            )
            conn.execute("DELETE FROM items WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            _log_change(conn, "project", project_id, project["name"] if project else None, project_id, "purged")
        self._remove_files(paths)
        logger.info("Purged project id=%d permanently", project_id)

    _PROJECT_SELECT = (
        "SELECT projects.*, project_groups.name AS group_name FROM projects "
        "LEFT JOIN project_groups ON projects.group_id = project_groups.id"
    )

    def get_projects(self, include_deleted=False):
        with self._connect() as conn:
            if include_deleted:
                return conn.execute(
                    f"{self._PROJECT_SELECT} WHERE projects.is_deleted = 1 ORDER BY projects.deleted_at DESC"
                ).fetchall()
            return conn.execute(
                f"{self._PROJECT_SELECT} WHERE projects.is_deleted = 0 ORDER BY projects.name"
            ).fetchall()

    def get_projects_in_group(self, group_id):
        with self._connect() as conn:
            return conn.execute(
                f"{self._PROJECT_SELECT} WHERE projects.is_deleted = 0 AND projects.group_id = ? "
                f"ORDER BY projects.name",
                (group_id,),
            ).fetchall()

    def get_project(self, project_id):
        with self._connect() as conn:
            return conn.execute(f"{self._PROJECT_SELECT} WHERE projects.id = ?", (project_id,)).fetchone()

    # ------------------------------------------------------------------ #
    # Project Groups ("main project" that several section-projects
    # belong to — e.g. "QUBA MOSQUE EXPANSION PROJECT" grouping its
    # Toilet Block / Roof Tank / South Irrigation Tank section-projects).
    # Kept intentionally lightweight (no soft-delete/trash of its own):
    # it's just a name-plus-defaults label, cheap to recreate, unlike a
    # project or item which carries real work. Deleting a group never
    # deletes or touches its member projects — they just become
    # ungrouped (group_id set to NULL).
    # ------------------------------------------------------------------ #
    def add_project_group(self, name, location="", contractor="", currency="SAR", notes=""):
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO project_groups (name, location, contractor, currency, notes, created_date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name, location, contractor, currency, notes, now_str()),
            )
            new_id = cur.lastrowid
            logger.info("Added project group id=%d name=%r", new_id, name)
            return new_id

    def update_project_group(self, group_id, **fields):
        if not fields:
            return
        allowed = {"name", "location", "contractor", "currency", "notes"}
        cols_sql, values, safe_fields = _safe_update(allowed, fields)
        values.append(group_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE project_groups SET {cols_sql} WHERE id = ?", values)
        logger.info("Updated project group id=%d fields=%s", group_id, set(fields))

    def delete_project_group(self, group_id):
        """Deletes the group itself and ungroups its member projects
        (they keep all their data — only group_id is cleared)."""
        with self._connect() as conn:
            conn.execute("UPDATE projects SET group_id = NULL, project_group = NULL WHERE group_id = ?", (group_id,))
            conn.execute("DELETE FROM project_groups WHERE id = ?", (group_id,))
        logger.info("Deleted project group id=%d (member projects ungrouped, not deleted)", group_id)

    def get_project_groups(self):
        """Active project groups, each a full row (id, name, location,
        contractor, currency, notes) — for populating group
        pickers/dropdowns and for pre-filling a new project's defaults
        from its group."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM project_groups WHERE is_deleted = 0 ORDER BY name"
            ).fetchall()

    def get_project_group(self, group_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM project_groups WHERE id = ?", (group_id,)).fetchone()

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    #: Groupings the variance report understands.
    VARIANCE_GROUPINGS = ("area", "supplier", "status")

    def get_variance_report(self, group_by="area", project_ids=None):
        """Aggregated supply status per group, for the variance report.

        Quantities are deliberately NOT summed: items inside one group can be
        measured in different units (عدد / م.ط / مجموعة), so a total would be
        meaningless. Counts, completion, attention flags and value are
        comparable - and value is kept per currency rather than converted.

        Returns a list of dicts, sorted by item count descending:
            group, items, delivered, delivered_pct, awaiting_request,
            attention, values {currency: amount}, currency, mixed_currency
        """
        if group_by not in self.VARIANCE_GROUPINGS:
            raise ValueError(f"Unknown grouping: {group_by!r}")

        wanted = [p for p in self.get_projects()
                  if project_ids is None or p["id"] in project_ids]
        items_by_project = self.get_items_for_projects([p["id"] for p in wanted])

        buckets = {}
        for project in wanted:
            for item in items_by_project.get(project["id"], []):
                if group_by == "area":
                    key = (item["pump_station"] or "").strip() or "(no area)"
                elif group_by == "supplier":
                    key = (item["supplier_name"] or "").strip() or "(no supplier)"
                else:
                    key = item["status"] or "(unknown)"

                bucket = buckets.setdefault(key, {
                    "group": key, "items": 0, "delivered": 0,
                    "awaiting_request": 0, "attention": 0, "values": {},
                })
                bucket["items"] += 1

                if item["status"] == "Delivered":
                    bucket["delivered"] += 1
                if item["status"] == "Not requested":
                    bucket["awaiting_request"] += 1
                total = item["total_quantity"] or 0
                requested = item["requested_quantity"] or 0
                delivered = item["delivered_quantity"] or 0
                if (is_over_supplied(total, delivered)
                        or is_over_requested(total, requested)
                        or item["status"] == "On Hold"):
                    bucket["attention"] += 1

                value = total * (item["unit_cost"] or 0)
                if value:
                    currency = item["currency"] or project["currency"] or "(no currency set)"
                    bucket["values"][currency] = bucket["values"].get(currency, 0) + value

        rows = []
        for bucket in buckets.values():
            items = bucket["items"]
            values = bucket["values"]
            rows.append({
                **bucket,
                "delivered_pct": (100.0 * bucket["delivered"] / items) if items else 0.0,
                "currency": max(values, key=values.get) if values else None,
                "mixed_currency": len(values) > 1,
            })
        rows.sort(key=lambda r: (-r["items"], str(r["group"]).lower()))
        return rows


    def get_cost_changes(self, project_ids=None, limit=2000):
        """Every recorded unit-cost change, newest first - the data behind the
        cost-change log report.

        Returns rows of: item_name, project_name, project_id, old_value,
        new_value, changed_at."""
        query = (
            "SELECT a.entity_name AS item_name, a.project_id, p.name AS project_name, "
            "a.old_value, a.new_value, a.changed_at "
            "FROM audit_log a LEFT JOIN projects p ON p.id = a.project_id "
            "WHERE a.entity_type = 'item' AND a.field = 'unit_cost'"
        )
        params = []
        if project_ids is not None:
            placeholders = ", ".join("?" for _ in project_ids)
            query += f" AND a.project_id IN ({placeholders})"
            params += list(project_ids)
        query += " ORDER BY a.changed_at DESC, a.id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()


    # ------------------------------------------------------------------ #
    # Schedule (project time schedule)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _check_schedule_dates(start_date, end_date):
        """Raises when the range is impossible, so a bad edit can never be
        stored - the report and the timeline both assume start <= end."""
        if start_date and end_date and end_date < start_date:
            raise ValueError("The end date cannot be before the start date.")

    def _next_schedule_sort_order(self, conn, project_id):
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM schedule_activities "
            "WHERE project_id = ? AND is_deleted = 0",
            (project_id,),
        ).fetchone()
        return (row["m"] or 0) + 1

    def get_schedule_activities(self, project_id):
        """The project's active activities in schedule order."""
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM schedule_activities "
                "WHERE project_id = ? AND is_deleted = 0 "
                "ORDER BY sort_order, id",
                (project_id,),
            ).fetchall()

    def get_schedule_activity(self, activity_id):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM schedule_activities WHERE id = ?", (activity_id,)
            ).fetchone()

    def add_schedule_activity(self, project_id, name, phase="", start_date=None,
                              end_date=None, progress=0, milestone=False, notes=""):
        name = (name or "").strip()
        if not name:
            raise ValueError("An activity needs a name.")
        self._check_schedule_dates(start_date, end_date)
        progress = max(0, min(100, int(progress or 0)))

        with self._connect() as conn:
            sort_order = self._next_schedule_sort_order(conn, project_id)
            cur = conn.execute(
                """INSERT INTO schedule_activities
                   (project_id, name, phase, start_date, end_date, progress,
                    milestone, notes, sort_order, is_deleted, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (project_id, name, phase or "", start_date or None,
                 end_date or None, progress, 1 if milestone else 0,
                 notes or "", sort_order, now_str()),
            )
            activity_id = cur.lastrowid
            _log_change(conn, "schedule", activity_id, name, project_id, "created")
        logger.info("Added schedule activity id=%d project=%d", activity_id, project_id)
        return activity_id

    def update_schedule_activity(self, activity_id, **fields):
        if not fields:
            return
        current = self.get_schedule_activity(activity_id)
        if current is None:
            return
        start_date = fields.get("start_date", current["start_date"])
        end_date = fields.get("end_date", current["end_date"])
        self._check_schedule_dates(start_date, end_date)
        if "progress" in fields:
            fields["progress"] = max(0, min(100, int(fields["progress"] or 0)))
        fields["last_updated"] = now_str()

        cols_sql, values, safe_fields = _safe_update(ALLOWED_SCHEDULE_COLS, fields)
        values.append(activity_id)
        entity_name = safe_fields.get("name", current["name"])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE schedule_activities SET {cols_sql} WHERE id = ?", values
            )
            _log_field_diffs(conn, "schedule", activity_id, entity_name,
                             current["project_id"], current, safe_fields)
        logger.info("Updated schedule activity id=%d fields=%s", activity_id, set(fields))

    def delete_schedule_activity(self, activity_id):
        """Soft delete, so a mistaken removal is recoverable."""
        activity = self.get_schedule_activity(activity_id)
        if activity is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE schedule_activities SET is_deleted = 1, deleted_at = ? WHERE id = ?",
                (now_str(), activity_id),
            )
            _log_change(conn, "schedule", activity_id, activity["name"],
                        activity["project_id"], "deleted")
        logger.info("Soft-deleted schedule activity id=%d", activity_id)

    def restore_schedule_activity(self, activity_id):
        activity = self.get_schedule_activity(activity_id)
        if activity is None:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE schedule_activities SET is_deleted = 0, deleted_at = NULL WHERE id = ?",
                (activity_id,),
            )
            _log_change(conn, "schedule", activity_id, activity["name"],
                        activity["project_id"], "restored")
        logger.info("Restored schedule activity id=%d", activity_id)

    def reorder_schedule_activities(self, ordered_activity_ids):
        """Renumbers the given activities to 1..n in the order supplied."""
        with self._connect() as conn:
            for position, activity_id in enumerate(ordered_activity_ids, start=1):
                conn.execute(
                    "UPDATE schedule_activities SET sort_order = ? WHERE id = ?",
                    (position, activity_id),
                )

    def move_schedule_activity(self, project_id, activity_id, direction):
        """direction: -1 up, +1 down. Swaps with the neighbour, like items."""
        activities = list(self.get_schedule_activities(project_id))
        ids = [a["id"] for a in activities]
        if activity_id not in ids:
            return
        index = ids.index(activity_id)
        target = index + direction
        if target < 0 or target >= len(ids):
            return
        ids[index], ids[target] = ids[target], ids[index]
        self.reorder_schedule_activities(ids)


    # ---------------- Suppliers ----------------
    def add_supplier(self, name, contact_person="", phone="", email="", notes=""):
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO suppliers (name, contact_person, phone, email, notes) VALUES (?, ?, ?, ?, ?)",
                (name, contact_person, phone, email, notes),
            )
            new_id = cur.lastrowid
            _log_change(conn, "supplier", new_id, name, None, "created")
            logger.info("Added supplier id=%d name=%r", new_id, name)
            return new_id

    def update_supplier(self, supplier_id, **fields):
        if not fields:
            return
        current = self._get_supplier_row(supplier_id)
        cols_sql, values, safe_fields = _safe_update(ALLOWED_SUPPLIER_COLS, fields)
        values.append(supplier_id)
        entity_name = safe_fields.get("name", current["name"] if current else None)
        with self._connect() as conn:
            conn.execute(f"UPDATE suppliers SET {cols_sql} WHERE id = ?", values)
            _log_field_diffs(conn, "supplier", supplier_id, entity_name, None, current, safe_fields)
        logger.info("Updated supplier id=%d fields=%s", supplier_id, set(fields))

    def _get_supplier_row(self, supplier_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM suppliers WHERE id = ?", (supplier_id,)).fetchone()

    def delete_supplier(self, supplier_id):
        supplier = self._get_supplier_row(supplier_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE suppliers SET is_deleted = 1, deleted_at = ? WHERE id = ?",
                (now_str(), supplier_id),
            )
            _log_change(conn, "supplier", supplier_id, supplier["name"] if supplier else None, None, "deleted")
        logger.info("Soft-deleted supplier id=%d", supplier_id)

    def restore_supplier(self, supplier_id):
        supplier = self._get_supplier_row(supplier_id)
        with self._connect() as conn:
            conn.execute("UPDATE suppliers SET is_deleted = 0, deleted_at = NULL WHERE id = ?", (supplier_id,))
            _log_change(conn, "supplier", supplier_id, supplier["name"] if supplier else None, None, "restored")
        logger.info("Restored supplier id=%d", supplier_id)

    def get_suppliers(self, include_deleted=False):
        with self._connect() as conn:
            if include_deleted:
                return conn.execute("SELECT * FROM suppliers WHERE is_deleted = 1 ORDER BY deleted_at DESC").fetchall()
            return conn.execute("SELECT * FROM suppliers WHERE is_deleted = 0 ORDER BY name").fetchall()

    # ------------------------------------------------------------------ #
    # User accounts (multi-user support: accounts + project assignment)
    # ------------------------------------------------------------------ #
    def add_user(self, username, password, role="user", display_name="", is_active=True):
        username = (username or "").strip()
        if not username:
            raise ValueError("Username is required.")
        if role not in ("manager", "user"):
            raise ValueError("Unknown role.")
        salt, password_hash = auth.hash_password(password)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE lower(username) = lower(?)", (username,)
            ).fetchone()
            if existing:
                raise ValueError("Username already exists.")
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, role, display_name, is_active, created_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (username, password_hash, salt, role, display_name or "", int(bool(is_active)), now_str()),
            )
            new_id = cur.lastrowid
            _log_change(conn, "user", new_id, username, None, "created")
        logger.info("Added user id=%s name=%r role=%s", new_id, username, role)
        return new_id

    def count_users(self):
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

    def list_users(self, active_only=False):
        query = "SELECT * FROM users"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY CASE role WHEN 'manager' THEN 0 ELSE 1 END, lower(username)"
        with self._connect() as conn:
            return conn.execute(query).fetchall()

    def get_user(self, user_id):
        with self._connect() as conn:
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def get_user_by_username(self, username):
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE lower(username) = lower(?)", ((username or "").strip(),)
            ).fetchone()

    def update_user(self, user_id, **fields):
        allowed = {"username", "role", "display_name", "is_active"}
        safe = {k: v for k, v in fields.items() if k in allowed}
        if not safe:
            return
        if "role" in safe and safe["role"] not in ("manager", "user"):
            raise ValueError("Unknown role.")
        current = self.get_user(user_id)
        if current is None:
            return
        if "username" in safe:
            safe["username"] = str(safe["username"]).strip()
            if not safe["username"]:
                raise ValueError("Username is required.")
        cols_sql = ", ".join(f"{k} = ?" for k in safe)
        values = list(safe.values()) + [user_id]
        with self._connect() as conn:
            if "username" in safe:
                clash = conn.execute(
                    "SELECT id FROM users WHERE lower(username) = lower(?) AND id != ?",
                    (safe["username"], user_id),
                ).fetchone()
                if clash:
                    raise ValueError("Username already exists.")
            conn.execute(f"UPDATE users SET {cols_sql} WHERE id = ?", values)
            _log_change(conn, "user", user_id, safe.get("username", current["username"]), None, "updated")
        logger.info("Updated user id=%d fields=%s", user_id, set(safe))

    def set_password(self, user_id, password):
        salt, password_hash = auth.hash_password(password)
        current = self.get_user(user_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                (password_hash, salt, user_id),
            )
            _log_change(conn, "user", user_id, current["username"] if current else None, None, "password")
        logger.info("Password changed for user id=%d", user_id)

    def verify_user(self, username, password):
        user = self.get_user_by_username(username)
        if user is None or not user["is_active"]:
            return None
        if auth.verify_password(password, user["salt"], user["password_hash"]):
            return user
        return None

    def set_project_assignee(self, project_id, user_id):
        with self._connect() as conn:
            conn.execute("UPDATE projects SET assigned_user_id = ? WHERE id = ?", (user_id, project_id))
        logger.info("Project id=%s assigned to user id=%s", project_id, user_id)

    def assign_projects_to_user(self, user_id, project_ids):
        """Replace this user's project assignments with the given ids."""
        ids = [int(pid) for pid in project_ids]
        with self._connect() as conn:
            conn.execute("UPDATE projects SET assigned_user_id = NULL WHERE assigned_user_id = ?",
                         (user_id,))
            if ids:
                conn.executemany(
                    "UPDATE projects SET assigned_user_id = ? WHERE id = ?",
                    [(user_id, pid) for pid in ids],
                )
        logger.info("User id=%s now owns %s project(s)", user_id, len(ids))

    def delete_user(self, user_id):
        """Delete an account and return its projects to the unassigned pool."""
        with self._connect() as conn:
            row = conn.execute("SELECT id, role, is_active FROM users WHERE id = ?",
                               (user_id,)).fetchone()
            if row is None:
                raise ValueError("User not found.")
            if row["role"] == "manager" and row["is_active"]:
                active_managers = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE role = 'manager' AND is_active = 1"
                ).fetchone()["n"]
                if active_managers <= 1:
                    raise ValueError("At least one active manager is required.")
            conn.execute("UPDATE projects SET assigned_user_id = NULL WHERE assigned_user_id = ?",
                         (user_id,))
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        logger.info("Deleted user id=%s", user_id)

    # ---------------- Items ----------------
    def _next_sort_order(self, conn, project_id):
        # Only ACTIVE items count: a soft-deleted item keeps its stale
        # sort_order, and including it here would make the next added or
        # restored item leave a visible gap (e.g. 1, 2, 4) in the '#' column.
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM items "
            "WHERE project_id = ? AND is_deleted = 0",
            (project_id,),
        ).fetchone()
        return (row["m"] or 0) + 1

    def add_item(self, project_id, item_name, pump_station="", supplier_id=None, unit="",
                 total_quantity=0, requested_quantity=0, delivered_quantity=0,
                 unit_cost=0, currency=None, remarks="", manual_hold=False,
                 po_issued=False, variance_note=""):
        status = compute_status(total_quantity, requested_quantity, delivered_quantity, manual_hold, po_issued)
        with self._connect() as conn:
            sort_order = self._next_sort_order(conn, project_id)
            cur = conn.execute(
                """INSERT INTO items
                   (project_id, item_name, pump_station, supplier_id, unit, total_quantity,
                    requested_quantity, delivered_quantity, unit_cost, currency, remarks, status,
                    manual_hold, po_issued, variance_note, sort_order, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, item_name, pump_station, supplier_id, unit, total_quantity,
                 requested_quantity, delivered_quantity, unit_cost, currency, remarks, status,
                 int(manual_hold), int(po_issued), variance_note, sort_order, now_str()),
            )
            new_id = cur.lastrowid
            _log_change(conn, "item", new_id, item_name, project_id, "created")
            logger.info("Added item id=%d name=%r to project=%d", new_id, item_name, project_id)
            return new_id

    def duplicate_items(self, project_id, item_ids):
        """Duplicates each of the given items, inserting each copy
        directly after its original — not appended at the end of a
        possibly very long list — since that's what's wanted the
        overwhelming majority of the time (no more manually moving a
        duplicate up through hundreds of rows). Returns the new item ids,
        in the same relative order as *item_ids*."""
        new_ids = []
        new_id_by_original = {}
        for item_id in item_ids:
            item = self.get_item(item_id)
            if item is None:
                continue
            new_id = self.add_item(
                project_id,
                item_name=f"{item['item_name']} (Copy)",
                pump_station=item["pump_station"],
                supplier_id=item["supplier_id"],
                unit=item["unit"],
                currency=item["currency"],
                total_quantity=item["total_quantity"],
                requested_quantity=item["requested_quantity"],
                delivered_quantity=item["delivered_quantity"],
                unit_cost=item["unit_cost"],
                remarks=item["remarks"],
                manual_hold=bool(item["manual_hold"]),
                po_issued=bool(item["po_issued"]),
                variance_note=item["variance_note"] or "",
            )
            new_ids.append(new_id)
            new_id_by_original[item_id] = new_id

        if not new_ids:
            return new_ids

        all_ids = [it["id"] for it in self.get_items(project_id)]
        new_id_set = set(new_ids)
        remaining = [i for i in all_ids if i not in new_id_set]
        final = []
        for i in remaining:
            final.append(i)
            if i in new_id_by_original:
                final.append(new_id_by_original[i])
        self.reorder_items(final)
        return new_ids

    def update_item(self, item_id, **fields):
        if not fields:
            return
        # Recompute status server-side whenever quantities/flags change, so
        # the UI never needs to (and can never fall out of sync).
        current = self.get_item(item_id)
        if current is None:
            raise ValueError(f"Item {item_id} does not exist.")
        # A write that changes nothing must not touch the row: last_updated
        # drives the Dashboard's "stale / possibly forgotten" list, so
        # re-saving identical values (e.g. re-importing a cost sheet that
        # still holds the current prices) would wrongly reset it.
        if not any(
            key in ALLOWED_ITEM_COLS and key not in ("status", "last_updated")
            and not _same_value(current[key], value)
            for key, value in fields.items()
        ):
            return
        total_qty = fields.get("total_quantity", current["total_quantity"])
        requested_qty = fields.get("requested_quantity", current["requested_quantity"])
        delivered_qty = fields.get("delivered_quantity", current["delivered_quantity"])
        manual_hold = fields.get("manual_hold", current["manual_hold"])
        po_issued = fields.get("po_issued", current["po_issued"])
        fields["status"] = compute_status(total_qty, requested_qty, delivered_qty, manual_hold, po_issued)
        fields["last_updated"] = now_str()
        cols_sql, values, safe_fields = _safe_update(ALLOWED_ITEM_COLS, fields)
        values.append(item_id)
        entity_name = safe_fields.get("item_name", current["item_name"])
        project_id = current["project_id"]
        with self._connect() as conn:
            conn.execute(f"UPDATE items SET {cols_sql} WHERE id = ?", values)
            _log_field_diffs(conn, "item", item_id, entity_name, project_id, current, safe_fields)
        logger.info("Updated item id=%d fields=%s", item_id, set(fields))

    def _compact_sort_order(self, conn, project_id):
        """Renumber all active (non-deleted) items in a project as a clean
        1..N sequence with no gaps. Called after any delete so the visible
        '#' column never shows jumps like 39, 42, 43 after 40/41 are gone."""
        rows = conn.execute(
            "SELECT id, sort_order FROM items WHERE project_id = ? AND is_deleted = 0 ORDER BY sort_order, id",
            (project_id,),
        ).fetchall()
        # Only rows whose number actually changes are written, so the
        # startup check on an already-clean database writes nothing.
        for idx, r in enumerate(rows, start=1):
            if r["sort_order"] != idx:
                conn.execute("UPDATE items SET sort_order = ? WHERE id = ?", (idx, r["id"]))

    def delete_item(self, item_id):
        item = self.get_item(item_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE items SET is_deleted = 1, deleted_at = ?, deleted_with_project = 0 WHERE id = ?",
                (now_str(), item_id),
            )
            _log_change(conn, "item", item_id, item["item_name"] if item else None,
                       item["project_id"] if item else None, "deleted")
            if item is not None:
                self._compact_sort_order(conn, item["project_id"])
        logger.info("Soft-deleted item id=%d", item_id)

    def restore_item(self, item_id):
        item = self.get_item(item_id)
        if item is None:
            # Purged meanwhile (e.g. "Delete Forever" before Undo): nothing
            # left to restore, and nothing to crash on.
            logger.warning("restore_item: item id=%s no longer exists", item_id)
            return False
        project = self.get_project(item["project_id"])
        if project is not None and project["is_deleted"]:
            # Restoring it now would make it "active" inside a project nobody
            # can see. Instead tie it to the project: it comes back together
            # with the project when that is restored from the trash.
            with self._connect() as conn:
                conn.execute("UPDATE items SET deleted_with_project = 1 WHERE id = ?", (item_id,))
            logger.info("restore_item: item id=%s will return with project id=%s",
                        item_id, item["project_id"])
            return False
        with self._connect() as conn:
            # Put the restored item at the end of the current sequence
            # rather than its old sort_order, which may now collide with
            # (or be stale relative to) the already-compacted numbering.
            new_order = self._next_sort_order(conn, item["project_id"]) if item else None
            conn.execute(
                "UPDATE items SET is_deleted = 0, deleted_at = NULL, deleted_with_project = 0, sort_order = COALESCE(?, sort_order) WHERE id = ?",
                (new_order, item_id),
            )
            _log_change(conn, "item", item_id, item["item_name"] if item else None,
                       item["project_id"] if item else None, "restored")
        logger.info("Restored item id=%d", item_id)
        return True

    def purge_item(self, item_id):
        item = self.get_item(item_id)
        with self._connect() as conn:
            paths = self._collect_attachment_paths(conn, "item_id = ?", (item_id,))
            conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            _log_change(conn, "item", item_id, item["item_name"] if item else None,
                       item["project_id"] if item else None, "purged")
        self._remove_files(paths)
        logger.info("Purged item id=%d permanently", item_id)

    def get_items(self, project_id):
        with self._connect() as conn:
            return conn.execute(
                """SELECT items.*, suppliers.name AS supplier_name
                   FROM items LEFT JOIN suppliers ON items.supplier_id = suppliers.id
                   WHERE items.project_id = ? AND items.is_deleted = 0
                   ORDER BY items.sort_order, items.id""",
                (project_id,),
            ).fetchall()

    def get_item(self, item_id):
        with self._connect() as conn:
            return conn.execute(
                """SELECT items.*, suppliers.name AS supplier_name
                   FROM items LEFT JOIN suppliers ON items.supplier_id = suppliers.id
                   WHERE items.id = ?""",
                (item_id,),
            ).fetchone()

    def reorder_items(self, ordered_item_ids):
        """Given item ids in their new desired order, renumber sort_order
        as a clean 1..N sequence (no gaps, no duplicates)."""
        with self._connect() as conn:
            for idx, item_id in enumerate(ordered_item_ids, start=1):
                conn.execute("UPDATE items SET sort_order = ? WHERE id = ?", (idx, item_id))
        logger.info("Reordered %d items", len(ordered_item_ids))

    def move_item(self, project_id, item_id, direction):
        """direction: -1 to move up, +1 to move down. Swaps sort_order with
        the neighbouring item and renumbers cleanly."""
        items = list(self.get_items(project_id))
        ids = [it["id"] for it in items]
        if item_id not in ids:
            return
        idx = ids.index(item_id)
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(ids):
            return
        ids[idx], ids[new_idx] = ids[new_idx], ids[idx]
        self.reorder_items(ids)

    def move_items_group(self, project_id, selected_ids, direction):
        """Moves several selected items up/down together, as a group, in
        one step — the standard multi-select reorder behavior (like
        reordering multiple selected tracks in a playlist): each selected
        item shifts one position past its nearest non-selected neighbor,
        so the whole selection moves as a block instead of each item
        fighting the others for position. direction: -1 up, +1 down."""
        items = list(self.get_items(project_id))
        ids = [it["id"] for it in items]
        selected_set = set(selected_ids) & set(ids)
        if not selected_set:
            return
        n = len(ids)
        order = range(n) if direction < 0 else range(n - 1, -1, -1)
        for i in order:
            if ids[i] in selected_set:
                j = i + direction
                if 0 <= j < n and ids[j] not in selected_set:
                    ids[i], ids[j] = ids[j], ids[i]
        self.reorder_items(ids)

    def move_items_to_edge(self, project_id, selected_ids, to_top):
        """Moves the whole selected group straight to the very top or
        bottom of the list in one step — for when you know exactly where
        something belongs and clicking Move Up/Down one row at a time
        through a long list (e.g. 350+ items) would be impractical.
        Selected items keep their relative order among themselves."""
        items = list(self.get_items(project_id))
        ids = [it["id"] for it in items]
        selected_set = set(selected_ids) & set(ids)
        if not selected_set:
            return
        selected_ordered = [i for i in ids if i in selected_set]
        rest = [i for i in ids if i not in selected_set]
        final = (selected_ordered + rest) if to_top else (rest + selected_ordered)
        self.reorder_items(final)

    def move_items_to_position(self, project_id, selected_ids, target_position):
        """Moves the selected group so it starts at 1-based position
        *target_position* in the full (unfiltered) item sequence — a
        direct jump instead of stepping through every row in between.
        Selected items keep their relative order among themselves."""
        items = list(self.get_items(project_id))
        ids = [it["id"] for it in items]
        selected_set = set(selected_ids) & set(ids)
        if not selected_set:
            return
        selected_ordered = [i for i in ids if i in selected_set]
        rest = [i for i in ids if i not in selected_set]
        idx = max(0, min(target_position - 1, len(rest)))
        final = rest[:idx] + selected_ordered + rest[idx:]
        self.reorder_items(final)

    # ---------------- Attachments ----------------
    def add_attachment(self, item_id, category, source_file_path):
        item_folder = os.path.join(self.attachments_dir, f"item_{item_id}")
        os.makedirs(item_folder, exist_ok=True)
        original_name = os.path.basename(source_file_path)
        unique_name = f"{uuid.uuid4().hex[:8]}_{original_name}"
        dest_path = self.resolve_attachment_path(f"item_{item_id}/{unique_name}")
        shutil.copy2(source_file_path, dest_path)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO attachments (item_id, category, file_path, original_name, uploaded_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (item_id, category, os.path.relpath(dest_path, self.attachments_dir).replace("\\", "/"), original_name, now_str()),
            )
            self._log_attachment(conn, item_id, "attachment_added", category, original_name)
        logger.info("Attached %r (%s) to item=%d", original_name, category, item_id)
        return dest_path

    def get_attachments(self, item_id, category=None):
        with self._connect() as conn:
            if category:
                return self._resolved_attachments(conn.execute(
                    "SELECT * FROM attachments WHERE item_id = ? AND category = ? AND is_deleted = 0 ORDER BY id",
                    (item_id, category),
                ).fetchall())
            return self._resolved_attachments(conn.execute(
                "SELECT * FROM attachments WHERE item_id = ? AND is_deleted = 0 ORDER BY category, id", (item_id,)
            ).fetchall())

    def get_all_attachments_for_project(self, project_id):
        with self._connect() as conn:
            return self._resolved_attachments(conn.execute(
                """SELECT a.* FROM attachments a
                   JOIN items i ON a.item_id = i.id
                   WHERE i.project_id = ? AND a.is_deleted = 0 AND i.is_deleted = 0
                   ORDER BY a.item_id, a.category, a.id""",
                (project_id,),
            ).fetchall())

    def get_item_attachment_categories(self, project_id):
        """{item_id: set(category names)} for every item in the project
        that has at least one attachment — one query for the whole
        project, used to flag items missing a PR/PO without opening the
        Attachments dialog for each one."""
        by_item = defaultdict(set)
        for a in self.get_all_attachments_for_project(project_id):
            by_item[a["item_id"]].add(a["category"])
        return dict(by_item)

    def _log_attachment(self, conn, item_id, action, category, original_name):
        """Attachment changes go into the ITEM's history (entity 'item'),
        so they show in the item's History and the project's Activity."""
        item = conn.execute("SELECT item_name, project_id FROM items WHERE id = ?", (item_id,)).fetchone()
        _log_change(conn, "item", item_id, item["item_name"] if item else None,
                    item["project_id"] if item else None, action,
                    field=category, new_value=original_name)

    def _attachment_row(self, conn, attachment_id):
        return conn.execute(
            "SELECT item_id, category, original_name FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()

    def delete_attachment(self, attachment_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE attachments SET is_deleted = 1, deleted_at = ? WHERE id = ?",
                (now_str(), attachment_id),
            )
            row = self._attachment_row(conn, attachment_id)
            if row is not None:
                self._log_attachment(conn, row["item_id"], "attachment_deleted",
                                     row["category"], row["original_name"])
        logger.info("Soft-deleted attachment id=%d", attachment_id)

    def restore_attachment(self, attachment_id):
        with self._connect() as conn:
            conn.execute("UPDATE attachments SET is_deleted = 0, deleted_at = NULL WHERE id = ?", (attachment_id,))
            row = self._attachment_row(conn, attachment_id)
            if row is not None:
                self._log_attachment(conn, row["item_id"], "attachment_restored",
                                     row["category"], row["original_name"])
        logger.info("Restored attachment id=%d", attachment_id)

    # ---------------- Trash / housekeeping ----------------
    def empty_trash(self, older_than_days=None):
        """Permanently purge soft-deleted projects past a given age.
        (Soft-deleted items/suppliers are purged individually via
        purge_item or the Trash screens' "Delete Forever" actions.)
        Called explicitly from the Trash screen."""
        with self._connect() as conn:
            if older_than_days is None:
                proj_ids = [r["id"] for r in conn.execute("SELECT id FROM projects WHERE is_deleted = 1")]
            else:
                cutoff = datetime.now().timestamp() - older_than_days * 86400
                proj_ids = [
                    r["id"] for r in conn.execute("SELECT id, deleted_at FROM projects WHERE is_deleted = 1")
                    if r["deleted_at"] and datetime.strptime(r["deleted_at"], "%Y-%m-%d %H:%M:%S").timestamp() < cutoff
                ]
        for pid in proj_ids:
            self.purge_project(pid)
        return len(proj_ids)

    @staticmethod
    def _deleted_before(deleted_at, cutoff):
        if cutoff is None:
            return True
        try:
            return datetime.strptime(deleted_at, "%Y-%m-%d %H:%M:%S") < cutoff
        except (TypeError, ValueError):
            return False  # unknown age: keep it

    def trash_summary(self, older_than_days=None):
        """What empty_trash_items_and_projects would remove: counts of
        trashed projects (with their items) and of items deleted one by one
        from projects that are still active."""
        cutoff = None if older_than_days is None else datetime.now() - timedelta(days=older_than_days)
        with self._connect() as conn:
            projects = [r for r in conn.execute("SELECT id, deleted_at FROM projects WHERE is_deleted = 1")
                        if self._deleted_before(r["deleted_at"], cutoff)]
            project_ids = [r["id"] for r in projects]
            items_in_projects = 0
            if project_ids:
                marks = ", ".join("?" for _ in project_ids)
                items_in_projects = conn.execute(
                    f"SELECT COUNT(*) FROM items WHERE project_id IN ({marks})", project_ids
                ).fetchone()[0]
            loose = [r["id"] for r in conn.execute(
                "SELECT i.id, i.deleted_at FROM items i JOIN projects p ON p.id = i.project_id "
                "WHERE i.is_deleted = 1 AND p.is_deleted = 0")
                if self._deleted_before(r["deleted_at"], cutoff)]
        return {"project_ids": project_ids, "projects": len(project_ids),
                "items_in_projects": items_in_projects,
                "loose_item_ids": loose, "loose_items": len(loose)}

    def empty_trash_items_and_projects(self, older_than_days=None):
        """Permanently removes what trash_summary() reports. Returns that
        summary. The caller is expected to take a backup first."""
        summary = self.trash_summary(older_than_days)
        for item_id in summary["loose_item_ids"]:
            self.purge_item(item_id)
        for project_id in summary["project_ids"]:
            self.purge_project(project_id)
        return summary

    # ---------------- Activity / audit log ----------------
    def get_activity(self, project_id=None, entity_type=None, entity_id=None, limit=300):
        """Flexible timeline query, used by:
          - the project-level Activity tab: get_activity(project_id=X)
            (matches item changes belonging to that project AND changes to
            the project itself).
          - a single item's/supplier's History dialog:
            get_activity(entity_type='item'|'supplier', entity_id=X).
        """
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if entity_type is not None and entity_id is not None:
            query += " AND entity_type = ? AND entity_id = ?"
            params += [entity_type, entity_id]
        elif project_id is not None:
            query += " AND (project_id = ? OR (entity_type = 'project' AND entity_id = ?))"
            params += [project_id, project_id]
        elif entity_type is not None:
            query += " AND entity_type = ?"
            params.append(entity_type)
        query += " ORDER BY changed_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return conn.execute(query, params).fetchall()

    # ---------------- AI chat memory ----------------
    def save_chat_message(self, scope_project_id, role, content, scope_group_id=None):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO ai_chat_history (scope_project_id, scope_group_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (scope_project_id, scope_group_id, role, content, now_str()),
            )

    def get_chat_history(self, scope_project_id, limit=100, scope_group_id=None):
        """Chat is stored per scope — a specific project's id, a specific
        group's id, or NULL/NULL for the "All projects" scope — so
        switching scope shows the right conversation instead of mixing
        everything together. scope_project_id and scope_group_id are
        mutually exclusive; pass only one (or neither for "All")."""
        with self._connect() as conn:
            if scope_group_id is not None:
                rows = conn.execute(
                    "SELECT * FROM ai_chat_history WHERE scope_group_id = ? "
                    "ORDER BY id DESC LIMIT ?", (scope_group_id, limit),
                ).fetchall()
            elif scope_project_id is None:
                rows = conn.execute(
                    "SELECT * FROM ai_chat_history WHERE scope_project_id IS NULL AND scope_group_id IS NULL "
                    "ORDER BY id DESC LIMIT ?", (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ai_chat_history WHERE scope_project_id = ? "
                    "ORDER BY id DESC LIMIT ?", (scope_project_id, limit),
                ).fetchall()
        return list(reversed(rows))

    def clear_chat_history(self, scope_project_id, scope_group_id=None):
        with self._connect() as conn:
            if scope_group_id is not None:
                conn.execute("DELETE FROM ai_chat_history WHERE scope_group_id = ?", (scope_group_id,))
            elif scope_project_id is None:
                conn.execute(
                    "DELETE FROM ai_chat_history WHERE scope_project_id IS NULL AND scope_group_id IS NULL"
                )
            else:
                conn.execute("DELETE FROM ai_chat_history WHERE scope_project_id = ?", (scope_project_id,))

    # ------------------------------------------------------------------ #
    # Cross-project helpers: bulk edit, global search, dashboard summary
    # ------------------------------------------------------------------ #
    def bulk_update_items(self, item_ids, **fields):
        """Applies the same field value(s) to several items at once (e.g.
        the same supplier across 40 items) — a thin loop over
        update_item, so status recompute and per-item audit logging stay
        identical to editing one item normally, just repeated. All-or-nothing:
        if one item fails, none of them is changed."""
        with self.transaction():
            for item_id in item_ids:
                self.update_item(item_id, **dict(fields))

    BULK_REPLACE_FIELDS = [
        ("item_name", "Item Name"),
        ("pump_station", "Pump Station / Area"),
        ("unit", "Unit"),
        ("remarks", "Remarks"),
    ]

    def count_find_replace_matches(self, item_ids, field, find_text, case_sensitive=False):
        """How many of the given items currently contain find_text in
        field — used to preview the effect before actually applying
        bulk_find_replace."""
        if not find_text:
            return 0
        needle = find_text if case_sensitive else find_text.lower()
        count = 0
        for item_id in item_ids:
            item = self.get_item(item_id)
            if item is None:
                continue
            current = item[field] or ""
            haystack = current if case_sensitive else current.lower()
            if needle in haystack:
                count += 1
        return count

    def bulk_find_replace(self, item_ids, field, find_text, replace_text, case_sensitive=False):
        """Replaces one piece of text with another across several items'
        same field at once (e.g. fixing a recurring typo or standardizing
        inconsistent wording in Remarks/Item Name across many items at
        once). Only items whose field actually contains find_text are
        touched or counted — everything else is left completely alone.
        Returns the number of items actually updated."""
        allowed = dict(self.BULK_REPLACE_FIELDS)
        if field not in allowed:
            raise ValueError(f"field must be one of {list(allowed)}")
        if not find_text:
            return 0

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(re.escape(find_text), flags)

        updated = 0
        with self.transaction():  # all-or-nothing across every item
            for item_id in item_ids:
                item = self.get_item(item_id)
                if item is None:
                    continue
                current = item[field] or ""
                if not pattern.search(current):
                    continue
                new_value = pattern.sub(lambda m: replace_text, current)
                if new_value != current:
                    self.update_item(item_id, **{field: new_value})
                    updated += 1
        return updated

    SEARCHABLE_ITEM_FIELDS = [
        ("item_name", "Item Name"),
        ("pump_station", "Area"),
        ("supplier_name", "Supplier"),
        ("remarks", "Remarks"),
        ("unit", "Unit"),
        ("status", "Status"),
    ]

    @staticmethod
    def _field_matches(value, query_words, query_phrase, mode):
        """mode: "contains" (default) = value contains the query as one
        phrase, in that exact word order. "include" = value contains
        every word from the query somewhere, in ANY order — e.g.
        "قطر 100 طول الف" also matches a cell written as "طول الف قطر
        100", since commas/word order in real BOQ entries are
        inconsistent. "equal" = value equals the query exactly."""
        value = (value or "").lower()
        if mode == "equal":
            return value.strip() == query_phrase.strip()
        if mode == "include":
            return all(w in value for w in query_words)
        return query_phrase in value

    def search_items_across_projects(self, query, fields=None, project_ids=None, mode="contains"):
        """Case-insensitive search — for a quick 'where is this item'
        lookup without opening each project one by one. By default
        searches every active (non-deleted) project; pass `project_ids`
        (e.g. one project's id, or every project in a chosen group) to
        scope the search instead of scanning everything. By default
        matches against item_name, pump_station/area, supplier name,
        remarks (people often note a drawing/plate number there), unit,
        and status — pass `fields` (a list of keys from
        SEARCHABLE_ITEM_FIELDS, e.g. ["remarks"]) to search only specific
        column(s) instead of every field. `mode` controls how the query
        text is matched — see _field_matches — and defaults to the
        original "contains the whole phrase" behavior. Each result row
        carries which field(s) matched ("matched_fields") plus its
        project_id/project_name."""
        query_phrase = (query or "").strip().lower()
        if not query_phrase:
            return []
        query_words = [w for w in query_phrase.split() if w]

        searchable_fields = self.SEARCHABLE_ITEM_FIELDS
        if fields is not None:
            wanted = set(fields)
            searchable_fields = [(k, label) for k, label in searchable_fields if k in wanted]
            if not searchable_fields:
                return []

        wanted_projects = set(project_ids) if project_ids is not None else None

        results = []
        for project in self.get_projects():
            if wanted_projects is not None and project["id"] not in wanted_projects:
                continue
            for item in self.get_items(project["id"]):
                matched = [label for key, label in searchable_fields
                           if self._field_matches(item[key], query_words, query_phrase, mode)]
                if matched:
                    row = dict(item)
                    row["project_id"] = project["id"]
                    row["project_name"] = project["name"]
                    row["matched_fields"] = matched
                    results.append(row)
        return results

    def get_items_for_projects(self, project_ids=None):
        """Every active item across projects in ONE query, grouped by project.

        Returns the same rows get_items() returns (supplier name included) but
        without the N+1 round trips: the Dashboard and the Projects screen used
        to call get_items() once per project on every refresh.
        """
        query = (
            "SELECT items.*, suppliers.name AS supplier_name "
            "FROM items LEFT JOIN suppliers ON items.supplier_id = suppliers.id "
            "WHERE items.is_deleted = 0"
        )
        params = []
        if project_ids is not None:
            ids = list(project_ids)
            if not ids:
                return {}
            query += f" AND items.project_id IN ({', '.join('?' for _ in ids)})"
            params += ids
        query += " ORDER BY items.project_id, items.sort_order, items.id"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        grouped = {}
        for row in rows:
            grouped.setdefault(row["project_id"], []).append(row)
        return grouped

    def get_dashboard_summary(self, stale_days=14, project_ids=None):
        """Aggregates status/cost/data-completeness across the given
        projects in one pass — backs the Dashboard screen. project_ids
        limits the summary to those specific projects (None = every
        active project). stale_days controls how long an item can sit at
        "Not requested" with no activity before it's flagged as possibly
        forgotten."""
        projects = self.get_projects()
        if project_ids is not None:
            wanted = set(project_ids)
            projects = [p for p in projects if p["id"] in wanted]
        status_counts = defaultdict(int)
        value_by_currency = defaultdict(float)
        total_items = 0
        missing_cost_count = 0
        stale_items = []
        cutoff = datetime.now() - timedelta(days=stale_days)

        # One query for every item, then walked per project in the same
        # project order as before, so the numbers (and the stale-list order)
        # are identical to the per-project version.
        items_by_project = self.get_items_for_projects([p["id"] for p in projects])

        for project in projects:
            for it in items_by_project.get(project["id"], []):
                total_items += 1
                status_counts[it["status"]] += 1
                value_by_currency[it["currency"] or project["currency"] or "?"] += (it["total_quantity"] or 0) * (it["unit_cost"] or 0)
                if not it["unit_cost"]:
                    missing_cost_count += 1
                if it["status"] == "Not requested" and it["last_updated"]:
                    try:
                        last_dt = datetime.strptime(it["last_updated"], "%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        last_dt = None
                    if last_dt and last_dt < cutoff:
                        row = dict(it)
                        row["project_name"] = project["name"]
                        row["days_stale"] = (datetime.now() - last_dt).days
                        stale_items.append(row)

        stale_items.sort(key=lambda r: r["days_stale"], reverse=True)
        return {
            "project_count": len(projects),
            "item_count": total_items,
            "status_counts": dict(status_counts),
            "value_by_currency": dict(value_by_currency),
            "missing_cost_count": missing_cost_count,
            "stale_items": stale_items,
        }

    def get_project_delivery_stats(self):
        """{project_id: {"items": n, "delivered": n}} in one pass — backs the
        "Delivered %" column on the Projects screen.

        An item counts as delivered when its stored status is "Delivered",
        which is exactly the rule compute_status() applies, so this column
        can never disagree with the Dashboard's status breakdown."""
        projects = self.get_projects()
        items_by_project = self.get_items_for_projects([p["id"] for p in projects])
        stats = {}
        for project in projects:
            items = items_by_project.get(project["id"], [])
            delivered = sum(1 for it in items if it["status"] == "Delivered")
            stats[project["id"]] = {"items": len(items), "delivered": delivered}
        return stats

