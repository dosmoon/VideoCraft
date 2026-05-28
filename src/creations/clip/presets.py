"""Clip preset store — components-based schema.

Replaces the legacy `core/composition/presets.py` (which roundtripped
CompositionStyle dataclasses that no longer match the clip workbench
after the component-migration refactor).

A preset now carries:
  - `components`: list of component instance dicts (same shape as
    `ClipInstanceConfig.components`); applying a preset replaces the
    project's components wholesale.
  - `output`: aspect / short_edge / mode.
  - `encode_preset`: ffmpeg encoder preset name.

On-disk shape (clip_preset.json):
    {
      "last_used": "<name>",
      "presets": {
        "<name>": {
          "components": [{...}, ...],
          "output": {"aspect": "9:16", "short_edge": 1080, "mode": "reframe"},
          "encode_preset": "veryfast"
        },
        ...
      }
    }

Built-ins are seeded on first load and re-injected on every load so
hand-deleting one never permanently strands the user. User presets
sort alphabetically after the built-in declared order.

Schema-strict load: entries that don't carry a list `components` field
or a dict `output` field are dropped silently. Pre-alpha policy: no
migration shim for the legacy CompositionStyle-shaped store. Users
re-save their presets under the new schema.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Optional

from core import user_data

from creations.clip.components import spec_for_kind


PRESET_DIR = user_data.path("presets")
CLIP_PRESETS_PATH = os.path.join(PRESET_DIR, "clip_preset.json")

BUILTIN_DEFAULT = "Default 9:16"


# ── Component-instance helpers (used by BUILTINS) ──────────────────────────

def _default_component(kind: str, **overrides) -> dict:
    """Build a fresh default instance for `kind` and merge `overrides`
    on top. Raises if the kind isn't registered — catches typos in
    BUILTINS at import time rather than at apply time."""
    spec = spec_for_kind(kind)
    if spec is None or spec.default_instance is None:
        raise RuntimeError(f"unknown component kind in preset: {kind}")
    # duration is unused by current default_instance impls; pass a
    # plausible clip length so any future use sees a real number.
    inst = spec.default_instance(60.0)
    inst.update(overrides)
    return inst


# ── Built-in presets ───────────────────────────────────────────────────────

def _builtin_presets() -> dict[str, dict]:
    """Constructed lazily so component registry is populated. Each preset
    is a complete dict ready for the on-disk store."""
    return {
        BUILTIN_DEFAULT: {
            "components": [
                _default_component("clip_subtitle"),
                _default_component("clip_hook_card"),
            ],
            "output": {"aspect": "9:16", "short_edge": 1080,
                        "mode": "reframe"},
            "encode_preset": "veryfast",
        },
        "TikTok / Reels / Shorts (9:16 双语)": {
            "components": [
                # Bilingual stack: Chinese in orange-red on top of English
                # in white. Two components because one subtitle = one
                # language (see components/subtitle.py). If the material
                # lacks one language, that component compiles to nothing.
                _default_component(
                    "clip_subtitle",
                    id="sub_zh",
                    name="字幕(中文)",
                    language="zh",
                    fontsize_pct=60 / 1080.0,
                    color="#FF4500",
                    bold=True,
                    is_chinese=True,
                    position="bottom"),
                _default_component(
                    "clip_subtitle",
                    id="sub_en",
                    name="subtitle(en)",
                    language="en",
                    fontsize_pct=48 / 1080.0,
                    color="#FFFFFF",
                    bold=True,
                    is_chinese=False,
                    position="bottom"),
                _default_component("clip_hook_card", position="upper-third"),
                _default_component("clip_outro_card", position="lower-third"),
            ],
            "output": {"aspect": "9:16", "short_edge": 1080,
                        "mode": "reframe"},
            "encode_preset": "veryfast",
        },
        "YouTube 横屏 (16:9 中文)": {
            "components": [
                _default_component(
                    "clip_subtitle",
                    language="zh",
                    fontsize_pct=54 / 1080.0,
                    color="#FF4500",
                    bold=True,
                    is_chinese=True),
                _default_component("clip_hook_card", position="upper-third"),
                _default_component("clip_outro_card", position="lower-third"),
            ],
            "output": {"aspect": "16:9", "short_edge": 1080,
                        "mode": "reframe"},
            "encode_preset": "veryfast",
        },
        "Instagram / 小红书 (1:1 中文)": {
            "components": [
                _default_component(
                    "clip_subtitle",
                    language="zh",
                    fontsize_pct=54 / 1080.0,
                    color="#FF4500",
                    bold=True,
                    is_chinese=True),
                _default_component("clip_hook_card", position="upper-third"),
            ],
            "output": {"aspect": "1:1", "short_edge": 1080,
                        "mode": "reframe"},
            "encode_preset": "veryfast",
        },
    }


def builtin_names() -> list[str]:
    return list(_builtin_presets().keys())


def is_builtin(name: str) -> bool:
    return name in _builtin_presets()


# ── Schema validation ──────────────────────────────────────────────────────

def _valid_preset_entry(entry: object) -> bool:
    """A preset entry must be a dict with a list `components` and a dict
    `output`. Anything else gets dropped on load."""
    if not isinstance(entry, dict):
        return False
    if not isinstance(entry.get("components"), list):
        return False
    if not isinstance(entry.get("output"), dict):
        return False
    return True


def _validate_presets(raw_presets: dict) -> tuple[dict, list[str]]:
    kept: dict = {}
    dropped: list[str] = []
    for name, entry in raw_presets.items():
        if _valid_preset_entry(entry):
            kept[name] = entry
        else:
            dropped.append(name)
    return kept, dropped


# ── JSON I/O ───────────────────────────────────────────────────────────────

def _read_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _seed_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT,
        "presets": copy.deepcopy(_builtin_presets()),
    }


# ── Public store API ───────────────────────────────────────────────────────

def load_store() -> dict:
    """Read clip_preset.json, validate, and re-inject any missing
    built-ins. First-run / corrupt file produces a freshly seeded store."""
    raw = _read_json(CLIP_PRESETS_PATH)
    if raw is None or "presets" not in raw:
        return _seed_store()
    kept, _dropped = _validate_presets(raw.get("presets") or {})
    builtins = _builtin_presets()
    # Built-ins are code-owned and user-protected (no overwrite / delete in
    # the UI), so the on-disk copy can only ever be a stale snapshot from an
    # earlier seed. Always refresh them to the current definition so preset
    # improvements ship to users who already seeded a store. User presets
    # (any name not in builtins) are left untouched.
    for name, entry in builtins.items():
        kept[name] = copy.deepcopy(entry)
    last_used = raw.get("last_used", BUILTIN_DEFAULT)
    if last_used not in kept:
        last_used = BUILTIN_DEFAULT
    return {"last_used": last_used, "presets": kept}


def save_store(store: dict) -> None:
    _write_json(CLIP_PRESETS_PATH, store)


def list_presets(store: dict) -> list[str]:
    """Built-ins first (in declared order), then user presets sorted
    alphabetically. Matches the legacy ordering convention."""
    presets = store.get("presets", {})
    builtins = _builtin_presets()
    builtin_order = [n for n in builtins if n in presets]
    user_names = sorted(
        (n for n in presets if n not in builtins),
        key=lambda s: s.lower(),
    )
    return builtin_order + user_names


def get_preset(store: dict, name: str) -> Optional[dict]:
    """Return a deep copy of the preset dict, or None if missing."""
    raw = store.get("presets", {}).get(name)
    return copy.deepcopy(raw) if raw is not None else None


def upsert_preset(store: dict, name: str, *,
                    components: list[dict],
                    output_aspect: str,
                    output_short_edge: int,
                    output_mode: str,
                    encode_preset: str) -> None:
    """Insert or overwrite. Deep-copies components so later cfg edits
    don't leak into the saved preset."""
    store.setdefault("presets", {})[name] = {
        "components": copy.deepcopy(components),
        "output": {
            "aspect": str(output_aspect),
            "short_edge": int(output_short_edge),
            "mode": str(output_mode),
        },
        "encode_preset": str(encode_preset),
    }


def delete_preset(store: dict, name: str) -> bool:
    """Delete a user preset. Built-ins are protected."""
    if is_builtin(name):
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT
    return True


def get_last_used(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT
    return name


def set_last_used(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name
