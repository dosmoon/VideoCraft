"""News-desk preset storage.

A preset in the components-era is just an ordered component list plus
a name + description — the same shape the workbench already uses.
Applying a preset overwrites the instance's components wholesale.

This module is the SINGLE owner of `user_data/presets/news_desk.json`;
the old core.composition.presets.* news-desk API is retired (it spoke
in CompositionStyle, which the components took over).
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional
from core.io_utils import atomic_write_json

from core import user_data


# ── On-disk store ───────────────────────────────────────────────────────────

PRESETS_PATH = os.path.join(user_data.path("presets"), "news_desk.json")


# ── Preset dataclass ────────────────────────────────────────────────────────

@dataclass
class NewsDeskPreset:
    """One named starting point for a news-desk creation.

    `components` is the ordered list (top→bottom = z) of component
    instance dicts — same shape NewsDeskInstanceConfig.components stores.
    Apply = wholesale replace; never merged.
    """
    name: str                                  # display name + primary key
    description: str = ""                      # 1-2 line picker hint
    components: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NewsDeskPreset":
        name = str(d.get("name", "")).strip()
        if not name:
            raise ValueError("preset is missing a name")
        return cls(
            name=name,
            description=str(d.get("description", "")),
            components=[c for c in (d.get("components") or [])
                        if isinstance(c, dict)],
        )


# ── Builtin starter presets ────────────────────────────────────────────────
# Three intentionally-different templates so picking between them shows
# visible change. Component shapes mirror each component's
# _default_instance() — keep in sync when adding new fields there.

def _chapter_component(*, top_strip: bool, start_card: bool,
                        name: str = "章节") -> dict:
    return {
        "kind": "chapter",
        "name": name,
        "enabled": True,
        "modes": {"top_strip": top_strip, "start_card": start_card},
        "style": {
            "top_strip": {
                "bg_color": "#1E40AF",
                "text_color": "#FFFFFF",
                "fontsize": 26,
            },
            "start_card": {
                "title_color": "#FFFFFF",
                "title_fontsize": 40,
                "body_color": "#E5E7EB",
                "body_fontsize": 22,
                "bg_color": "#0F1B2C",
                "bg_opacity": 55,
                "accent_color": "#DC2626",
                "duration_sec": 6,
            },
        },
        "schedule": [],
    }


def _subtitle_component(*, is_chinese: bool, color: str, name: str,
                          fontsize: int = 28) -> dict:
    return {
        "kind": "subtitle",
        "id": uuid.uuid4().hex[:8],            # replaced on apply, see _fresh_components
        "name": name,
        "enabled": True,
        "srt_path": "",
        "position": "bottom",
        "block_margin_pct": 9,
        "fontsize": fontsize,
        "color": color,
        "is_chinese": is_chinese,
        "stroke_color": "#000000",
        "stroke_width": 2,
        "bg_enabled": True,
        "bg_color": "#000000",
        "bg_opacity": 55,
    }


def _text_watermark_component(*, text: str, name: str,
                                position: str = "bottom-left",
                                fontsize: int = 28) -> dict:
    return {
        "kind": "text_watermark",
        "name": name,
        "enabled": True,
        "text": text,
        "fontsize": fontsize,
        "color": "#FFFFFF",
        "opacity": 70,
        "position": position,
        "margin_x_pct": 2.5,
        "margin_y_pct": 2.5,
    }


def _image_watermark_component(*, name: str = "台标",
                                 position: str = "top-right") -> dict:
    return {
        "kind": "image_watermark",
        "name": name,
        "enabled": True,
        "image_path": "",
        "scale_pct": 15,
        "opacity": 100,
        "position": position,
        "margin_x_pct": 2.5,
        "margin_y_pct": 2.5,
    }


BUILTIN_PRESETS: dict[str, NewsDeskPreset] = {
    "新闻发布会": NewsDeskPreset(
        name="新闻发布会",
        description="顶部章节条 + 起始大卡 + 双字幕 + 台标 + 日期戳",
        components=[
            _chapter_component(top_strip=True, start_card=True),
            _subtitle_component(is_chinese=True, color="#FFFF00",
                                 name="中文字幕"),
            _subtitle_component(is_chinese=False, color="#FFFFFF",
                                 name="英文字幕", fontsize=24),
            _image_watermark_component(),
            _text_watermark_component(text="", name="日期戳",
                                       position="bottom-left", fontsize=26),
        ],
    ),
    "演讲": NewsDeskPreset(
        name="演讲",
        description="顶部章节条 + 单字幕 + 主讲人名牌",
        components=[
            _chapter_component(top_strip=True, start_card=False),
            _subtitle_component(is_chinese=True, color="#FFFF00",
                                 name="字幕", fontsize=32),
            _text_watermark_component(text="", name="主讲人",
                                       position="top-left"),
        ],
    ),
    "极简": NewsDeskPreset(
        name="极简",
        description="纯字幕，无章节卡 / 无水印",
        components=[
            _subtitle_component(is_chinese=True, color="#FFFFFF",
                                 name="字幕"),
        ],
    ),
}

DEFAULT_PRESET_NAME = "新闻发布会"


# ── Store IO ────────────────────────────────────────────────────────────────

def _read_store() -> dict:
    if not os.path.isfile(PRESETS_PATH):
        return {}
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_store(data: dict) -> None:
    atomic_write_json(PRESETS_PATH, data)


def load_presets() -> dict[str, NewsDeskPreset]:
    """Return the merged preset set: builtins (always present) + any user
    presets persisted on disk. User presets with the same name as a
    builtin override the builtin."""
    out: dict[str, NewsDeskPreset] = {}
    for name, p in BUILTIN_PRESETS.items():
        out[name] = NewsDeskPreset(
            name=p.name, description=p.description,
            components=copy.deepcopy(p.components),
        )
    raw = _read_store()
    user_dict = raw.get("user_presets")
    if isinstance(user_dict, dict):
        for name, entry in user_dict.items():
            if not isinstance(entry, dict):
                continue
            try:
                out[str(name)] = NewsDeskPreset.from_dict(
                    {**entry, "name": str(name)})
            except ValueError:
                continue
    return out


def save_user_preset(preset: NewsDeskPreset) -> None:
    """Persist a user-authored preset. Overwrites any existing user
    preset with the same name; builtins are not touched (they live in
    code, not on disk).

    Per-project content (chapter schedule / titles, image_watermark
    image_path, subtitle id+srt_path) is stripped before writing — the
    preset captures the visual decisions, not the current project's
    imported data."""
    if is_builtin(preset.name):
        raise ValueError(
            f"cannot overwrite builtin preset '{preset.name}'")
    clean = NewsDeskPreset(
        name=preset.name,
        description=preset.description,
        components=_serialize_components_for_preset(preset.components),
    )
    raw = _read_store()
    user_dict = raw.get("user_presets")
    if not isinstance(user_dict, dict):
        user_dict = {}
    user_dict[clean.name] = clean.to_dict()
    raw["user_presets"] = user_dict
    _write_store(raw)


def delete_user_preset(name: str) -> bool:
    """Remove a user preset. Returns False for builtins or missing
    names (callers don't act on the return)."""
    if is_builtin(name):
        return False
    raw = _read_store()
    user_dict = raw.get("user_presets")
    if not isinstance(user_dict, dict) or name not in user_dict:
        return False
    del user_dict[name]
    raw["user_presets"] = user_dict
    _write_store(raw)
    return True


def is_builtin(name: str) -> bool:
    return name in BUILTIN_PRESETS


def list_preset_names() -> list[str]:
    """Builtin order first (insertion order), then user presets alphabetical."""
    presets = load_presets()
    builtin_in_order = [n for n in BUILTIN_PRESETS if n in presets]
    user_alpha = sorted(
        (n for n in presets if n not in BUILTIN_PRESETS),
        key=lambda s: s.lower(),
    )
    return builtin_in_order + user_alpha


def get_preset(name: str) -> Optional[NewsDeskPreset]:
    return load_presets().get(name)


# ── Apply helpers ───────────────────────────────────────────────────────────

# Per-kind fields that a preset, by definition, must not carry — these
# describe the active *project's* imported data, not a reusable visual
# decision. The save path drops them on serialization (they are not
# part of a preset's schema); the apply path uses the same map to AUDIT
# disk presets and surface findings to the user instead of silently
# fixing them.
_PROJECT_CONTENT_KEYS: dict[str, tuple[str, ...]] = {
    "subtitle":        ("srt_path",),        # id is regenerated separately
    "chapter":         ("schedule", "titles"),
    "image_watermark": ("image_path",),
    # text_watermark intentionally absent — text + style are preset-worthy
}


def _serialize_components_for_preset(components: list[dict]) -> list[dict]:
    """Produce the on-disk representation of a preset's components.

    A preset describes a *reusable visual configuration*, so its
    serialized form contains style and layout only — never per-project
    imported data (chapter schedules, SRT paths, local watermark files).
    Dropping those fields here is the preset schema talking, not a
    defensive strip pass.
    """
    out = copy.deepcopy(components)
    for c in out:
        for k in _PROJECT_CONTENT_KEYS.get(c.get("kind"), ()):
            c.pop(k, None)
    return out


def audit_preset_pollution(preset: NewsDeskPreset) -> list[str]:
    """Inspect a preset's components for fields that should not exist
    in any preset — left behind by old code paths that serialized
    everything. Returns a list of human-readable findings. Empty list
    = preset is clean.

    Apply-side surfaces these as a confirmation dialog ("this preset
    still holds X, Y, Z from a prior project — clear and apply?"). It
    is NOT a silent auto-fix; the user decides.
    """
    findings: list[str] = []
    for c in preset.components:
        kind = c.get("kind")
        label = c.get("name") or kind or "?"
        for key in _PROJECT_CONTENT_KEYS.get(kind, ()):
            v = c.get(key)
            present = (v not in (None, "", [], {}, ()))
            if not present:
                continue
            if isinstance(v, list):
                findings.append(
                    f"{label}（{kind}）.{key}: {len(v)} 条遗留数据")
            else:
                findings.append(f"{label}（{kind}）.{key}: {v!r}")
    return findings


def scrub_preset_pollution(preset: NewsDeskPreset) -> NewsDeskPreset:
    """Drop all project-content fields from a preset (in-memory). Used
    by the apply path after the user confirms the audit dialog.
    Returns a NEW preset; caller is responsible for persisting if
    desired."""
    return NewsDeskPreset(
        name=preset.name,
        description=preset.description,
        components=_serialize_components_for_preset(preset.components),
    )


def fresh_components_for(preset: NewsDeskPreset) -> list[dict]:
    """Apply-side: deep-copy preset.components and regenerate per-INSTANCE
    identifiers (subtitle id) so two instances applied from the same
    preset don't share state.

    Does NOT silently clean project-content pollution — callers must
    audit_preset_pollution() up front and route findings through the UI.
    """
    out = copy.deepcopy(preset.components)
    for c in out:
        if c.get("kind") == "subtitle":
            c["id"] = uuid.uuid4().hex[:8]
    return out
