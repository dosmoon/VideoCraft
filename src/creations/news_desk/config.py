"""News-desk instance config — single in-memory representation.

The on-disk `config.json` has ONE in-memory owner: NewsDeskInstanceConfig.
All reads / writes funnel through `.load()` / `.save()`. No other code
may construct dicts and dump to this file — if a new field needs to
persist, add it to this dataclass.

This is the fix for the "two writers, no shared model" trap we hit when
material_binding wrote bound_material directly while news_desk_tool
overwrote config.json with its own narrow view, wiping the binding.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


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
class NewsDeskInstanceConfig:
    """The complete editable state of one news_desk creation instance.
    Fields mirror config.json one-to-one. Add a field here → it lands
    on disk on next save → it loads back on next open. No other writer
    may touch the file."""
    bound_material: Optional[BoundMaterial] = None
    preset_name: str = ""
    components: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "NewsDeskInstanceConfig":
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

        components = raw.get("components")
        components = ([c for c in components if isinstance(c, dict)]
                       if isinstance(components, list) else [])

        return cls(
            bound_material=bm,
            preset_name=str(raw.get("preset_name", "")),
            components=components,
        )

    def save(self, path: str) -> None:
        """Atomically persist to disk. The single write path for
        config.json — anyone wanting to update state mutates `self` and
        calls save()."""
        out: dict = {
            "preset_name": self.preset_name,
            "components": self.components,
        }
        if self.bound_material is not None:
            out["bound_material"] = self.bound_material.to_dict()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
