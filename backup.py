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

logger = logging.getLogger(__name__)

MAX_AUTO_BACKUPS = 14
_BACKUP_NAME_RE = re.compile(r"^project_tracker_(\d{4}-\d{2}-\d{2})_(\d{6})\.db$")


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


def maybe_create_auto_backup(db_path, data_dir):
    """Creates a new dated backup of db_path if one hasn't already been
    made today, then prunes old auto-backups beyond MAX_AUTO_BACKUPS.
    Safe to call on every app startup — never raises (a failed backup
    should never stop the app from opening), and does nothing if there's
    no database yet (a brand-new install). Returns the new backup's path,
    or None if no new backup was created."""
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
        _prune_old_backups(backups_dir, existing)
        return None

    now = datetime.now()
    dest = os.path.join(backups_dir, f"project_tracker_{now.strftime('%Y-%m-%d_%H%M%S')}.db")
    try:
        # Snapshot with SQLite's own backup API instead of copying the file:
        # a plain copy made while the app is writing could capture a torn
        # mid-transaction state; the API always yields a consistent,
        # fully-restorable database.
        src = sqlite3.connect(db_path)
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
    _prune_old_backups(backups_dir, existing + [(now, dest)])
    return dest


def _prune_old_backups(backups_dir, backups):
    if len(backups) <= MAX_AUTO_BACKUPS:
        return
    for _dt, path in backups[: len(backups) - MAX_AUTO_BACKUPS]:
        try:
            os.remove(path)
        except OSError:
            pass


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
