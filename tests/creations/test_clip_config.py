"""creations/clip/config.py — single in-memory owner of config.json."""

from __future__ import annotations

import json
import os

from creations.clip.config import (
    BoundMaterial, ClipInstanceConfig, now_iso,
)


# ── load() ──────────────────────────────────────────────────────────────────

def test_load_missing_returns_empty(tmp_path):
    cfg = ClipInstanceConfig.load(str(tmp_path / "absent.json"))
    assert cfg.bound_material is None
    assert cfg.preset_name == ""
    assert cfg.source_subtitle == ""
    assert cfg.selected_clip_indices == []
    assert cfg.style is None
    assert cfg.clips_overrides == {}
    assert cfg.rendered == []


def test_load_empty_dict_returns_empty(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({}, f)
    cfg = ClipInstanceConfig.load(p)
    assert cfg.bound_material is None


def test_load_full_roundtrip(tmp_path):
    p = str(tmp_path / "config.json")
    src = ClipInstanceConfig(
        bound_material=BoundMaterial(
            type_name="news_video", instance_name="news-1",
            bound_at=now_iso()),
        source_subtitle="en",
        selected_clip_indices=[0, 2, 5],
        preset_name="MyPreset",
        style={"output": {"aspect": "9:16"}},
        clips_overrides={3: {"hook": "boom"}},
        rendered=[{"file": "clip01.mp4", "src_idx": 0}],
    )
    src.save(p)
    loaded = ClipInstanceConfig.load(p)
    assert loaded.bound_material.type_name == "news_video"
    assert loaded.bound_material.instance_name == "news-1"
    assert loaded.source_subtitle == "en"
    assert loaded.selected_clip_indices == [0, 2, 5]
    assert loaded.preset_name == "MyPreset"
    assert loaded.style == {"output": {"aspect": "9:16"}}
    assert loaded.clips_overrides == {3: {"hook": "boom"}}
    assert loaded.rendered == [{"file": "clip01.mp4", "src_idx": 0}]


def test_load_partial_bound_material_treated_as_none(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"bound_material": {"type_name": "news_video"}}, f)
    cfg = ClipInstanceConfig.load(p)
    assert cfg.bound_material is None


def test_load_malformed_json_returns_empty(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        f.write("{ not json")
    cfg = ClipInstanceConfig.load(p)
    assert cfg.preset_name == ""
    assert cfg.bound_material is None


def test_load_coerces_clips_overrides_keys_to_int(tmp_path):
    """JSON object keys are strings; load() must reconstruct int keys."""
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"clips_overrides": {"3": {"hook": "x"},
                                          "7": {"title": "y"}}}, f)
    cfg = ClipInstanceConfig.load(p)
    assert cfg.clips_overrides == {3: {"hook": "x"}, 7: {"title": "y"}}


def test_load_skips_non_dict_override_values(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"clips_overrides": {"1": {"k": "v"}, "2": "junk"}}, f)
    cfg = ClipInstanceConfig.load(p)
    assert cfg.clips_overrides == {1: {"k": "v"}}


def test_load_skips_non_dict_rendered_entries(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rendered": [{"file": "ok.mp4"}, "junk", 42]}, f)
    cfg = ClipInstanceConfig.load(p)
    assert cfg.rendered == [{"file": "ok.mp4"}]


# ── save() ──────────────────────────────────────────────────────────────────

def test_save_creates_parent_dir(tmp_path):
    p = str(tmp_path / "deep" / "nested" / "config.json")
    ClipInstanceConfig().save(p)
    assert os.path.isfile(p)


def test_save_omits_bound_material_when_none(tmp_path):
    p = str(tmp_path / "config.json")
    ClipInstanceConfig(preset_name="X").save(p)
    data = json.load(open(p, encoding="utf-8"))
    assert "bound_material" not in data


def test_save_then_load_preserves_binding(tmp_path):
    """Regression: a save→load→mutate→save cycle must round-trip the
    binding. This is the failure mode the news_desk refactor exposed
    (two writers), now precluded by the single-owner pattern."""
    p = str(tmp_path / "config.json")
    cfg = ClipInstanceConfig(
        bound_material=BoundMaterial("news_video", "news-1", now_iso()),
        preset_name="P",
        selected_clip_indices=[0],
    )
    cfg.save(p)

    reloaded = ClipInstanceConfig.load(p)
    assert reloaded.bound_material is not None
    reloaded.selected_clip_indices = [0, 1, 2]
    reloaded.save(p)

    final = ClipInstanceConfig.load(p)
    assert final.bound_material is not None
    assert final.bound_material.instance_name == "news-1"
    assert final.selected_clip_indices == [0, 1, 2]


def test_save_clips_overrides_uses_string_keys_on_disk(tmp_path):
    """JSON object keys must be strings — verify the writer coerces."""
    p = str(tmp_path / "config.json")
    ClipInstanceConfig(clips_overrides={3: {"hook": "x"}}).save(p)
    data = json.load(open(p, encoding="utf-8"))
    assert data["clips_overrides"] == {"3": {"hook": "x"}}


# ── BoundMaterial dataclass ─────────────────────────────────────────────────

def test_bound_material_roundtrip():
    bm = BoundMaterial("news_video", "news-1", "2026-05-17T00:00:00+00:00")
    assert BoundMaterial.from_dict(bm.to_dict()) == bm
