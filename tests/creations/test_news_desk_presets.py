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


# ── save_user_preset schema enforcement ─────────────────────────────────────

def test_save_user_preset_drops_project_content(tmp_path):
    """The preset on-disk schema carries style only. Per-project fields
    that a buggy caller might pass in (chapter schedule / titles,
    image_path, srt_path) are absent from the serialized form — not
    cleared-to-empty-string, but key-not-present (the schema rejected
    them outright)."""
    polluted = nd_presets.NewsDeskPreset(
        name="user_preset",
        components=[
            {"kind": "chapter", "name": "章节", "enabled": True,
             "modes": {"start_card": True},
             "schedule": [{"title": "stale"}],
             "titles": ["stale title"]},
            {"kind": "image_watermark", "name": "logo",
             "scale": 0.12,
             "image_path": r"D:\old\logo.png"},
            {"kind": "subtitle", "name": "字幕",
             "fontsize": 28,
             "srt_path": r"D:\old\zh.srt"},
        ],
    )
    with mock.patch.object(nd_presets, "PRESETS_PATH",
                             str(tmp_path / "news_desk.json")):
        nd_presets.save_user_preset(polluted)
        raw = json.load(open(nd_presets.PRESETS_PATH, encoding="utf-8"))
    saved = raw["user_presets"]["user_preset"]["components"]
    by_kind = {c["kind"]: c for c in saved}
    # Schema rejects these — not just emptied, gone
    assert "schedule" not in by_kind["chapter"]
    assert "titles" not in by_kind["chapter"]
    assert "image_path" not in by_kind["image_watermark"]
    assert "srt_path" not in by_kind["subtitle"]
    # Style survives
    assert by_kind["chapter"]["modes"]["start_card"] is True
    assert by_kind["image_watermark"]["scale"] == 0.12
    assert by_kind["subtitle"]["fontsize"] == 28


# ── audit_preset_pollution ──────────────────────────────────────────────────

def test_audit_clean_preset_returns_empty():
    """A preset built fresh has nothing to report."""
    preset = nd_presets.get_preset("新闻发布会")
    assert nd_presets.audit_preset_pollution(preset) == []


def test_audit_detects_chapter_pollution():
    polluted = nd_presets.NewsDeskPreset(
        name="legacy",
        components=[{
            "kind": "chapter", "name": "章节",
            "schedule": [{"x": 1}, {"x": 2}, {"x": 3}],
            "titles": ["t1", "t2"],
        }],
    )
    findings = nd_presets.audit_preset_pollution(polluted)
    assert len(findings) == 2
    assert any("schedule" in f and "3" in f for f in findings)
    assert any("titles" in f and "2" in f for f in findings)


def test_audit_detects_image_watermark_path():
    polluted = nd_presets.NewsDeskPreset(
        name="legacy",
        components=[{
            "kind": "image_watermark", "name": "logo",
            "image_path": r"D:\old\logo.png",
        }],
    )
    findings = nd_presets.audit_preset_pollution(polluted)
    assert len(findings) == 1
    assert "image_path" in findings[0]
    assert "logo.png" in findings[0]


def test_audit_ignores_empty_values():
    """Empty string / empty list = clean; not flagged."""
    preset = nd_presets.NewsDeskPreset(
        name="clean",
        components=[
            {"kind": "chapter", "schedule": [], "titles": []},
            {"kind": "image_watermark", "image_path": ""},
            {"kind": "subtitle", "srt_path": ""},
        ],
    )
    assert nd_presets.audit_preset_pollution(preset) == []


# ── scrub_preset_pollution ──────────────────────────────────────────────────

def test_scrub_drops_project_content_in_memory():
    polluted = nd_presets.NewsDeskPreset(
        name="legacy",
        components=[{
            "kind": "chapter", "name": "章节",
            "modes": {"start_card": True},
            "schedule": [{"x": 1}],
            "titles": ["t"],
        }],
    )
    cleaned = nd_presets.scrub_preset_pollution(polluted)
    ch = cleaned.components[0]
    assert "schedule" not in ch
    assert "titles" not in ch
    assert ch["modes"]["start_card"] is True       # style survives
    # Original untouched (deep-copy semantics)
    assert polluted.components[0]["schedule"] == [{"x": 1}]


# ── fresh_components_for: no silent cleaning ────────────────────────────────

def test_fresh_components_does_not_silently_clean_pollution():
    """Apply path must NOT scrub pollution silently — that path now
    surfaces findings through audit_preset_pollution + user dialog
    instead. fresh_components_for only handles per-instance ids."""
    polluted = nd_presets.NewsDeskPreset(
        name="legacy",
        components=[{
            "kind": "chapter", "name": "章节",
            "schedule": [{"x": 1}],
            "titles": ["t"],
        }],
    )
    fresh = nd_presets.fresh_components_for(polluted)
    ch = fresh[0]
    # Pollution survives — the caller is expected to audit + ask the
    # user before this point.
    assert ch["schedule"] == [{"x": 1}]
    assert ch["titles"] == ["t"]
