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
    style: Optional[dict] = None          # raw CompositionStyle dict
    # Step 5 (clip-component-migration): ordered list of component
    # instance dicts (each carries kind/name/enabled/... per spec).
    # Empty during 5.0 scaffold; specs land in 5.1+. List order is z-order.
    components: list[dict] = field(default_factory=list)
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

        style = raw.get("style")
        style = style if isinstance(style, dict) else None

        comps_raw = raw.get("components")
        components: list[dict] = []
        if isinstance(comps_raw, list):
            components = [c for c in comps_raw if isinstance(c, dict)]

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
            style=style,
            components=components,
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
            "clips_overrides": {str(k): v for k, v in self.clips_overrides.items()},
            "rendered": list(self.rendered),
        }
        if self.style is not None:
            out["style"] = self.style
        if self.bound_material is not None:
            out["bound_material"] = self.bound_material.to_dict()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
