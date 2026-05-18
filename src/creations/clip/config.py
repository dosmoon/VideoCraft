"""Clip instance config — single in-memory representation.

The on-disk `config.json` for a clip creation has ONE in-memory owner:
ClipInstanceConfig. All reads / writes funnel through `.load()` /
`.save()`. No other code may construct dicts and dump to this file —
if a new field needs to persist, add it to this dataclass.

Mirrors the news_desk pattern (see creations/news_desk/config.py and
[[project_creation_config_owner]]).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class BoundMaterial:
    """ADR-0005: which material instance this creation consumes."""
    type_name: str
    instance_name: str
    bound_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BoundMaterial":
        return cls(
            type_name=str(d.get("type_name", "")),
            instance_name=str(d.get("instance_name", "")),
            bound_at=str(d.get("bound_at", "")),
        )


@dataclass
class ClipInstanceConfig:
    """Complete editable state of one clip creation instance. Fields
    mirror config.json one-to-one. Add a field here → it lands on disk
    on next save → it loads back on next open. No other writer may
    touch the file."""
    bound_material: Optional[BoundMaterial] = None
    source_subtitle: str = ""             # active language code (e.g. "en")
    selected_clip_indices: list[int] = field(default_factory=list)
    preset_name: str = ""
    # Step 5 (clip-component-migration): ordered list of component
    # instance dicts (each carries kind/name/enabled/... per spec).
    # List order is z-order (top of list = topmost render layer).
    components: list[dict] = field(default_factory=list)
    # Output geometry + encoder preset — flat primitives so the dataclass
    # stays JSON-trivial. clip_tool builds an OutputGeometry on the fly
    # from these fields at render time.
    output_aspect: str = "9:16"
    output_short_edge: int = 1080
    output_mode: str = "reframe"          # "reframe" | "passthrough"
    encode_preset: str = "medium"
    clips_overrides: dict[int, dict] = field(default_factory=dict)
    rendered: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "ClipInstanceConfig":
        """Load from disk. Returns a fresh empty config when the file is
        missing or malformed (pre-alpha — no migration shim)."""
        if not os.path.isfile(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(raw, dict):
            return cls()

        bm: Optional[BoundMaterial] = None
        bound = raw.get("bound_material")
        if (isinstance(bound, dict)
                and bound.get("type_name") and bound.get("instance_name")):
            bm = BoundMaterial.from_dict(bound)

        sel = raw.get("selected_clip_indices")
        selected = ([int(i) for i in sel if isinstance(i, int)]
                     if isinstance(sel, list) else [])

        # One-shot migration of legacy `style` dict — extract output
        # settings + encode_preset; subtitle/watermark/hook_outro are
        # left for clip_tool's startup component seeding to convert.
        legacy_style = raw.get("style")
        legacy_style = (legacy_style if isinstance(legacy_style, dict)
                         else None)
        out_aspect = "9:16"
        out_short_edge = 1080
        out_mode = "reframe"
        enc_preset = "medium"
        if legacy_style:
            out = legacy_style.get("output") or {}
            if isinstance(out, dict):
                out_aspect = str(out.get("aspect", out_aspect))
                try:
                    out_short_edge = int(out.get(
                        "short_edge", out_short_edge))
                except (TypeError, ValueError):
                    pass
                out_mode = str(out.get("mode", out_mode))
            enc_preset = str(legacy_style.get("encode_preset", enc_preset))
        # New-schema flat fields take precedence if present.
        out_aspect = str(raw.get("output_aspect", out_aspect))
        try:
            out_short_edge = int(raw.get("output_short_edge", out_short_edge))
        except (TypeError, ValueError):
            pass
        out_mode = str(raw.get("output_mode", out_mode))
        enc_preset = str(raw.get("encode_preset", enc_preset))

        comps_raw = raw.get("components")
        components: list[dict] = []
        if isinstance(comps_raw, list):
            components = [c for c in comps_raw if isinstance(c, dict)]
        # When components is empty and legacy style had subtitle /
        # watermark / hook_outro, seed components from those templates
        # so existing projects don't lose their layer config.
        if not components and legacy_style:
            components = _seed_components_from_legacy_style(legacy_style)

        ovs_raw = raw.get("clips_overrides")
        overrides: dict[int, dict] = {}
        if isinstance(ovs_raw, dict):
            for k, v in ovs_raw.items():
                if not isinstance(v, dict):
                    continue
                try:
                    overrides[int(k)] = v
                except (TypeError, ValueError):
                    continue

        rendered_raw = raw.get("rendered")
        rendered = ([r for r in rendered_raw if isinstance(r, dict)]
                     if isinstance(rendered_raw, list) else [])

        return cls(
            bound_material=bm,
            source_subtitle=str(raw.get("source_subtitle", "")),
            selected_clip_indices=selected,
            preset_name=str(raw.get("preset_name", "")),
            components=components,
            output_aspect=out_aspect,
            output_short_edge=out_short_edge,
            output_mode=out_mode,
            encode_preset=enc_preset,
            clips_overrides=overrides,
            rendered=rendered,
        )

    def save(self, path: str) -> None:
        """Atomically persist to disk. The single write path for
        config.json — anyone wanting to update state mutates `self` and
        calls save()."""
        out: dict[str, Any] = {
            "source_subtitle": self.source_subtitle,
            "selected_clip_indices": list(self.selected_clip_indices),
            "preset_name": self.preset_name,
            "components": list(self.components),
            "output_aspect": self.output_aspect,
            "output_short_edge": int(self.output_short_edge),
            "output_mode": self.output_mode,
            "encode_preset": self.encode_preset,
            "clips_overrides": {str(k): v for k, v in self.clips_overrides.items()},
            "rendered": list(self.rendered),
        }
        if self.bound_material is not None:
            out["bound_material"] = self.bound_material.to_dict()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)


def _seed_components_from_legacy_style(legacy_style: dict) -> list[dict]:
    """One-shot migration: parse a legacy `style` dict (pre-5.5.c
    CompositionStyle shape) into the matching component instance dicts.
    Used at config.load() when `components` is missing.

    Failures are silent — a malformed legacy style produces an empty
    components list and the user re-adds via the UI. Pre-alpha: lossy
    is acceptable.
    """
    try:
        from core.composition import presets as _presets
        from creations.clip.components import (
            hook_outro as _ho_mod,
            subtitle as _sub_mod,
            watermark as _wm_mod,
        )
        style_obj = _presets.composition_style_from_dict(legacy_style)
    except Exception:
        return []
    out: list[dict] = []
    out.extend(_sub_mod.template_from_style(style_obj))
    out.extend(_wm_mod.template_from_style(style_obj))
    out.extend(_ho_mod.template_from_style(style_obj))
    return out
