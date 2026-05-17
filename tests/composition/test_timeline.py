"""Dataclass roundtrip + defaults for the timeline IR types."""

from __future__ import annotations

from core.composition.timeline import (
    CompositionTimeline, Element, Track,
)


def test_element_required_fields():
    e = Element(kind="subtitle_cue", start_sec=1.0, end_sec=2.5)
    assert e.kind == "subtitle_cue"
    assert e.start_sec == 1.0
    assert e.end_sec == 2.5


def test_element_defaults():
    e = Element(kind="text_watermark", start_sec=0.0, end_sec=10.0)
    assert e.z_offset == 0
    assert e.style == {}
    assert e.data == {}


def test_element_independent_default_dicts():
    """Each Element gets its own dict — no shared mutable default."""
    a = Element(kind="x", start_sec=0.0, end_sec=1.0)
    b = Element(kind="x", start_sec=0.0, end_sec=1.0)
    a.style["foo"] = "bar"
    a.data["baz"] = 1
    assert b.style == {}
    assert b.data == {}


def test_track_required_fields_and_defaults():
    t = Track(id="t1", component_kind="chapter", z_base=10, enabled=True)
    assert t.id == "t1"
    assert t.component_kind == "chapter"
    assert t.z_base == 10
    assert t.enabled is True
    assert t.elements == []


def test_composition_timeline_defaults():
    tl = CompositionTimeline(duration_sec=60.0)
    assert tl.duration_sec == 60.0
    assert tl.tracks == []
