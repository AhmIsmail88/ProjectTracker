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
import tempfile

from app_paths import get_app_dir

logger = logging.getLogger(__name__)

APP_DIR = get_app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.json")


def _load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except json.JSONDecodeError:
        # Keep the damaged file (it still names the data folder) before
        # the next save replaces it, so it can be recovered by hand.
        logger.error("config.json is damaged; keeping a copy as config.json.corrupt")
        try:
            corrupt_copy = CONFIG_PATH + ".corrupt"
            if not os.path.exists(corrupt_copy):
                shutil.copy2(CONFIG_PATH, corrupt_copy)
        except OSError:
            pass
        return {}
    except OSError:
        return {}


def _save_config(cfg):
    # A failed preference write (read-only folder, full disk) must never
    # take the app down - the worst case is that a preference is not
    # remembered for the next run.
    # Written to a temporary file and swapped in atomically: a crash or
    # power cut mid-write must never leave a half-written config.json,
    # which would make the app forget where the data folder is.
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(dir=os.path.dirname(CONFIG_PATH) or ".",
                                         prefix="config.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(temporary, CONFIG_PATH)
        temporary = None
    except OSError:
        logger.warning("Could not write config file at %s", CONFIG_PATH, exc_info=True)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


def load_data_dir():
    """Returns the previously chosen data folder, or None if not set yet
    (or if that folder no longer exists, e.g. moved drive/USB)."""
    data_dir = _load_config().get("data_dir")
    if data_dir and os.path.isdir(data_dir):
        return data_dir
    return None


def configured_data_dir():
    """The data folder recorded in config.json, whether or not it exists
    right now (None only when none was ever chosen). Lets startup tell
    "first run" apart from "the drive holding the data is not connected"."""
    return _load_config().get("data_dir") or None


def save_data_dir(path):
    cfg = _load_config()
    cfg["data_dir"] = path
    _save_config(cfg)


def load_extra_backup_dir():
    """Optional second folder (another drive / cloud-synced folder) that
    every automatic backup is also copied to, or None."""
    return _load_config().get("extra_backup_dir") or None


def save_extra_backup_dir(path):
    cfg = _load_config()
    if path:
        cfg["extra_backup_dir"] = path
    else:
        cfg.pop("extra_backup_dir", None)
    _save_config(cfg)


def db_path_for(data_dir):
    return os.path.join(data_dir, "project_tracker.db")


def attachments_dir_for(data_dir):
    return os.path.join(data_dir, "attachments")


def load_table_layout(table_key):
    """Returns the saved column order/widths (an opaque base64 string)
    for the given table, or None if the user has never rearranged it."""
    return _load_config().get("table_layouts", {}).get(table_key)


def save_table_layout(table_key, state_b64, scale=1.0):
    cfg = _load_config()
    layouts = cfg.get("table_layouts", {})
    layouts[table_key] = state_b64
    cfg["table_layouts"] = layouts
    scales = cfg.get("table_layout_scales", {})
    scales[table_key] = scale
    cfg["table_layout_scales"] = scales
    _save_config(cfg)


def load_table_layout_scale(table_key):
    return _load_config().get("table_layout_scales", {}).get(table_key, 1.0)


def clear_table_layout(table_key):
    cfg = _load_config()
    layouts = cfg.get("table_layouts", {})
    if table_key in layouts:
        del layouts[table_key]
        cfg["table_layouts"] = layouts
        cfg.get("table_layout_scales", {}).pop(table_key, None)
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


def load_items_view():
    return _load_config().get("items_view", "all")


def save_items_view(view):
    cfg = _load_config()
    cfg["items_view"] = view
    _save_config(cfg)

