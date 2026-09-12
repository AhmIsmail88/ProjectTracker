"""
config.py
Stores small settings next to the app itself:
- which folder the user chose to keep their actual data
  (project_tracker.db + attachments/) in
- remembered column layouts (order/width) per table, so a table the user
  rearranged stays rearranged the next time the app opens
This file (config.json) is tiny and safe to keep alongside the .exe even
though it is not "the data" itself - it just remembers a few preferences.
"""

import json
import logging
import os
import shutil

from app_paths import get_app_dir

logger = logging.getLogger(__name__)

APP_DIR = get_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_config(cfg):
    # A failed preference write (read-only folder, full disk) must never
    # take the app down - the worst case is that a preference is not
    # remembered for the next run.
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        logger.warning("Could not write config file at %s", CONFIG_PATH, exc_info=True)


def load_data_dir():
    """Returns the previously chosen data folder, or None if not set yet
    (or if that folder no longer exists, e.g. moved drive/USB)."""
    data_dir = _load_config().get("data_dir")
    if data_dir and os.path.isdir(data_dir):
        return data_dir
    return None


def save_data_dir(path):
    cfg = _load_config()
    cfg["data_dir"] = path
    _save_config(cfg)


def db_path_for(data_dir):
    return os.path.join(data_dir, "project_tracker.db")


def attachments_dir_for(data_dir):
    return os.path.join(data_dir, "attachments")


def load_table_layout(table_key):
    """Returns the saved column order/widths (an opaque base64 string)
    for the given table, or None if the user has never rearranged it."""
    return _load_config().get("table_layouts", {}).get(table_key)


def save_table_layout(table_key, state_b64):
    cfg = _load_config()
    layouts = cfg.get("table_layouts", {})
    layouts[table_key] = state_b64
    cfg["table_layouts"] = layouts
    _save_config(cfg)


def clear_table_layout(table_key):
    cfg = _load_config()
    layouts = cfg.get("table_layouts", {})
    if table_key in layouts:
        del layouts[table_key]
        cfg["table_layouts"] = layouts
        _save_config(cfg)


def logo_path():
    """Path of the copied company logo, or None when none is set. The
    logo is stored next to the app itself (branding, not project data) so
    it survives data-folder changes and ships with frozen builds."""
    p = os.path.join(APP_DIR, "company_logo.png")
    return p if os.path.isfile(p) else None


def set_company_logo(source_path):
    """Copies the chosen image next to the app as company_logo.png.
    Returns True on success."""
    dest = os.path.join(APP_DIR, "company_logo.png")
    try:
        shutil.copy2(source_path, dest)
        return True
    except OSError:
        logger.warning("Could not copy company logo", exc_info=True)
        return False


def remove_company_logo():
    try:
        p = os.path.join(APP_DIR, "company_logo.png")
        if os.path.isfile(p):
            os.remove(p)
    except OSError:
        logger.warning("Could not remove company logo", exc_info=True)


def load_last_project_id():
    """The project the user had open when they last used the app, so it
    can be reopened automatically on startup — or None if there isn't
    one yet. The caller must still verify this id actually exists (it
    won't, right after switching to a different/empty data folder)."""
    return _load_config().get("last_project_id")


def save_last_project_id(project_id):
    cfg = _load_config()
    cfg["last_project_id"] = project_id
    _save_config(cfg)

