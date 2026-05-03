"""
core/clip_hook_outro_presets.py — Hook / Outro style template store.

Persistence for named HookOutroStyle templates. Mirrors clip_presets.py
in shape; lives in its own file so users can manage hook/outro looks
independently of the broader clip-project preset (aspect, subtitle, etc.).

Storage:  user_data/presets/clip_hook_outro.json
Format:
    {
      "last_used": "新闻 Banner",
      "presets": {
        "<name>": { ... full HookOutroStyle dict ... },
      }
    }

Built-ins are seeded on first load and re-injected if missing on
subsequent loads. Users can override built-ins in the file but they
get re-seeded next load — so a clean baseline is always reachable.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from core import user_data
from core.program.clip import HookOutroStyle


PRESET_DIR = user_data.path("presets")
PRESET_FILE = os.path.join(PRESET_DIR, "clip_hook_outro.json")
BUILTIN_DEFAULT_NAME = "默认 / Default"


def _style_with(**overrides) -> dict:
    """Build a HookOutroStyle dict with field overrides applied."""
    s = HookOutroStyle()
    for k, v in overrides.items():
        setattr(s, k, v)
    return asdict(s)


# Built-in templates. Each one represents a distinct visual archetype
# from the short-video industry playbook. Tuned for 9:16 first; 16:9
# users may need to bump fontsize but the position presets translate
# correctly to either aspect.
BUILTIN_PRESETS: dict[str, dict] = {
    BUILTIN_DEFAULT_NAME: _style_with(),
    "新闻 Banner / News Banner": _style_with(
        font="Microsoft YaHei", size=56,
        color="#FFFFFF", bg_color="#C8102E", bg_opacity=85,
        stroke_color="#000000", stroke_width=2, box_padding=18,
        hook_position="top", outro_position="lower-third",
        hook_duration_sec=4.0, outro_duration_sec=5.0,
    ),
    "大字标题 / Big Headline": _style_with(
        font="Microsoft YaHei", size=84,
        color="#FFFFFF", bg_color="#000000", bg_opacity=0,
        stroke_color="#000000", stroke_width=8, box_padding=10,
        hook_position="center", outro_position="center",
        hook_duration_sec=2.5, outro_duration_sec=3.5,
    ),
    "问号体 / Question Style": _style_with(
        font="Microsoft YaHei", size=72,
        color="#FFEB00", bg_color="#000000", bg_opacity=55,
        stroke_color="#000000", stroke_width=5, box_padding=20,
        hook_position="center", outro_position="lower-third",
        hook_duration_sec=3.0, outro_duration_sec=4.0,
    ),
    "知识小贴士 / Knowledge Tip": _style_with(
        font="Microsoft YaHei", size=44,
        color="#FFFFFF", bg_color="#1F2937", bg_opacity=80,
        stroke_color="#000000", stroke_width=2, box_padding=14,
        hook_position="upper-third", outro_position="lower-third",
        hook_duration_sec=4.5, outro_duration_sec=5.0,
    ),
    "下三分之一字幕 / Lower-Third Caption": _style_with(
        font="Microsoft YaHei", size=42,
        color="#FFFFFF", bg_color="#000000", bg_opacity=0,
        stroke_color="#000000", stroke_width=4, box_padding=10,
        hook_position="lower-third", outro_position="lower-third",
        hook_duration_sec=5.0, outro_duration_sec=5.0,
    ),
    "CTA 关注三连 / CTA Subscribe": _style_with(
        font="Microsoft YaHei", size=52,
        color="#FFFFFF", bg_color="#0F172A", bg_opacity=85,
        stroke_color="#000000", stroke_width=2, box_padding=18,
        hook_position="upper-third", outro_position="bottom",
        hook_duration_sec=2.5, outro_duration_sec=4.5,
    ),
    "极简白底 / Minimal White": _style_with(
        font="Microsoft YaHei", size=48,
        color="#111111", bg_color="#FFFFFF", bg_opacity=92,
        stroke_color="#FFFFFF", stroke_width=0, box_padding=14,
        hook_position="center", outro_position="lower-third",
        hook_duration_sec=3.0, outro_duration_sec=4.0,
    ),
    "品牌横幅 / Brand Banner": _style_with(
        font="Microsoft YaHei", size=50,
        color="#FFFFFF", bg_color="#1E40AF", bg_opacity=90,
        stroke_color="#000000", stroke_width=1, box_padding=16,
        hook_position="top", outro_position="bottom",
        hook_duration_sec=3.5, outro_duration_sec=4.5,
    ),
}


def _empty_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_NAME,
        "presets": {name: dict(p) for name, p in BUILTIN_PRESETS.items()},
    }


def load_store() -> dict:
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
