"""creations/news_desk/presets.py — preset library + user-preset IO."""

from __future__ import annotations

import json
import os
from unittest import mock

from creations.news_desk import presets as nd_presets


# ── Builtins ────────────────────────────────────────────────────────────────

def test_builtins_load_without_disk_access(tmp_path):
    """load_presets() always returns the builtin set even with no
    user_data/presets/news_desk.json on disk."""
    with mock.patch.object(nd_presets, "PRESETS_PATH",
                             str(tmp_path / "nonexistent.json")):
        loaded = nd_presets.load_presets()
    assert set(nd_presets.BUILTIN_PRESETS).issubset(set(loaded))


def test_each_builtin_has_unique_components_layout():
    """The three builtins must differ in shape — if they collapse to the
    same component list, the preset system is back to being a no-op."""
    shapes = {}
    for name, p in nd_presets.BUILTIN_PRESETS.items():
        sig = tuple(sorted((c["kind"], len(c)) for c in p.components))
        shapes[name] = sig
    assert len(set(shapes.values())) == len(shapes), (
        f"builtin presets are too similar: {shapes}")


def test_is_builtin():
    assert nd_presets.is_builtin("新闻发布会")
    assert not nd_presets.is_builtin("用户造的预设")


# ── User-preset IO ──────────────────────────────────────────────────────────

def _patched_path(tmp_path):
    return mock.patch.object(
        nd_presets, "PRESETS_PATH", str(tmp_path / "store.json"))


def test_save_user_preset_persists(tmp_path):
    with _patched_path(tmp_path):
        p = nd_presets.NewsDeskPreset(
            name="A", description="d",
            components=[{"kind": "subtitle", "name": "x"}])
        nd_presets.save_user_preset(p)
        loaded = nd_presets.load_presets()
        assert "A" in loaded
        assert loaded["A"].components[0]["name"] == "x"


def test_save_user_preset_rejects_builtin_name(tmp_path):
    with _patched_path(tmp_path):
        try:
            nd_presets.save_user_preset(
                nd_presets.NewsDeskPreset(name="新闻发布会"))
        except ValueError:
            return
        assert False, "should have raised ValueError"


def test_save_user_preset_overwrites_same_name(tmp_path):
    with _patched_path(tmp_path):
        nd_presets.save_user_preset(nd_presets.NewsDeskPreset(
            name="A", components=[{"kind": "subtitle"}]))
        nd_presets.save_user_preset(nd_presets.NewsDeskPreset(
            name="A", components=[{"kind": "chapter"}, {"kind": "subtitle"}]))
        loaded = nd_presets.load_presets()
        assert len(loaded["A"].components) == 2


def test_delete_user_preset_removes(tmp_path):
    with _patched_path(tmp_path):
        nd_presets.save_user_preset(nd_presets.NewsDeskPreset(name="A"))
        assert nd_presets.delete_user_preset("A") is True
        assert "A" not in nd_presets.load_presets()


def test_delete_user_preset_refuses_builtin(tmp_path):
    with _patched_path(tmp_path):
        assert nd_presets.delete_user_preset("新闻发布会") is False
        assert "新闻发布会" in nd_presets.load_presets()


def test_delete_missing_returns_false(tmp_path):
    with _patched_path(tmp_path):
        assert nd_presets.delete_user_preset("never_existed") is False


def test_list_preset_names_orders_builtins_first(tmp_path):
    """Builtins keep insertion order; user presets are sorted alpha."""
    with _patched_path(tmp_path):
        nd_presets.save_user_preset(nd_presets.NewsDeskPreset(name="zebra"))
        nd_presets.save_user_preset(nd_presets.NewsDeskPreset(name="alpha"))
        names = nd_presets.list_preset_names()
    builtin_count = len(nd_presets.BUILTIN_PRESETS)
    assert names[:builtin_count] == list(nd_presets.BUILTIN_PRESETS)
    assert names[builtin_count:] == ["alpha", "zebra"]


def test_corrupt_store_falls_back_to_builtins(tmp_path):
    """Garbage JSON on disk does not crash — user presets are dropped,
    builtins still present."""
    p = str(tmp_path / "store.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ this is not json")
    with mock.patch.object(nd_presets, "PRESETS_PATH", p):
        loaded = nd_presets.load_presets()
    assert set(nd_presets.BUILTIN_PRESETS).issubset(set(loaded))


# ── fresh_components_for ────────────────────────────────────────────────────

def test_fresh_components_mints_subtitle_ids():
    """Same preset applied twice yields different subtitle ids — no
    id collisions across instances."""
    preset = nd_presets.get_preset("新闻发布会")
    assert preset is not None
    a = nd_presets.fresh_components_for(preset)
    b = nd_presets.fresh_components_for(preset)
    a_ids = [c.get("id") for c in a if c.get("kind") == "subtitle"]
    b_ids = [c.get("id") for c in b if c.get("kind") == "subtitle"]
    assert a_ids and b_ids
    assert not (set(a_ids) & set(b_ids)), (
        f"subtitle ids collide: {a_ids} vs {b_ids}")


def test_fresh_components_clears_subtitle_srt_path():
    """Preset never carries an SRT path forward; consumers must re-import."""
    preset = nd_presets.get_preset("新闻发布会")
    fresh = nd_presets.fresh_components_for(preset)
    for c in fresh:
        if c.get("kind") == "subtitle":
            assert c.get("srt_path") == ""


def test_fresh_components_deepcopy_independence():
    """Mutating one fresh list must not affect the builtin or a sibling."""
    preset = nd_presets.get_preset("新闻发布会")
    a = nd_presets.fresh_components_for(preset)
    b = nd_presets.fresh_components_for(preset)
    a[0]["enabled"] = False
    a[0].setdefault("schedule", []).append({"x": 1})
    assert b[0].get("enabled") is not False
    assert preset.components[0].get("enabled") is not False


def test_fresh_components_strips_chapter_project_content():
    """A preset baked with imported analysis.json (schedule + titles)
    must not leak that content when applied to a new project."""
    preset = nd_presets.NewsDeskPreset(
        name="dirty",
        components=[{
            "kind": "chapter", "name": "章节", "enabled": True,
            "modes": {"start_card": True},
            "schedule": [
                {"start_sec": 0, "end_sec": 60, "title": "项目A的章节",
                 "refined": "项目A的描述", "key_points": ["a", "b"]},
            ],
            "titles": ["项目A候选标题1", "项目A候选标题2"],
            "style": {"start_card": {"title_color": "#FF0000"}},
        }],
    )
    fresh = nd_presets.fresh_components_for(preset)
    ch = fresh[0]
    assert ch["schedule"] == [], "chapter schedule leaked across projects"
    assert ch["titles"] == [], "chapter titles leaked across projects"
    # Style + modes survive (those are preset-worthy)
    assert ch["modes"]["start_card"] is True
    assert ch["style"]["start_card"]["title_color"] == "#FF0000"


def test_fresh_components_strips_image_watermark_path():
    """image_path is an absolute disk path — preset must not carry it."""
    preset = nd_presets.NewsDeskPreset(
        name="dirty",
        components=[{
            "kind": "image_watermark", "name": "台标", "enabled": True,
            "image_path": r"D:\projects\old\logo.png",
            "scale": 0.12, "position": "top-right",
        }],
    )
    fresh = nd_presets.fresh_components_for(preset)
    wm = fresh[0]
    assert wm["image_path"] == "", "image_path leaked across projects"
    assert wm["scale"] == 0.12          # style survives
    assert wm["position"] == "top-right"


# ── save_user_preset strip ──────────────────────────────────────────────────

def test_save_user_preset_strips_project_content(tmp_path):
    """Save-side defence: even if the workbench passes in a polluted
    components list, the preset on disk must be clean — so re-loading
    it later cannot resurrect prior project content."""
    dirty = nd_presets.NewsDeskPreset(
        name="user_preset",
        components=[
            {"kind": "chapter", "name": "章节", "enabled": True,
             "schedule": [{"title": "stale chapter"}],
             "titles": ["stale title"]},
            {"kind": "image_watermark", "name": "logo",
             "image_path": r"D:\old\logo.png"},
            {"kind": "subtitle", "name": "字幕",
             "id": "fixed-id", "srt_path": r"D:\old\zh.srt"},
        ],
    )
    with mock.patch.object(nd_presets, "PRESETS_PATH",
                             str(tmp_path / "news_desk.json")):
        nd_presets.save_user_preset(dirty)
        raw = json.load(open(nd_presets.PRESETS_PATH, encoding="utf-8"))
    saved = raw["user_presets"]["user_preset"]["components"]
    by_kind = {c["kind"]: c for c in saved}
    assert by_kind["chapter"]["schedule"] == []
    assert by_kind["chapter"]["titles"] == []
    assert by_kind["image_watermark"]["image_path"] == ""
    assert by_kind["subtitle"]["srt_path"] == ""
    # Subtitle id must be regenerated, not preserved
    assert by_kind["subtitle"]["id"] != "fixed-id"
