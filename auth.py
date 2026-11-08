"""auth.py

Accounts helper layer: password hashing + the current sign-in session +
small permission questions. Accounts live in the database (see database.py);
this module deliberately imports nothing from Qt or the database so it stays
easy to unit test and safe to import from anywhere.
"""

import hashlib
import hmac
import os
import sqlite3

PBKDF2_ITERATIONS = 200_000
_HASH_NAME = "sha256"
_SALT_BYTES = 16

_current_user = None
_session_db = None


def hash_password(password, salt_hex=None):
    """Return (salt_hex, hash_hex) for *password* (PBKDF2-HMAC-SHA256)."""
    if salt_hex is None:
        salt_hex = os.urandom(_SALT_BYTES).hex()
    digest = hashlib.pbkdf2_hmac(
        _HASH_NAME, (password or "").encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS
    )
    return salt_hex, digest.hex()


def verify_password(password, salt_hex, expected_hash):
    if not salt_hex or not expected_hash:
        return False
    _, digest = hash_password(password, salt_hex)
    return hmac.compare_digest(digest, expected_hash)


def login(user_row, db):
    """Bind a verified account to the database it authenticated against."""
    global _current_user, _session_db
    _current_user = user_row
    _session_db = db


def logout():
    global _current_user, _session_db
    _current_user = None
    _session_db = None


def current_user():
    """Read current rights; revoked accounts and changed passwords end the session."""
    if _current_user is None or _session_db is None:
        return None
    try:
        user = _session_db.get_user(_current_user["id"])
    except (sqlite3.Error, OSError):
        # If account state cannot be verified, do not retain cached privileges.
        logout()
        return None
    if (user is None or not user["is_active"]
            or user["password_hash"] != _current_user["password_hash"]):
        logout()
        return None
    return user


def session_matches(db):
    """A numeric user id is meaningful only within its authenticated database."""
    return (_session_db is not None and
            os.path.normcase(os.path.realpath(db.db_path)) ==
            os.path.normcase(os.path.realpath(_session_db.db_path)))


def _role():
    user = current_user()
    return user["role"] if user is not None else None


def is_manager(db=None):
    return (db is None or session_matches(db)) and _role() == "manager"


def can_manage_projects():
    return is_manager()


def can_manage_users():
    return is_manager()


def _row_get(row, key):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def can_edit_project(db, project_id):
    """May the current user change data of *project_id*?

    Managers: every project. Engineers: only projects assigned to them.
    Nobody signed in: never.
    """
    if not session_matches(db) or project_id is None:
        return False
    user = current_user()
    if user is None:
        return False
    project = db.get_project(project_id)
    if project is None or _row_get(project, "is_deleted"):
        return False
    return user["role"] == "manager" or _row_get(project, "assigned_user_id") == user["id"]


def can_edit_project_row(project):
    """Same question when the caller already has the project row."""
    if _session_db is None or project is None:
        return False
    return can_edit_project(_session_db, project["id"])


def can_edit_items(db, item_ids):
    """Recheck every target when a bulk editor or attachment dialog saves."""
    for item_id in item_ids:
        item = db.get_item(item_id)
        if item is None or not can_edit_project(db, item["project_id"]):
            return False
    return bool(item_ids)
