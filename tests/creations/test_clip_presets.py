"""Clip preset store — components-based schema."""

from __future__ import annotations

import json
import os

import pytest

from creations.clip import presets as cp


# ── Built-ins ──────────────────────────────────────────────────────────────

def test_builtin_names_includes_default():
    assert cp.BUILTIN_DEFAULT in cp.builtin_names()


def test_is_builtin_recognises_seeded_names():
    for name in cp.builtin_names():
        assert cp.is_builtin(name)
    assert not cp.is_builtin("my own preset")


def test_builtins_carry_components_and_output():
    """Every built-in must produce a valid preset entry (components
    list + output dict); regression guard against typos in BUILTINS."""
    for name in cp.builtin_names():
        entry = cp._builtin_presets()[name]
        assert isinstance(entry["components"], list) and entry["components"]
        assert isinstance(entry["output"], dict)
        assert entry["output"]["aspect"] in ("9:16", "1:1", "16:9", "4:5")
        assert isinstance(entry["encode_preset"], str)
        # Each component must declare a known kind that the registry
        # recognises — preset apply would crash otherwise.
        from creations.clip.components import spec_for_kind
        for comp in entry["components"]:
            assert spec_for_kind(comp["kind"]) is not None


# ── Load + seed ────────────────────────────────────────────────────────────

def test_load_store_seeds_builtins_on_first_run(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "CLIP_PRESETS_PATH",
                         str(tmp_path / "clip_preset.json"))
    store = cp.load_store()
    assert store["last_used"] == cp.BUILTIN_DEFAULT
    for name in cp.builtin_names():
        assert name in store["presets"]


def test_load_store_reinjects_missing_builtins(tmp_path, monkeypatch):
    """Hand-deleting a built-in from the JSON file must not strand the
    user — load re-injects every missing built-in."""
    path = str(tmp_path / "clip_preset.json")
    monkeypatch.setattr(cp, "CLIP_PRESETS_PATH", path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_used": "x", "presets": {}}, f)
    store = cp.load_store()
    for name in cp.builtin_names():
        assert name in store["presets"]


def test_load_store_drops_malformed_entries(tmp_path, monkeypatch):
    path = str(tmp_path / "clip_preset.json")
    monkeypatch.setattr(cp, "CLIP_PRESETS_PATH", path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"presets": {
            "good": {"components": [], "output": {"aspect": "9:16"},
                      "encode_preset": "veryfast"},
            "missing_output": {"components": []},
            "missing_components": {"output": {}},
            "not_a_dict": 42,
        }}, f)
    store = cp.load_store()
    assert "good" in store["presets"]
    assert "missing_output" not in store["presets"]
    assert "missing_components" not in store["presets"]
    assert "not_a_dict" not in store["presets"]


# ── Upsert / get / delete ──────────────────────────────────────────────────

def test_upsert_then_get_roundtrip():
    store = {"presets": {}}
    components = [{"kind": "clip_subtitle", "id": "sub1", "enabled": True}]
    cp.upsert_preset(store, "my preset",
                       components=components,
                       output_aspect="16:9", output_short_edge=720,
                       output_mode="reframe", encode_preset="slow")
    got = cp.get_preset(store, "my preset")
    assert got["components"] == components
    assert got["output"] == {"aspect": "16:9", "short_edge": 720,
                              "mode": "reframe"}
    assert got["encode_preset"] == "slow"


def test_upsert_deep_copies_components():
    """Mutating cfg.components after save must not echo into the store."""
    store = {"presets": {}}
    components = [{"kind": "clip_subtitle", "color": "#FFF"}]
    cp.upsert_preset(store, "x", components=components,
                       output_aspect="9:16", output_short_edge=1080,
                       output_mode="reframe", encode_preset="veryfast")
    components[0]["color"] = "#000"
    assert store["presets"]["x"]["components"][0]["color"] == "#FFF"


def test_get_preset_deep_copies():
    """Mutating the returned dict must not corrupt the store."""
    store = cp.load_store()
    got = cp.get_preset(store, cp.BUILTIN_DEFAULT)
    got["components"].clear()
    assert len(store["presets"][cp.BUILTIN_DEFAULT]["components"]) > 0


def test_delete_user_preset_succeeds():
    store = {"presets": {"mine": {"components": [], "output": {}}}}
    assert cp.delete_preset(store, "mine") is True
    assert "mine" not in store["presets"]


def test_delete_builtin_protected():
    store = cp.load_store()
    assert cp.delete_preset(store, cp.BUILTIN_DEFAULT) is False
    assert cp.BUILTIN_DEFAULT in store["presets"]


def test_delete_resets_last_used_when_deleting_active():
    store = {"last_used": "mine",
              "presets": {"mine": {"components": [], "output": {}}}}
    cp.delete_preset(store, "mine")
    assert store["last_used"] == cp.BUILTIN_DEFAULT


# ── List + last_used ───────────────────────────────────────────────────────

def test_list_presets_builtins_first_then_users_alpha():
    store = {"presets": {}}
    for name in cp.builtin_names():
        store["presets"][name] = {"components": [], "output": {}}
    store["presets"]["zeta"] = {"components": [], "output": {}}
    store["presets"]["alpha"] = {"components": [], "output": {}}
    names = cp.list_presets(store)
    builtins = cp.builtin_names()
    assert names[:len(builtins)] == builtins
    assert names[len(builtins):] == ["alpha", "zeta"]


def test_get_last_used_falls_back_to_default_when_missing():
    store = {"last_used": "ghost",
              "presets": {cp.BUILTIN_DEFAULT: {"components": [],
                                                  "output": {}}}}
    assert cp.get_last_used(store) == cp.BUILTIN_DEFAULT


def test_set_last_used_ignores_unknown_names():
    store = {"last_used": cp.BUILTIN_DEFAULT,
              "presets": {cp.BUILTIN_DEFAULT: {"components": [],
                                                  "output": {}}}}
    cp.set_last_used(store, "nonexistent")
    assert store["last_used"] == cp.BUILTIN_DEFAULT
