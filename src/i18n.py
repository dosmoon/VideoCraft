"""
i18n.py - Lightweight localization layer.

Loads JSON locale tables from src/i18n/<lang>.json and exposes a single
tr(key, **kwargs) function. Language selection is persisted to
<repo>/user_data/settings.json and applied on next startup (Tk labels are
fixed at widget creation time, so switching is restart-based).

Fallback chain for any given key:
    current language table  →  zh source table  →  raw key string
"""

import json
import os

from core import user_data


LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n")
SETTINGS_FILE = user_data.path("settings.json")
# Factory default is English: the first wave of open-source users is expected
# to be English-speaking. Users can switch to Chinese via File > Preferences.
DEFAULT_LANG = "en"
SUPPORTED = ("zh", "en")


def _load_locale(code: str) -> dict:
    """Read src/i18n/<code>.json. Returns {} on miss or corruption."""
    path = os.path.join(LOCALE_DIR, f"{code}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def get_current_lang() -> str:
    """Read language from settings.json. Returns DEFAULT_LANG on miss/corrupt/unsupported."""
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_LANG
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return DEFAULT_LANG
    if not isinstance(data, dict):
        return DEFAULT_LANG
    lang = data.get("language", DEFAULT_LANG)
    return lang if lang in SUPPORTED else DEFAULT_LANG


def set_current_lang(code: str) -> None:
    """Persist language to settings.json. Does NOT apply to the running UI."""
    if code not in SUPPORTED:
        raise ValueError(f"Unsupported language code: {code!r}")
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    data: dict = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                data = existing
        except (json.JSONDecodeError, OSError):
            data = {}
    data["language"] = code
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# Module-level state: loaded once on import. Callers restart the app to switch.
_CURRENT = get_current_lang()
_TABLE = _load_locale(_CURRENT)
_FALLBACK = _load_locale(DEFAULT_LANG) if _CURRENT != DEFAULT_LANG else _TABLE


def tr(key: str, **kwargs) -> str:
    """Translate a key through the fallback chain and optionally interpolate kwargs.

    Example:
        tr('menu.file')                              -> '文件' or 'File'
        tr('log.download.success', filename='a.mp4') -> '下载完成: a.mp4'
    """
    text = _TABLE.get(key)
    if text is None:
        text = _FALLBACK.get(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text
