"""
backup.py
Automatic, unattended backups of the database file — protection against
corruption, a bad edit, or an accidental delete, without the user having
to remember to do anything themselves.

Runs once per app startup and only actually creates a new backup file if
today doesn't already have one, so opening/closing the app several times
in one day doesn't pile up duplicate backups. Only backs up the database
itself (fast, always small) — the full backup including all attachment
files is the separate, explicit "File \u2192 Backup Now..." action, since
attachments can be large and copying them on every single startup would
slow the app down for no real benefit (they don't change nearly as often
as the database does).

Old auto-backups are pruned automatically, keeping the most recent
MAX_AUTO_BACKUPS (default: 14, roughly two weeks of daily snapshots).
"""

import logging
import os
import re
import shutil
import sqlite3
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_AUTO_BACKUPS = 14      # newest daily snapshots always kept
KEEP_WEEKLY = 8            # + the newest snapshot of each of the last 8 weeks
KEEP_MONTHLY = 12          # + the newest snapshot of each of the last 12 months
_BACKUP_NAME_RE = re.compile(r"^project_tracker_(\d{4}-\d{2}-\d{2})_(\d{6})\.db$")


def snapshot_database(source_path, destination_path):
    """Copy a committed SQLite snapshot, including data held in the WAL."""
    src = sqlite3.connect(source_path, timeout=30)
    try:
        dst = sqlite3.connect(destination_path)
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def backups_dir_for(data_dir):
    return os.path.join(data_dir, "backups")


def _existing_backups(backups_dir):
    """Returns [(datetime, filepath), ...] for every auto-backup file
    found, sorted oldest to newest."""
    if not os.path.isdir(backups_dir):
        return []
    found = []
    for name in os.listdir(backups_dir):
        m = _BACKUP_NAME_RE.match(name)
        if m:
            try:
                dt = datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S")
            except ValueError:
                continue
            found.append((dt, os.path.join(backups_dir, name)))
    found.sort(key=lambda pair: pair[0])
    return found


def check_integrity(db_path):
    """Runs SQLite's quick_check on *db_path* without changing it.

    Returns (ok, message). A missing file counts as ok (nothing to check
    yet); a file SQLite cannot even open counts as not ok."""
    if not os.path.isfile(db_path):
        return True, ""
    try:
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, str(exc)
    messages = [str(r[0]) for r in rows]
    if messages == ["ok"]:
        return True, ""
    return False, "; ".join(messages[:5])


def maybe_create_auto_backup(db_path, data_dir, prune=True):
    """Creates a new dated backup of db_path if one hasn't already been
    made today, then prunes old auto-backups beyond MAX_AUTO_BACKUPS.
    Safe to call on every app startup — never raises (a failed backup
    should never stop the app from opening), and does nothing if there's
    no database yet (a brand-new install). Returns the new backup's path,
    or None if no new backup was created.

    prune=False keeps every existing backup - used when the live database
    failed its integrity check, so a damaged copy can never push the last
    good backups out of the rotation."""
    if not os.path.isfile(db_path):
        return None

    backups_dir = backups_dir_for(data_dir)
    try:
        os.makedirs(backups_dir, exist_ok=True)
    except OSError:
        logger.warning("Could not create backups folder at %s", backups_dir)
        return None

    existing = _existing_backups(backups_dir)
    if existing and existing[-1][0].date() == date.today():
        if prune:
            _prune_old_backups(backups_dir, existing)
        return None

    now = datetime.now()
    dest = os.path.join(backups_dir, f"project_tracker_{now.strftime('%Y-%m-%d_%H%M%S')}.db")
    try:
        # Snapshot with SQLite's own backup API instead of copying the file:
        # a plain copy made while the app is writing could capture a torn
        # mid-transaction state; the API always yields a consistent,
        # fully-restorable database.
        src = sqlite3.connect(db_path, timeout=30)
        try:
            dst = sqlite3.connect(dest)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except (OSError, sqlite3.Error):
        logger.warning("Automatic backup failed (disk full / permissions?)", exc_info=True)
        try:
            if os.path.exists(dest):
                os.remove(dest)
        except OSError:
            pass
        return None

    logger.info("Automatic backup created: %s", dest)
    if prune:
        _prune_old_backups(backups_dir, existing + [(now, dest)])
    return dest


def _backups_to_keep(backups, today=None):
    """Tiered retention: the newest MAX_AUTO_BACKUPS snapshots, plus the
    newest one of each recent week (KEEP_WEEKLY) and month (KEEP_MONTHLY).

    A problem nobody notices for a few weeks (a wrong bulk edit, a bad
    import) must still be recoverable, so older history thins out instead
    of disappearing after two weeks."""
    today = today or date.today()
    ordered = sorted(backups, key=lambda pair: pair[0])
    keep = {path for _dt, path in ordered[-MAX_AUTO_BACKUPS:]} if MAX_AUTO_BACKUPS > 0 else set()

    this_week = today.isocalendar()[:2]
    newest_per_week = {}
    newest_per_month = {}
    for dt, path in ordered:
        week = dt.date().isocalendar()[:2]
        weeks_ago = (this_week[0] - week[0]) * 52 + (this_week[1] - week[1])
        if 0 <= weeks_ago < KEEP_WEEKLY:
            newest_per_week[week] = path
        months_ago = (today.year - dt.year) * 12 + (today.month - dt.month)
        if 0 <= months_ago < KEEP_MONTHLY:
            newest_per_month[(dt.year, dt.month)] = path
    keep.update(newest_per_week.values())
    keep.update(newest_per_month.values())
    return keep


def _prune_old_backups(backups_dir, backups):
    keep = _backups_to_keep(backups)
    for _dt, path in backups:
        if path in keep:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def mirror_attachments(attachments_dir, data_dir):
    """Copies new or changed attachment files into backups/attachments.

    Incremental (only what changed is copied) and add-only: a file removed
    from the live folder - e.g. by "Delete Forever" - stays in the mirror,
    so a mistaken permanent delete can still be recovered. Returns the
    number of files copied; never raises."""
    if not attachments_dir or not os.path.isdir(attachments_dir):
        return 0
    mirror = os.path.join(backups_dir_for(data_dir), "attachments")
    copied = 0
    for root, _dirs, files in os.walk(attachments_dir):
        rel = os.path.relpath(root, attachments_dir)
        target_dir = os.path.normpath(os.path.join(mirror, rel))
        for name in files:
            src = os.path.join(root, name)
            dst = os.path.join(target_dir, name)
            try:
                st = os.stat(src)
                if os.path.exists(dst):
                    dt = os.stat(dst)
                    if dt.st_size == st.st_size and int(dt.st_mtime) >= int(st.st_mtime):
                        continue
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
            except OSError:
                logger.warning("Could not mirror attachment %s", src, exc_info=True)
    if copied:
        logger.info("Mirrored %d attachment file(s) into %s", copied, mirror)
    return copied


def copy_to_extra_folder(backup_path, extra_dir):
    """Copies a finished snapshot to a second location (another drive,
    OneDrive / Google Drive folder, USB) and applies the same retention
    there. A backup on the same disk as the data does not survive a disk
    failure or theft. Returns the copied path, or None; never raises."""
    if not backup_path or not extra_dir:
        return None
    if not os.path.isdir(extra_dir):
        logger.warning("Second backup folder is not available: %s", extra_dir)
        return None
    try:
        dest = os.path.join(extra_dir, os.path.basename(backup_path))
        shutil.copy2(backup_path, dest)
    except OSError:
        logger.warning("Could not copy backup to %s", extra_dir, exc_info=True)
        return None
    _prune_old_backups(extra_dir, _existing_backups(extra_dir))
    logger.info("Backup copied to second folder: %s", dest)
    return dest


def last_backup_datetime(data_dir):
    """The timestamp of the most recent automatic backup, or None if
    there isn't one yet — used to show "Last backup: ..." in the status
    bar."""
    existing = _existing_backups(backups_dir_for(data_dir))
    return existing[-1][0] if existing else None


def restore_backup(source_path, target_dir):
    """Restores a backup into *target_dir*, which must be a folder of its own.

    Never restores over live data: the caller points the app at the restored
    folder afterwards (or not). Accepts either an automatic .db snapshot or a
    full .zip backup (database + attachments).

    Returns the path of the restored database. Raises on a corrupt archive or
    an archive whose entries would escape the target folder.
    """
    import zipfile

    if not os.path.isfile(source_path):
        raise FileNotFoundError(source_path)

    os.makedirs(target_dir, exist_ok=True)
    target_root = os.path.abspath(target_dir)
    db_target = os.path.join(target_dir, "project_tracker.db")

    if source_path.lower().endswith(".zip"):
        with zipfile.ZipFile(source_path) as archive:
            for member in archive.namelist():
                destination = os.path.abspath(os.path.join(target_dir, member))
                # Zip-slip guard: a crafted archive must not be able to write
                # outside the folder the user chose.
                if not destination.startswith(target_root + os.sep) and destination != target_root:
                    raise ValueError(f"Unsafe path in backup: {member!r}")
            archive.extractall(target_dir)
        if not os.path.isfile(db_target):
            raise ValueError("The backup does not contain a database.")
    else:
        shutil.copy2(source_path, db_target)

    logger.info("Restored backup %s into %s", source_path, target_dir)
    return db_target
