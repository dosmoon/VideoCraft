"""creations/news_desk/config.py — single in-memory owner of config.json."""

from __future__ import annotations

import json
import os

from creations.news_desk.config import (
    BoundMaterial, NewsDeskInstanceConfig, now_iso,
)


# ── load() ──────────────────────────────────────────────────────────────────

def test_load_missing_returns_empty(tmp_path):
    cfg = NewsDeskInstanceConfig.load(str(tmp_path / "absent.json"))
    assert cfg.bound_material is None
    assert cfg.preset_name == ""
    assert cfg.components == []


def test_load_empty_dict_returns_empty(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({}, f)
    cfg = NewsDeskInstanceConfig.load(p)
    assert cfg.bound_material is None


def test_load_full_roundtrip(tmp_path):
    p = str(tmp_path / "config.json")
    src = NewsDeskInstanceConfig(
        bound_material=BoundMaterial(
            type_name="news_video", instance_name="news-1",
            bound_at=now_iso()),
        preset_name="Custom",
        components=[{"kind": "chapter", "id": "abc"}],
    )
    src.save(p)
    loaded = NewsDeskInstanceConfig.load(p)
    assert loaded.bound_material.type_name == "news_video"
    assert loaded.bound_material.instance_name == "news-1"
    assert loaded.preset_name == "Custom"
    assert loaded.components == [{"kind": "chapter", "id": "abc"}]


def test_load_partial_bound_material_treated_as_none(tmp_path):
    """A bound_material entry missing instance_name is not a binding."""
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"bound_material": {"type_name": "news_video"}}, f)
    cfg = NewsDeskInstanceConfig.load(p)
    assert cfg.bound_material is None


def test_load_malformed_json_returns_empty(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not json")
    cfg = NewsDeskInstanceConfig.load(p)
    assert cfg.preset_name == ""
    assert cfg.components == []


def test_load_non_dict_components_falls_back_to_empty(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"components": "not a list"}, f)
    cfg = NewsDeskInstanceConfig.load(p)
    assert cfg.components == []


def test_load_skips_non_dict_component_entries(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"components": [{"kind": "ok"}, "junk", 42]}, f)
    cfg = NewsDeskInstanceConfig.load(p)
    # Non-dict entries are dropped; the surviving component gets a stable id
    # assigned on load (new-arch: the id-based RPCs address each component, so
    # load() repairs id-less Tk-era components — id falls back to the kind).
    assert cfg.components == [{"kind": "ok", "id": "ok"}]


def test_load_assigns_unique_ids(tmp_path):
    """Id-less / colliding components from the index-based Tk era are repaired on
    load so the id-based RPCs can address each one (parallels clip's config)."""
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"components": [
            {"kind": "subtitle", "name": "中文"},
            {"kind": "subtitle", "name": "英文"},
            {"id": "subtitle", "kind": "chapter"},  # collides with the first
        ]}, f)
    cfg = NewsDeskInstanceConfig.load(p)
    ids = [c["id"] for c in cfg.components]
    assert ids == ["subtitle", "subtitle-2", "subtitle-3"]
    assert len(set(ids)) == len(ids)


# ── save() ──────────────────────────────────────────────────────────────────

def test_save_creates_parent_dir(tmp_path):
    p = str(tmp_path / "deep" / "nested" / "config.json")
    NewsDeskInstanceConfig().save(p)
    assert os.path.isfile(p)


def test_save_omits_bound_material_when_none(tmp_path):
    p = str(tmp_path / "config.json")
    NewsDeskInstanceConfig(preset_name="X").save(p)
    data = json.load(open(p, encoding="utf-8"))
    assert "bound_material" not in data
    assert data["preset_name"] == "X"


def test_save_then_load_preserves_binding(tmp_path):
    """Regression: previous architecture had two writers, one of which
    overwrote bound_material on save. Now there's a single writer, so
    a save followed by load must round-trip the binding."""
    p = str(tmp_path / "config.json")
    cfg = NewsDeskInstanceConfig(
        bound_material=BoundMaterial("news_video", "news-1", now_iso()),
        preset_name="P",
        components=[{"kind": "subtitle"}],
    )
    cfg.save(p)

    # Simulate a workbench mutation cycle: load, mutate non-binding
    # fields, save again. The binding must survive.
    reloaded = NewsDeskInstanceConfig.load(p)
    assert reloaded.bound_material is not None
    reloaded.components.append({"kind": "chapter"})
    reloaded.save(p)

    final = NewsDeskInstanceConfig.load(p)
    assert final.bound_material is not None
    assert final.bound_material.instance_name == "news-1"
    assert len(final.components) == 2


# ── BoundMaterial dataclass ─────────────────────────────────────────────────

def test_bound_material_roundtrip():
    bm = BoundMaterial("news_video", "news-1", "2026-05-17T00:00:00+00:00")
    assert BoundMaterial.from_dict(bm.to_dict()) == bm


def test_bound_material_from_dict_coerces_strings():
    bm = BoundMaterial.from_dict(
        {"type_name": "x", "instance_name": "y", "bound_at": None})
    assert bm.bound_at == "None"  # coerced via str()
