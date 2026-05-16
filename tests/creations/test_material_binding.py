"""creations/material_binding.py — bound_material config IO + get_or_bind.

The picker dialog itself requires Tk; we test the file-IO + recall
path only. The dialog flow is exercised manually."""

from __future__ import annotations

import json
import os

from creations.material_binding import (
    read_bound_material, write_bound_material,
)


def test_read_bound_material_missing_returns_none(tmp_path):
    path = str(tmp_path / "config.json")
    assert read_bound_material(path) is None


def test_read_bound_material_empty_config_returns_none(tmp_path):
    path = str(tmp_path / "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({}, f)
    assert read_bound_material(path) is None


def test_write_bound_material_persists(tmp_path):
    path = str(tmp_path / "config.json")
    write_bound_material(path, "news_video", "news-1")
    data = json.load(open(path, encoding="utf-8"))
    assert data["bound_material"]["type_name"] == "news_video"
    assert data["bound_material"]["instance_name"] == "news-1"
    assert "bound_at" in data["bound_material"]


def test_write_bound_material_preserves_other_fields(tmp_path):
    path = str(tmp_path / "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"components": [{"x": 1}], "name": "abc"}, f)
    write_bound_material(path, "news_video", "news-1")
    data = json.load(open(path, encoding="utf-8"))
    assert data["name"] == "abc"
    assert data["components"] == [{"x": 1}]
    assert data["bound_material"]["instance_name"] == "news-1"


def test_read_after_write_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    write_bound_material(path, "news_video", "my-instance")
    bm = read_bound_material(path)
    assert bm["type_name"] == "news_video"
    assert bm["instance_name"] == "my-instance"


def test_read_bound_material_rejects_partial(tmp_path):
    """A config with bound_material present but missing instance_name
    should be treated as not-bound (defensive)."""
    path = str(tmp_path / "config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"bound_material": {"type_name": "news_video"}}, f)
    assert read_bound_material(path) is None


def test_write_bound_material_creates_parent_dir(tmp_path):
    """Config path can point to a not-yet-existing directory."""
    path = str(tmp_path / "deep" / "nested" / "config.json")
    write_bound_material(path, "news_video", "news-1")
    assert os.path.isfile(path)


def test_write_bound_material_overwrites_previous(tmp_path):
    path = str(tmp_path / "config.json")
    write_bound_material(path, "news_video", "news-1")
    write_bound_material(path, "news_video", "news-2")
    bm = read_bound_material(path)
    assert bm["instance_name"] == "news-2"
