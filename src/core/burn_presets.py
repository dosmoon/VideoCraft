"""
core/burn_presets.py - Subtitle burn preset store.

Pure persistence layer for named parameter presets — domain data, not UI
data, so this lives in core. Both consumers (the legacy subtitle_tool UI
and the project-workbench step4_burn) read/write the same store, so a
preset tuned in one is immediately visible in the other. Storage lives
under the user's home directory alongside recent.json (see project.py),
not in the project folder, because presets are cross-project user
preferences.
"""

import json
import os
from typing import Optional


PRESET_DIR = os.path.join(os.path.expanduser("~"), ".videocraft", "presets")
PRESET_FILE = os.path.join(PRESET_DIR, "subtitle_burn.json")
BUILTIN_DEFAULT_NAME = "Default"


# Built-in baseline. Mirrors the hard-coded values in
# SubtitleToolApp.__init__ so the Default preset reproduces the
# pre-feature behavior exactly. watermark_date is intentionally
# excluded (it resets to "today" on every open).
BUILTIN_DEFAULT_PARAMS: dict = {
    "watermark_text":          "字幕By老猿@OldApeTalk",
    "watermark_txt_alpha":     60.0,
    "watermark_color":         "#00ffff",
    "watermark_fontsize":      48,
    "watermark_show":          True,
    "watermark_show_date":     False,
    "watermark_date_color":    "#505050",
    "watermark_date_fontsize": 36,
    "watermark_date_alpha":    80.0,
    "watermark_type":          "image",
    "watermark_img_path":      "",   # empty → resolve via _default_watermark_path()
    "watermark_img_scale":     0.25,
    "watermark_img_alpha":     100.0,

    "sub1_fontsize":   24,
    "sub1_color":      "#FFFF00",
    "sub1_show":       True,
    "sub2_fontsize":   24,
    "sub2_color":      "#FFFFFF",
    "sub2_show":       True,

    "split_sub1":        True,
    "sub1_max_chars":    20,
    "sub1_is_chinese":   True,
    "split_sub2":        True,
    "sub2_max_chars":    50,
    "sub2_is_chinese":   False,

    "orientation":    "horizontal",
    "encode_preset":  "veryfast",
    "auto_output":    True,
}


def _empty_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_NAME,
        "presets": {BUILTIN_DEFAULT_NAME: dict(BUILTIN_DEFAULT_PARAMS)},
    }


def load_store() -> dict:
    """Read the preset file. Return a fresh empty store on miss or corruption."""
    if not os.path.exists(PRESET_FILE):
        return _empty_store()
    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_store()

    if not isinstance(data, dict) or "presets" not in data:
        return _empty_store()

    # Ensure Default always exists and is never stale.
    data.setdefault("last_used", BUILTIN_DEFAULT_NAME)
    presets = data.get("presets") or {}
    if BUILTIN_DEFAULT_NAME not in presets:
        presets[BUILTIN_DEFAULT_NAME] = dict(BUILTIN_DEFAULT_PARAMS)
    data["presets"] = presets
    return data


def save_store(store: dict) -> None:
    os.makedirs(PRESET_DIR, exist_ok=True)
    with open(PRESET_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def list_preset_names(store: dict) -> list:
    """Return preset names with Default pinned at the top."""
    names = list(store.get("presets", {}).keys())
    if BUILTIN_DEFAULT_NAME in names:
        names.remove(BUILTIN_DEFAULT_NAME)
    names.sort(key=lambda s: s.lower())
    return [BUILTIN_DEFAULT_NAME] + names


def get_preset(store: dict, name: str) -> Optional[dict]:
    preset = store.get("presets", {}).get(name)
    return dict(preset) if preset is not None else None


def upsert_preset(store: dict, name: str, params: dict) -> None:
    store.setdefault("presets", {})[name] = dict(params)


def delete_preset(store: dict, name: str) -> bool:
    """Delete a user preset. Default is protected and cannot be removed."""
    if name == BUILTIN_DEFAULT_NAME:
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT_NAME
    return True


def set_last_used(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name


def get_last_used(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT_NAME)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT_NAME
    return name
