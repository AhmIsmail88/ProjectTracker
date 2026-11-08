"""Per-user AI settings; never store credentials in a distributable build.

On Windows the API key is encrypted with DPAPI (CryptProtectData) before it
is written to ai-settings.json: only the same Windows account on the same
machine can decrypt it, so copying the file elsewhere does not leak the key.
Older files holding a plain "api_key" are still read, and are rewritten in
encrypted form on the next save."""
import base64
import json
import logging
import os
import sys
from pathlib import Path
import tempfile
from dotenv import dotenv_values
from app_paths import get_app_dir

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openrouter/free"
_PROTECTED_KEY = "api_key_protected"


def settings_path():
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".config")
    return base / "ProjectTracker" / "ai-settings.json"


# --------------------------------------------------------------------------- #
# Windows DPAPI helpers (no extra dependency: plain ctypes)
# --------------------------------------------------------------------------- #
def _dpapi_available():
    return sys.platform == "win32"


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), "ProjectTracker AI key", None,
                                      None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def protect_secret(text):
    """Returns a base64 string of the DPAPI-encrypted *text*, or None when
    encryption is not available (non-Windows)."""
    if not text or not _dpapi_available():
        return None
    return base64.b64encode(_dpapi(text.encode("utf-8"), protect=True)).decode("ascii")


def unprotect_secret(token):
    return _dpapi(base64.b64decode(token), protect=False).decode("utf-8")


def read_settings():
    # Read files without copying keys into os.environ: removing a setting must
    # not keep a stale credential from a previous request alive in this process.
    portable = dotenv_values(Path(get_app_dir()) / ".env", interpolate=False)
    values = {"api_key": portable.get("OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY", "")),
              "model": portable.get("OPENROUTER_MODEL", os.environ.get("OPENROUTER_MODEL", DEFAULT_MODEL))}
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            values.update({k: v for k, v in saved.items() if k in values and isinstance(v, str)})
            token = saved.get(_PROTECTED_KEY)
            if isinstance(token, str) and token:
                try:
                    values["api_key"] = unprotect_secret(token)
                except (OSError, ValueError):
                    # Another Windows account / machine: the key cannot be
                    # read here and must be entered again.
                    logger.warning("Saved AI key could not be decrypted for this Windows account")
    except (OSError, ValueError):
        pass
    return {"api_key": (values["api_key"] or "").strip(),
            "model": (values["model"] or DEFAULT_MODEL).strip() or DEFAULT_MODEL}


def save_settings(api_key, model):
    values = read_settings()
    values["api_key"] = api_key.strip() or values["api_key"]
    values["model"] = model.strip() or DEFAULT_MODEL
    if not values["api_key"]:
        raise ValueError("Enter an OpenRouter API key.")
    if any(c.isspace() for c in values["api_key"]):
        raise ValueError("The API key must not contain spaces.")
    stored = {"model": values["model"]}
    try:
        token = protect_secret(values["api_key"])
    except OSError:
        token = None
        logger.warning("Could not encrypt the AI key; storing it unencrypted", exc_info=True)
    if token:
        stored[_PROTECTED_KEY] = token
    else:
        stored["api_key"] = values["api_key"]
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(stored, stream)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
