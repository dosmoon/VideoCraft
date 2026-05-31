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

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_unique_ids(components: list[dict]) -> None:
    """Give every component a unique, non-empty `id` (in place).

    The Tk workbench identified components by list index, so its specs did not
    all carry ids (only subtitle did). The new-arch RPCs address components by
    id (creation.update_component), so every component needs a stable, unique
    one — keep the first occurrence's id, rename later collisions to
    "<id>-2"/"-3"…, and fall back to the kind for a missing/blank id. Faithful
    to clip/config.py::_ensure_unique_ids.
    """
    seen: set[str] = set()
    for c in components:
        base = str(c.get("id") or c.get("kind") or "component")
        new_id = base
        n = 2
        while new_id in seen:
            new_id = f"{base}-{n}"
            n += 1
        c["id"] = new_id
        seen.add(new_id)


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
    # Persisted render-state (single full-source output). Owned by export.py's
    # commit_render/delete_render; mirrors clip's `rendered[]` so the workbench
    # Export tab can show what's on disk.
    rendered: list[dict] = field(default_factory=list)

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
        # Repair any duplicate/missing component ids from the index-based Tk
        # era so the id-based RPCs can address each component unambiguously.
        _ensure_unique_ids(components)

        rendered_raw = raw.get("rendered")
        rendered = ([r for r in rendered_raw if isinstance(r, dict)]
                     if isinstance(rendered_raw, list) else [])

        return cls(
            bound_material=bm,
            preset_name=str(raw.get("preset_name", "")),
            components=components,
            rendered=rendered,
        )

    # ── top-level patch (creation.update_config) ────────────────────────────

    def apply_patch(self, patch: dict) -> None:
        """Mutate from a wire patch. The single owner owns mutation semantics —
        only known top-level fields are honored, so the base RPC layer stays
        creation-agnostic (ADR-0004). news_desk renders the full source at
        source resolution (no reframe geometry), so the only patchable scalar
        today is `preset_name`; component edits go through the *_component
        methods, not here."""
        if not isinstance(patch, dict):
            return
        if "preset_name" in patch:
            self.preset_name = str(patch["preset_name"])

    def bind_material(self, material_type: str, material_instance: str) -> None:
        """Bind this creation to a material instance (ADR-0005). The single
        owner of config.json persists it — `material_binding.py` is UI-only and
        never writes here. Replaces any existing binding (re-bind)."""
        mt = str(material_type).strip()
        mi = str(material_instance).strip()
        if not mt or not mi:
            raise ValueError("material_type and material_instance are required")
        self.bound_material = BoundMaterial(
            type_name=mt, instance_name=mi, bound_at=now_iso())

    # ── component add / remove / reorder (creation.*_component RPCs) ─────────
    # The single owner owns component-list mutation. The base RPC layer calls
    # these generically (getattr), so it stays creation-agnostic (ADR-0004).
    # Faithful to the Tk workbench's add / delete / move-up / move-down, except
    # add appends (end of list = lowest z) per the new-arch convention — the
    # user reorders with ↑↓, same as clip.

    @staticmethod
    def addable_kinds() -> list[dict]:
        """The component kinds offerable in the [+ Add] menu, in registration
        order, each with its `multi_instance` flag (single-instance kinds are
        disabled once present)."""
        from creations.news_desk import component_defs
        return [dict(d) for d in component_defs.ADDABLE]

    def _unique_id(self, base: str) -> str:
        existing = {c.get("id") for c in self.components}
        if base not in existing:
            return base
        n = 2
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    def add_component(self, kind: str, duration: float = 0.0) -> dict:
        """Append a fresh default instance of `kind` (end of list = lowest z).
        Its id is made unique against the current list. Returns the new dict."""
        from creations.news_desk import component_defs
        instance = component_defs.default_instance(kind, duration)
        instance["id"] = self._unique_id(str(instance.get("id") or kind))
        self.components.append(instance)
        return instance

    def remove_component(self, component_id: str) -> None:
        self.components = [
            c for c in self.components if c.get("id") != component_id]

    def move_component(self, component_id: str, delta: int) -> None:
        """Swap the component with the one `delta` positions away (±1). Out-of-
        range moves are ignored."""
        idx = next((i for i, c in enumerate(self.components)
                    if c.get("id") == component_id), None)
        if idx is None:
            return
        target = idx + delta
        if not (0 <= target < len(self.components)):
            return
        comps = self.components
        comps[idx], comps[target] = comps[target], comps[idx]

    # ── presets (creation.*_preset RPCs) ────────────────────────────────────
    # Presets are news_desk-global (a shared store under user_data); applying /
    # saving operates on this instance's components. The owner mediates so the
    # base RPC layer stays creation-agnostic (ADR-0004). presets is imported
    # lazily — it's headless (component_defs, not the retired Tk specs).
    # news_desk has NO output geometry (full-source, no reframe), so a preset
    # is just an ordered component list; apply replaces components wholesale.

    def list_presets(self) -> dict:
        from creations.news_desk import presets
        return {
            "names": presets.list_preset_names(),
            "builtins": list(presets.BUILTIN_PRESETS.keys()),
            "lastUsed": self.preset_name or presets.DEFAULT_PRESET_NAME,
        }

    def apply_preset(self, name: str) -> None:
        """Replace components from the named preset (deep-copied; ids re-uniqued
        with news_desk's kind-based scheme). Presets are clean by construction
        (builtins carry no project content; the save path drops it), so there's
        no pollution to scrub here."""
        from creations.news_desk import presets
        preset = presets.get_preset(name)
        if preset is None:
            raise ValueError(f"unknown preset: {name!r}")
        self.components = copy.deepcopy(preset.components)
        _ensure_unique_ids(self.components)
        self.preset_name = name

    def save_preset(self, name: str) -> None:
        """Upsert the current components as a user preset (builtins protected).
        save_user_preset drops per-project content (srt_path / schedule /
        image_path) so the preset captures visual decisions only."""
        from creations.news_desk import presets
        if presets.is_builtin(name):
            raise ValueError(f"cannot overwrite builtin preset: {name!r}")
        presets.save_user_preset(
            presets.NewsDeskPreset(name=name, components=self.components))
        self.preset_name = name

    def delete_preset(self, name: str) -> None:
        from creations.news_desk import presets
        if presets.is_builtin(name):
            raise ValueError(f"cannot delete builtin preset: {name!r}")
        presets.delete_user_preset(name)

    def save(self, path: str) -> None:
        """Atomically persist to disk. The single write path for
        config.json — anyone wanting to update state mutates `self` and
        calls save()."""
        out: dict = {
            "preset_name": self.preset_name,
            "components": self.components,
            "rendered": list(self.rendered),
        }
        if self.bound_material is not None:
            out["bound_material"] = self.bound_material.to_dict()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
