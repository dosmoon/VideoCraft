"""Preset persistence for CompositionStyle + HookOutroStyle.

Two stores, two files, one shape:
  - clip_project.json   → named CompositionStyle templates
  - clip_hook_outro.json → named HookOutroStyle sub-templates

JSON layout (both files share it):
    {
      "last_used": "<name>",
      "presets": { "<name>": {...full dict...}, ... }
    }

Strict load semantics: a preset entry that can't be coerced to its
dataclass via the schema-matching rules below is dropped on load and
not re-saved. Legacy ClipProjectConfig v3 entries (flat
`subtitle.{mode,size,color}` keys, no `sub1`/`sub2` sub-dicts) hit this
path and are discarded — by design, no migration shims.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

from core import user_data

from .style import (
    CompositionStyle, HookOutroStyle, OutputGeometry, SubtitleLineStyle,
    SubtitleStyle, WatermarkStyle, default_overlay_styles,
)


PRESET_DIR = user_data.path("presets")
PROJECT_PRESETS_PATH = os.path.join(PRESET_DIR, "clip_project.json")
HOOK_OUTRO_PRESETS_PATH = os.path.join(PRESET_DIR, "clip_hook_outro.json")
BILIBURN_PRESETS_PATH = os.path.join(PRESET_DIR, "bilingual_burn.json")
NEWS_DESK_PRESETS_PATH = os.path.join(PRESET_DIR, "news_desk.json")

BUILTIN_DEFAULT_PROJECT = "Default 9:16"
BUILTIN_DEFAULT_HOOK_OUTRO = "默认 / Default"
BUILTIN_DEFAULT_BILIBURN = "Default"
BUILTIN_DEFAULT_NEWS_DESK = "Default"


# ── Schema-strict dict → dataclass conversion ──────────────────────────────

class PresetSchemaError(ValueError):
    """Raised when a preset dict doesn't match the current schema."""


def _filter_kwargs(d: dict, cls) -> dict:
    """Drop keys that aren't fields of `cls` — silently tolerate top-level
    extras like the legacy `background` field, but pass everything else
    through so type errors surface naturally."""
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


def _line_from_dict(d: dict) -> SubtitleLineStyle:
    if not isinstance(d, dict):
        raise PresetSchemaError("subtitle line entry is not a dict")
    return SubtitleLineStyle(**_filter_kwargs(d, SubtitleLineStyle))


def _subtitle_from_dict(d: dict) -> SubtitleStyle:
    if not isinstance(d, dict):
        raise PresetSchemaError("subtitle entry is not a dict")
    if "sub1" not in d:
        # Legacy v3 schema: flat `mode/size/color`. Not supported.
        raise PresetSchemaError(
            "subtitle dict missing 'sub1' (legacy v3 schema, dropped)")
    return SubtitleStyle(
        sub1=_line_from_dict(d.get("sub1") or {}),
        sub2=_line_from_dict(d.get("sub2") or {}) if d.get("sub2")
             else SubtitleLineStyle(enabled=False),
        stroke_color=str(d.get("stroke_color", "#000000")),
        stroke_width=int(d.get("stroke_width", 2)),
        position=str(d.get("position", "bottom")),
        block_margin_pct=float(d.get("block_margin_pct", 0.08)),
        track_gap_pct=float(d.get("track_gap_pct", 0.12)),
    )


def composition_style_from_dict(d: dict) -> CompositionStyle:
    """Strict converter. Drops top-level extras (e.g. legacy `background`,
    `aspect`, `bgm`) but rejects subtitle entries that don't carry
    sub1/sub2 sub-dicts. Presets missing the `output` block fall back to
    OutputGeometry defaults (reframe 9:16 / 1080)."""
    if not isinstance(d, dict):
        raise PresetSchemaError("preset entry is not a dict")
    return CompositionStyle(
        output=OutputGeometry(**_filter_kwargs(
            d.get("output") or {}, OutputGeometry)),
        encode_preset=str(d.get("encode_preset", "veryfast")),
        subtitle=_subtitle_from_dict(d.get("subtitle") or {}),
        watermark=WatermarkStyle(**_filter_kwargs(
            d.get("watermark") or {}, WatermarkStyle)),
        hook_outro=HookOutroStyle(**_filter_kwargs(
            d.get("hook_outro") or {}, HookOutroStyle)),
        overlay_styles=dict(d.get("overlay_styles") or {}),
    )


def hook_outro_from_dict(d: dict) -> HookOutroStyle:
    if not isinstance(d, dict):
        raise PresetSchemaError("hook_outro preset entry is not a dict")
    return HookOutroStyle(**_filter_kwargs(d, HookOutroStyle))


def composition_style_to_dict(style: CompositionStyle) -> dict:
    return asdict(style)


def hook_outro_to_dict(style: HookOutroStyle) -> dict:
    return asdict(style)


# ── Built-in presets (defined in Python, seeded on first load) ─────────────

BUILTIN_PROJECT_PRESETS: dict[str, CompositionStyle] = {
    BUILTIN_DEFAULT_PROJECT: CompositionStyle(),
    "TikTok / Reels / Shorts (9:16 单语中文)": CompositionStyle(
        output=OutputGeometry(mode="reframe", aspect="9:16"),
        subtitle=SubtitleStyle(
            sub1=SubtitleLineStyle(
                enabled=True, fontsize=28, color="#FFFF00",
                bold=True, is_chinese=True),
            sub2=SubtitleLineStyle(enabled=False),
            stroke_color="#000000", stroke_width=2, position="bottom",
        ),
    ),
    "YouTube 横屏 (16:9 单语中文)": CompositionStyle(
        output=OutputGeometry(mode="reframe", aspect="16:9"),
        subtitle=SubtitleStyle(
            sub1=SubtitleLineStyle(
                enabled=True, fontsize=30, color="#FFFF00",
                bold=True, is_chinese=True),
            sub2=SubtitleLineStyle(enabled=False),
            stroke_color="#000000", stroke_width=2, position="bottom",
        ),
    ),
    "Instagram / 小红书 (1:1 中文)": CompositionStyle(
        output=OutputGeometry(mode="reframe", aspect="1:1"),
        subtitle=SubtitleStyle(
            sub1=SubtitleLineStyle(
                enabled=True, fontsize=26, color="#FFFF00",
                bold=True, is_chinese=True),
            sub2=SubtitleLineStyle(enabled=False),
            stroke_color="#000000", stroke_width=2, position="bottom",
        ),
    ),
}


BUILTIN_HOOK_OUTRO_PRESETS: dict[str, HookOutroStyle] = {
    BUILTIN_DEFAULT_HOOK_OUTRO: HookOutroStyle(),
    "新闻 Banner / News Banner": HookOutroStyle(
        size=56, color="#FFFFFF", bg_color="#C8102E", bg_opacity=85,
        stroke_color="#000000", stroke_width=2, box_padding=18,
        hook_position="top", outro_position="lower-third",
        hook_duration_sec=4.0, outro_duration_sec=5.0,
    ),
    "大字标题 / Big Headline": HookOutroStyle(
        size=84, color="#FFFFFF", bg_color="#000000", bg_opacity=0,
        stroke_color="#000000", stroke_width=8, box_padding=10,
        hook_position="center", outro_position="center",
        hook_duration_sec=2.5, outro_duration_sec=3.5,
    ),
    "问号体 / Question Style": HookOutroStyle(
        size=72, color="#FFEB00", bg_color="#000000", bg_opacity=55,
        stroke_color="#000000", stroke_width=5, box_padding=20,
        hook_position="center", outro_position="lower-third",
        hook_duration_sec=3.0, outro_duration_sec=4.0,
    ),
    "知识小贴士 / Knowledge Tip": HookOutroStyle(
        size=44, color="#FFFFFF", bg_color="#1F2937", bg_opacity=80,
        stroke_color="#000000", stroke_width=2, box_padding=14,
        hook_position="upper-third", outro_position="lower-third",
        hook_duration_sec=4.5, outro_duration_sec=5.0,
    ),
    "下三分之一字幕 / Lower-Third Caption": HookOutroStyle(
        size=42, color="#FFFFFF", bg_color="#000000", bg_opacity=0,
        stroke_color="#000000", stroke_width=4, box_padding=10,
        hook_position="lower-third", outro_position="lower-third",
        hook_duration_sec=5.0, outro_duration_sec=5.0,
    ),
    "CTA 关注三连 / CTA Subscribe": HookOutroStyle(
        size=52, color="#FFFFFF", bg_color="#0F172A", bg_opacity=85,
        stroke_color="#000000", stroke_width=2, box_padding=18,
        hook_position="upper-third", outro_position="bottom",
        hook_duration_sec=2.5, outro_duration_sec=4.5,
    ),
    "极简白底 / Minimal White": HookOutroStyle(
        size=48, color="#111111", bg_color="#FFFFFF", bg_opacity=92,
        stroke_color="#FFFFFF", stroke_width=0, box_padding=14,
        hook_position="center", outro_position="lower-third",
        hook_duration_sec=3.0, outro_duration_sec=4.0,
    ),
    "品牌横幅 / Brand Banner": HookOutroStyle(
        size=50, color="#FFFFFF", bg_color="#1E40AF", bg_opacity=90,
        stroke_color="#000000", stroke_width=1, box_padding=16,
        hook_position="top", outro_position="bottom",
        hook_duration_sec=3.5, outro_duration_sec=4.5,
    ),
}


# ── Generic JSON store I/O ─────────────────────────────────────────────────

def _seed_project_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_PROJECT,
        "presets": {n: composition_style_to_dict(s)
                     for n, s in BUILTIN_PROJECT_PRESETS.items()},
    }


def _seed_hook_outro_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_HOOK_OUTRO,
        "presets": {n: hook_outro_to_dict(s)
                     for n, s in BUILTIN_HOOK_OUTRO_PRESETS.items()},
    }


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


def _validate_project_presets(raw_presets: dict) -> tuple[dict, list[str]]:
    """Walk a raw presets dict, keeping only entries that pass the strict
    schema check. Returns (kept_dict, dropped_names)."""
    kept: dict = {}
    dropped: list[str] = []
    for name, entry in raw_presets.items():
        try:
            style = composition_style_from_dict(entry)
            kept[name] = composition_style_to_dict(style)
        except (PresetSchemaError, TypeError, ValueError):
            dropped.append(name)
    return kept, dropped


def _validate_hook_outro_presets(raw_presets: dict) -> tuple[dict, list[str]]:
    kept: dict = {}
    dropped: list[str] = []
    for name, entry in raw_presets.items():
        try:
            style = hook_outro_from_dict(entry)
            kept[name] = hook_outro_to_dict(style)
        except (PresetSchemaError, TypeError, ValueError):
            dropped.append(name)
    return kept, dropped


# ── Project store API ──────────────────────────────────────────────────────

def load_project_store() -> dict:
    """Load `clip_project.json`. Built-ins are seeded on first run and
    re-injected on every load (so deleting a built-in by hand never
    permanently strands the user). v3-legacy entries are silently dropped."""
    raw = _read_json(PROJECT_PRESETS_PATH)
    if raw is None or "presets" not in raw:
        return _seed_project_store()
    kept, _dropped = _validate_project_presets(raw.get("presets") or {})
    # Re-inject any missing built-ins.
    for name, style in BUILTIN_PROJECT_PRESETS.items():
        if name not in kept:
            kept[name] = composition_style_to_dict(style)
    last_used = raw.get("last_used", BUILTIN_DEFAULT_PROJECT)
    if last_used not in kept:
        last_used = BUILTIN_DEFAULT_PROJECT
    return {"last_used": last_used, "presets": kept}


def save_project_store(store: dict) -> None:
    _write_json(PROJECT_PRESETS_PATH, store)


def list_project_presets(store: dict) -> list[str]:
    """Built-ins first (in declared order), then user presets alphabetically."""
    presets = store.get("presets", {})
    builtin_order = [n for n in BUILTIN_PROJECT_PRESETS if n in presets]
    user_names = sorted(
        (n for n in presets if n not in BUILTIN_PROJECT_PRESETS),
        key=lambda s: s.lower(),
    )
    return builtin_order + user_names


def get_project_preset(store: dict, name: str) -> Optional[CompositionStyle]:
    """Return CompositionStyle for `name`, or None if missing/invalid."""
    raw = store.get("presets", {}).get(name)
    if raw is None:
        return None
    try:
        return composition_style_from_dict(raw)
    except (PresetSchemaError, TypeError, ValueError):
        return None


def upsert_project_preset(store: dict, name: str,
                            style: CompositionStyle) -> None:
    store.setdefault("presets", {})[name] = composition_style_to_dict(style)


def delete_project_preset(store: dict, name: str) -> bool:
    """Delete a user preset. Built-ins are protected."""
    if name in BUILTIN_PROJECT_PRESETS:
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT_PROJECT
    return True


def is_builtin_project(name: str) -> bool:
    return name in BUILTIN_PROJECT_PRESETS


def get_last_used_project(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT_PROJECT)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT_PROJECT
    return name


def set_last_used_project(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name


# ── Hook/Outro store API (parallel shape) ──────────────────────────────────

def load_hook_outro_store() -> dict:
    raw = _read_json(HOOK_OUTRO_PRESETS_PATH)
    if raw is None or "presets" not in raw:
        return _seed_hook_outro_store()
    kept, _dropped = _validate_hook_outro_presets(raw.get("presets") or {})
    for name, style in BUILTIN_HOOK_OUTRO_PRESETS.items():
        if name not in kept:
            kept[name] = hook_outro_to_dict(style)
    last_used = raw.get("last_used", BUILTIN_DEFAULT_HOOK_OUTRO)
    if last_used not in kept:
        last_used = BUILTIN_DEFAULT_HOOK_OUTRO
    return {"last_used": last_used, "presets": kept}


def save_hook_outro_store(store: dict) -> None:
    _write_json(HOOK_OUTRO_PRESETS_PATH, store)


def list_hook_outro_presets(store: dict) -> list[str]:
    presets = store.get("presets", {})
    builtin_order = [n for n in BUILTIN_HOOK_OUTRO_PRESETS if n in presets]
    user_names = sorted(
        (n for n in presets if n not in BUILTIN_HOOK_OUTRO_PRESETS),
        key=lambda s: s.lower(),
    )
    return builtin_order + user_names


def get_hook_outro_preset(store: dict, name: str) -> Optional[HookOutroStyle]:
    raw = store.get("presets", {}).get(name)
    if raw is None:
        return None
    try:
        return hook_outro_from_dict(raw)
    except (PresetSchemaError, TypeError, ValueError):
        return None


def upsert_hook_outro_preset(store: dict, name: str,
                              style: HookOutroStyle) -> None:
    store.setdefault("presets", {})[name] = hook_outro_to_dict(style)


def delete_hook_outro_preset(store: dict, name: str) -> bool:
    if name in BUILTIN_HOOK_OUTRO_PRESETS:
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT_HOOK_OUTRO
    return True


def is_builtin_hook_outro(name: str) -> bool:
    return name in BUILTIN_HOOK_OUTRO_PRESETS


def get_last_used_hook_outro(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT_HOOK_OUTRO)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT_HOOK_OUTRO
    return name


def set_last_used_hook_outro(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name


# ── Bilingual burn store API (passthrough-mode CompositionStyle) ───────────
#
# Bilingual burn produces a derivative whose output canvas matches the
# source exactly (passthrough mode) — distinct enough from the clip
# derivative's reframe-1080 presets that it deserves its own preset file
# and built-ins. Same CompositionStyle schema, just different defaults.

BUILTIN_BILIBURN_PRESETS: dict[str, CompositionStyle] = {
    BUILTIN_DEFAULT_BILIBURN: CompositionStyle(
        output=OutputGeometry(mode="passthrough"),
        subtitle=SubtitleStyle(
            sub1=SubtitleLineStyle(
                enabled=True, fontsize=24, color="#FFFF00",
                bold=True, is_chinese=True,
                auto_max_chars=False, manual_max_chars=20),
            sub2=SubtitleLineStyle(
                enabled=True, fontsize=24, color="#FFFFFF",
                bold=False, is_chinese=False,
                auto_max_chars=False, manual_max_chars=50),
            stroke_color="#000000", stroke_width=2, position="bottom",
        ),
        watermark=WatermarkStyle(
            enabled=True, type="image",
            text="字幕By老猿@OldApeTalk",
            text_fontsize=48, text_color="#00FFFF", text_opacity=60,
            image_path="",          # resolved at apply time from Logo/
            image_scale=0.25, image_opacity=100,
            position="top-right",
        ),
        encode_preset="veryfast",
    ),
}


def _seed_biliburn_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_BILIBURN,
        "presets": {n: composition_style_to_dict(s)
                     for n, s in BUILTIN_BILIBURN_PRESETS.items()},
    }


def load_biliburn_store() -> dict:
    raw = _read_json(BILIBURN_PRESETS_PATH)
    if raw is None or "presets" not in raw:
        return _seed_biliburn_store()
    kept, _dropped = _validate_project_presets(raw.get("presets") or {})
    for name, style in BUILTIN_BILIBURN_PRESETS.items():
        if name not in kept:
            kept[name] = composition_style_to_dict(style)
    last_used = raw.get("last_used", BUILTIN_DEFAULT_BILIBURN)
    if last_used not in kept:
        last_used = BUILTIN_DEFAULT_BILIBURN
    return {"last_used": last_used, "presets": kept}


def save_biliburn_store(store: dict) -> None:
    _write_json(BILIBURN_PRESETS_PATH, store)


def list_biliburn_presets(store: dict) -> list[str]:
    presets = store.get("presets", {})
    builtin_order = [n for n in BUILTIN_BILIBURN_PRESETS if n in presets]
    user_names = sorted(
        (n for n in presets if n not in BUILTIN_BILIBURN_PRESETS),
        key=lambda s: s.lower(),
    )
    return builtin_order + user_names


def get_biliburn_preset(store: dict, name: str) -> Optional[CompositionStyle]:
    raw = store.get("presets", {}).get(name)
    if raw is None:
        return None
    try:
        return composition_style_from_dict(raw)
    except (PresetSchemaError, TypeError, ValueError):
        return None


def upsert_biliburn_preset(store: dict, name: str,
                              style: CompositionStyle) -> None:
    store.setdefault("presets", {})[name] = composition_style_to_dict(style)


def delete_biliburn_preset(store: dict, name: str) -> bool:
    if name in BUILTIN_BILIBURN_PRESETS:
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT_BILIBURN
    return True


def is_builtin_biliburn(name: str) -> bool:
    return name in BUILTIN_BILIBURN_PRESETS


def get_last_used_biliburn(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT_BILIBURN)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT_BILIBURN
    return name


def set_last_used_biliburn(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name


# ── News-desk store API (passthrough + bilingual subs + overlay style lib) ─
#
# news_desk derivative produces a long-form speaker / press-briefing video.
# Defaults: passthrough output (preserve source 1080p/4K), bilingual
# subtitles bottom, news_desk overlay style library seeded with a default
# LowerThirdStyle + TopicStripStyle so newly created instances have
# something to render without requiring the user to pick a class first.

BUILTIN_NEWS_DESK_PRESETS: dict[str, CompositionStyle] = {
    BUILTIN_DEFAULT_NEWS_DESK: CompositionStyle(
        output=OutputGeometry(mode="passthrough"),
        subtitle=SubtitleStyle(
            sub1=SubtitleLineStyle(
                enabled=True, fontsize=24, color="#FFFF00",
                bold=True, is_chinese=True,
                auto_max_chars=False, manual_max_chars=20),
            sub2=SubtitleLineStyle(
                enabled=True, fontsize=22, color="#FFFFFF",
                bold=False, is_chinese=False,
                auto_max_chars=False, manual_max_chars=50),
            stroke_color="#000000", stroke_width=2, position="bottom",
        ),
        watermark=WatermarkStyle(enabled=False),
        encode_preset="veryfast",
        overlay_styles=default_overlay_styles(),
    ),
}


def _seed_news_desk_store() -> dict:
    return {
        "last_used": BUILTIN_DEFAULT_NEWS_DESK,
        "presets": {n: composition_style_to_dict(s)
                     for n, s in BUILTIN_NEWS_DESK_PRESETS.items()},
    }


def load_news_desk_store() -> dict:
    raw = _read_json(NEWS_DESK_PRESETS_PATH)
    if raw is None or "presets" not in raw:
        return _seed_news_desk_store()
    kept, _dropped = _validate_project_presets(raw.get("presets") or {})
    for name, style in BUILTIN_NEWS_DESK_PRESETS.items():
        if name not in kept:
            kept[name] = composition_style_to_dict(style)
    last_used = raw.get("last_used", BUILTIN_DEFAULT_NEWS_DESK)
    if last_used not in kept:
        last_used = BUILTIN_DEFAULT_NEWS_DESK
    return {"last_used": last_used, "presets": kept}


def save_news_desk_store(store: dict) -> None:
    _write_json(NEWS_DESK_PRESETS_PATH, store)


def list_news_desk_presets(store: dict) -> list[str]:
    presets = store.get("presets", {})
    builtin_order = [n for n in BUILTIN_NEWS_DESK_PRESETS if n in presets]
    user_names = sorted(
        (n for n in presets if n not in BUILTIN_NEWS_DESK_PRESETS),
        key=lambda s: s.lower(),
    )
    return builtin_order + user_names


def get_news_desk_preset(store: dict, name: str):
    raw = store.get("presets", {}).get(name)
    if raw is None:
        return None
    try:
        return composition_style_from_dict(raw)
    except (PresetSchemaError, TypeError, ValueError):
        return None


def upsert_news_desk_preset(store: dict, name: str,
                              style: CompositionStyle) -> None:
    store.setdefault("presets", {})[name] = composition_style_to_dict(style)


def delete_news_desk_preset(store: dict, name: str) -> bool:
    if name in BUILTIN_NEWS_DESK_PRESETS:
        return False
    presets = store.get("presets", {})
    if name not in presets:
        return False
    del presets[name]
    if store.get("last_used") == name:
        store["last_used"] = BUILTIN_DEFAULT_NEWS_DESK
    return True


def is_builtin_news_desk(name: str) -> bool:
    return name in BUILTIN_NEWS_DESK_PRESETS


def get_last_used_news_desk(store: dict) -> str:
    name = store.get("last_used", BUILTIN_DEFAULT_NEWS_DESK)
    if name not in store.get("presets", {}):
        return BUILTIN_DEFAULT_NEWS_DESK
    return name


def set_last_used_news_desk(store: dict, name: str) -> None:
    if name in store.get("presets", {}):
        store["last_used"] = name
