"""
core/clip_presets.py - Clip-project output-style preset store.

Persistence for named ClipProjectConfig templates. Mirrors burn_presets.py
in shape and lifecycle so anyone familiar with one can read the other.

Storage:  user_data/presets/clip_project.json
Format:
    {
      "last_used": "Default",
      "presets": {
        "Default": { ... full ClipProjectConfig dict ... },
        "<user name>": { ... }
      }
    }

Built-in presets (Default + a handful of common platform shapes) are
seeded on first load and re-injected if missing on subsequent loads, so
the user can always get back to a clean baseline. User-created presets
live alongside built-ins and are freely editable / deletable; built-ins
can be overwritten in the file but get re-seeded on next load.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from core import user_data
from core.program.clip import ClipProjectConfig


PRESET_DIR = user_data.path("presets")
PRESET_FILE = os.path.join(PRESET_DIR, "clip_project.json")
BUILTIN_DEFAULT_NAME = "Default"


def _config_with(**overrides) -> dict:
    """Build a ClipProjectConfig dict with dotted-key overrides applied.

    Example:
        _config_with(aspect="16:9", subtitle__mode="bilingual")
        _config_with(**{"subtitle.size": 36})
    """
    cfg = ClipProjectConfig()
    for k, v in overrides.items():
        # Support both `subtitle.size` (string key) and `subtitle__size`
        # (Python kw form, as a convenience).
        path = k.replace("__", ".").split(".")
        if len(path) == 1:
            setattr(cfg, path[0], v)
        else:
            section = getattr(cfg, path[0])
            for p in path[1:-1]:
                section = getattr(section, p)
            setattr(section, path[-1], v)
    return asdict(cfg)


# Built-in presets. Default = pure ClipProjectConfig() defaults; the rest
# tweak only the fields that make sense to vary per platform shape.
# Watermark / Hook-Outro card / BGM stay at defaults — those are
# user-brand-specific, not platform-specific.
BUILTIN_PRESETS: dict[str, dict] = {
    BUILTIN_DEFAULT_NAME: _config_with(),
    "TikTok / Reels / Shorts (9:16 单语)": _config_with(**{
        "aspect": "9:16",
        "subtitle.mode": "single",
        "subtitle.size": 36,
        "subtitle.position": "bottom",
    }),
    "TikTok / Reels / Shorts (9:16 双语)": _config_with(**{
        "aspect": "9:16",
        "subtitle.mode": "bilingual",
        "subtitle.size": 32,
        "subtitle.position": "bottom",
    }),
    "YouTube 横屏 (16:9 单语)": _config_with(**{
        "aspect": "16:9",
        "subtitle.mode": "single",
        "subtitle.size": 36,
        "subtitle.position": "bottom",
    }),
    "B站横屏 (16:9 双语)": _config_with(**{
        "aspect": "16:9",
        "subtitle.mode": "bilingual",
        "subtitle.size": 32,
        "subtitle.position": "bottom",
    }),
    "Instagram / 小红书 (1:1)": _config_with(**{
        "aspect": "1:1",
        "subtitle.mode": "single",
        "subtitle.size": 32,
        "subtitle.position": "bottom",
    }),
}


def _empty_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_NAME,
        "presets": {name: dict(p) for name, p in BUILTIN_PRESETS.items()},
    }


def load_store() -> dict:
    """Read the preset file. Always returns a usable store; built-ins are
    re-injected if any are missing (so deleting a built-in by hand from
    the file doesn't permanently strand the user)."""
    if not os.path.exists(PRESET_FILE):
        return _empty_store()
    try:
        with open(PRESET_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_store()
    if not isinstance(data, dict) or "presets" not in data:
        return _empty_store()
    presets = data.get("presets") or {}
    for name, preset in BUILTIN_PRESETS.items():
        if name not in presets:
            presets[name] = dict(preset)
    data["presets"] = presets
    data.setdefault("last_used", BUILTIN_DEFAULT_NAME)
    return data


def save_store(store: dict) -> None:
    os.makedirs(PRESET_DIR, exist_ok=True)
    with open(PRESET_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def list_preset_names(store: dict) -> list[str]:
    """Return preset names with built-ins first (in their declared order),
    user-created presets after, sorted alphabetically."""
    presets = store.get("presets", {})
    builtin_order = [n for n in BUILTIN_PRESETS.keys() if n in presets]
    user_names = sorted(
        (n for n in presets.keys() if n not in BUILTIN_PRESETS),
        key=lambda s: s.lower(),
    )
    return builtin_order + user_names


def get_preset(store: dict, name: str) -> Optional[dict]:
    preset = store.get("presets", {}).get(name)
    return dict(preset) if preset is not None else None


def upsert_preset(store: dict, name: str, params: dict) -> None:
    store.setdefault("presets", {})[name] = dict(params)


def delete_preset(store: dict, name: str) -> bool:
    """Delete a user preset. Built-ins are protected and cannot be deleted."""
    if name in BUILTIN_PRESETS:
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT_NAME
    return True


def is_builtin(name: str) -> bool:
    return name in BUILTIN_PRESETS


def set_last_used(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name


def get_last_used(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT_NAME)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT_NAME
    return name
