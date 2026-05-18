"""creations/clip/components — Step 5.0 scaffold contract.

These tests pin the bare scaffolding before any actual spec lands:
- clip has its OWN registry (not news_desk's)
- ComponentDictAdapter resolves against clip's registry
- ClipProjectContext carries clip_overrides + the engine's 4 fields
"""

from __future__ import annotations

import pytest

from core.composition.compile import ClipRange, CompileContext
from creations.clip import components as cc
from creations.news_desk import components as nd


# ── Registry isolation ─────────────────────────────────────────────────────

def test_clip_subtitle_registered():
    """Step 5.1 — clip_subtitle is the first spec to land."""
    assert "clip_subtitle" in cc.REGISTRY
    spec = cc.REGISTRY["clip_subtitle"]
    assert spec.compile is not None


def test_clip_registry_is_separate_from_news_desk():
    """Same kind in both registries must not collide — sharing one would
    let creations see each other's components."""
    assert cc.REGISTRY is not nd.REGISTRY


# ── register / lookup helpers ──────────────────────────────────────────────

def test_register_and_lookup(monkeypatch):
    monkeypatch.setattr(cc, "REGISTRY", {})
    spec = nd.ComponentSpec(
        kind="test_kind", name_key="x", add_label_key="y")
    cc.register(spec)
    assert cc.spec_for_kind("test_kind") is spec
    assert cc.spec_for_instance({"kind": "test_kind"}) is spec
    assert cc.spec_for_kind("missing") is None
    assert cc.spec_for_instance({"kind": "missing"}) is None
    assert cc.spec_for_instance("not-a-dict") is None
    assert cc.all_specs() == [spec]


def test_register_last_wins(monkeypatch):
    """Hot-reload friendliness — re-registering the same kind replaces."""
    monkeypatch.setattr(cc, "REGISTRY", {})
    a = nd.ComponentSpec(kind="k", name_key="a", add_label_key="a")
    b = nd.ComponentSpec(kind="k", name_key="b", add_label_key="b")
    cc.register(a)
    cc.register(b)
    assert cc.spec_for_kind("k") is b


# ── ComponentDictAdapter ───────────────────────────────────────────────────

def test_adapter_resolves_against_clip_registry(monkeypatch):
    monkeypatch.setattr(cc, "REGISTRY", {})
    calls = []

    def _compile(instance, clip_range, ctx):
        calls.append((instance["kind"], clip_range.duration_sec))
        return []

    cc.register(nd.ComponentSpec(
        kind="t", name_key="x", add_label_key="y", compile=_compile))
    adapter = cc.ComponentDictAdapter({"kind": "t", "id": "i1"})
    assert adapter.kind == "t"
    assert adapter.id == "i1"
    assert adapter.is_enabled() is True
    adapter.compile(ClipRange(0.0, 5.0), CompileContext(
        project=None, material_model=None, instance_dir="", duration=5.0))
    assert calls == [("t", 5.0)]


def test_adapter_unknown_kind_compiles_to_empty():
    adapter = cc.ComponentDictAdapter({"kind": "unregistered"})
    out = adapter.compile(ClipRange(0.0, 1.0), CompileContext(
        project=None, material_model=None, instance_dir="", duration=1.0))
    assert out == []


def test_adapter_disabled_flag():
    on = cc.ComponentDictAdapter({"kind": "x", "enabled": True})
    off = cc.ComponentDictAdapter({"kind": "x", "enabled": False})
    default = cc.ComponentDictAdapter({"kind": "x"})  # default = enabled
    assert on.is_enabled() is True
    assert off.is_enabled() is False
    assert default.is_enabled() is True


