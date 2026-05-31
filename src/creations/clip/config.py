"""Clip instance config — single in-memory representation.

The on-disk `config.json` for a clip creation has ONE in-memory owner:
ClipInstanceConfig. All reads / writes funnel through `.load()` /
`.save()`. No other code may construct dicts and dump to this file —
if a new field needs to persist, add it to this dataclass.

Mirrors the news_desk pattern (see creations/news_desk/config.py and
[[project_creation_config_owner]]).
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_unique_ids(components: list[dict]) -> None:
    """Give every component a unique, non-empty `id` (in place).

    The Tk workbench identified components by list index, so its specs handed
    out fixed ids ("sub1", "hook", …) and two same-kind components legally
    shared one. The new-arch RPCs identify by id (creation.update_component),
    so collisions must be repaired — keep the first occurrence's id, rename
    later collisions to "<id>-2"/"-3"…. A missing/blank id falls back to the
    kind. Components never reference each other by id (clips_overrides keys on
    candidate index), so re-iding is safe.
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

        out_aspect = str(raw.get("output_aspect", "9:16"))
        try:
            out_short_edge = int(raw.get("output_short_edge", 1080))
        except (TypeError, ValueError):
            out_short_edge = 1080
        out_mode = str(raw.get("output_mode", "reframe"))
        enc_preset = str(raw.get("encode_preset", "medium"))

        comps_raw = raw.get("components")
        components: list[dict] = []
        if isinstance(comps_raw, list):
            components = [c for c in comps_raw if isinstance(c, dict)]
        # Repair any duplicate/missing component ids from the index-based Tk
        # era so the id-based RPCs can address each component unambiguously.
        _ensure_unique_ids(components)

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

    def apply_patch(self, patch: dict) -> None:
        """Mutate from a wire patch (creation.update_config). The single owner
        owns mutation semantics — only known fields are honored, so the base
        RPC layer stays clip-agnostic.

        Top-level fields are set directly. `clips_overrides_merge` deep-merges
        per-candidate overrides ({idx: {key: value}}): a value of None deletes
        the key, and an emptied override is dropped. This is the data path
        behind the Style-tab "apply crop to all" (write crop_rect into every
        candidate's override) and its clear case — faithful to style_panel.py
        ::_on_apply_crop_to_all, which never stored a global crop field.
        """
        if not isinstance(patch, dict):
            return
        for key in ("output_aspect", "output_mode",
                    "encode_preset", "source_subtitle", "preset_name"):
            if key in patch:
                setattr(self, key, str(patch[key]))
        if "output_short_edge" in patch:
            try:
                self.output_short_edge = int(patch["output_short_edge"])
            except (TypeError, ValueError):
                pass
        if isinstance(patch.get("selected_clip_indices"), list):
            self.selected_clip_indices = [
                int(i) for i in patch["selected_clip_indices"]
                if isinstance(i, int)]
        merge = patch.get("clips_overrides_merge")
        if isinstance(merge, dict):
            for raw_idx, fields in merge.items():
                try:
                    idx = int(raw_idx)
                except (TypeError, ValueError):
                    continue
                if not isinstance(fields, dict):
                    continue
                ov = self.clips_overrides.setdefault(idx, {})
                for k, val in fields.items():
                    if val is None:
                        ov.pop(k, None)
                    else:
                        ov[k] = val
                if not ov:
                    self.clips_overrides.pop(idx, None)

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

    # ── component add / remove / reorder (creation.*_component RPCs) ────────
    # The single owner owns component-list mutation, just as it owns
    # apply_patch. The base RPC layer calls these generically (getattr), so it
    # stays clip-agnostic (ADR-0004). Faithful to style_panel.py's
    # _on_add / _on_remove / _on_move_up / _on_move_down.

    @staticmethod
    def addable_kinds() -> list[dict]:
        """The component kinds offerable in the [+ Add] menu, in registration
        order, each with its `multi_instance` flag (single-instance kinds are
        disabled once present). Drives style_panel's _rebuild_add_menu."""
        from creations.clip import component_defs
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
        """Append a fresh default instance of `kind` (end of list = lowest z,
        faithful to _on_add). Its id is made unique against the current list.
        Returns the new component dict."""
        from creations.clip import component_defs
        instance = component_defs.default_instance(kind, duration)
        # A new subtitle inherits the active language so the first add "just
        # works"; the user can switch it in the property panel for bilingual
        # (faithful to style_panel._on_add).
        if kind == "clip_subtitle":
            instance["language"] = self.source_subtitle
        instance["id"] = self._unique_id(str(instance.get("id") or kind))
        self.components.append(instance)
        return instance

    def remove_component(self, component_id: str) -> None:
        self.components = [
            c for c in self.components if c.get("id") != component_id]

    def move_component(self, component_id: str, delta: int) -> None:
        """Swap the component with the one `delta` positions away (±1). Out-of-
        range moves are ignored — faithful to _on_move_up/_on_move_down."""
        idx = next((i for i, c in enumerate(self.components)
                    if c.get("id") == component_id), None)
        if idx is None:
            return
        target = idx + delta
        if not (0 <= target < len(self.components)):
            return
        comps = self.components
        comps[idx], comps[target] = comps[target], comps[idx]

    # ── presets (Style-tab toolbar) ─────────────────────────────────────────
    # Presets are clip-global (a shared store under user_data), but applying /
    # saving operates on this instance's config. The owner mediates so the base
    # RPC layer stays creation-agnostic. Faithful to style_panel.py::_on_preset_*.
    # presets is imported lazily — it's headless now (component_defs, not the
    # tkinter-coupled spec registry), so this is safe in the sidecar.

    @staticmethod
    def list_presets() -> dict:
        from creations.clip import presets
        store = presets.load_store()
        return {
            "names": presets.list_presets(store),
            "builtins": presets.builtin_names(),
            "lastUsed": presets.get_last_used(store),
        }

    def apply_preset(self, name: str) -> None:
        """Replace components + output geometry from the named preset (deep-
        copied; ids re-uniqued since presets carry the specs' fixed ids)."""
        from creations.clip import presets
        store = presets.load_store()
        preset = presets.get_preset(store, name)
        if preset is None:
            raise ValueError(f"unknown preset: {name!r}")
        out = preset.get("output") or {}
        self.output_aspect = str(out.get("aspect", self.output_aspect))
        try:
            self.output_short_edge = int(out.get("short_edge", self.output_short_edge))
        except (TypeError, ValueError):
            pass
        self.output_mode = str(out.get("mode", self.output_mode))
        self.encode_preset = str(preset.get("encode_preset", self.encode_preset))
        self.components = copy.deepcopy(preset.get("components") or [])
        _ensure_unique_ids(self.components)
        self.preset_name = name
        presets.set_last_used(store, name)
        presets.save_store(store)

    def save_preset(self, name: str) -> None:
        """Upsert the current config as a preset (save-as / overwrite). Builtins
        are protected."""
        from creations.clip import presets
        if presets.is_builtin(name):
            raise ValueError(f"cannot overwrite builtin preset: {name!r}")
        store = presets.load_store()
        presets.upsert_preset(
            store, name,
            components=self.components,
            output_aspect=self.output_aspect,
            output_short_edge=int(self.output_short_edge),
            output_mode=self.output_mode,
            encode_preset=self.encode_preset,
        )
        presets.set_last_used(store, name)
        presets.save_store(store)
        self.preset_name = name

    def delete_preset(self, name: str) -> None:
        from creations.clip import presets
        if presets.is_builtin(name):
            raise ValueError(f"cannot delete builtin preset: {name!r}")
        store = presets.load_store()
        presets.delete_preset(store, name)
        presets.save_store(store)

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
