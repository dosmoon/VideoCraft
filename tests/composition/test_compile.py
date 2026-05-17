"""compile_timeline() contract — pure-function behavior on synthetic
ComponentInstance fakes. No real components / primitives involved
yet (those land in PR 3 / PR 2 respectively).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.composition.compile import (
    ClipRange, CompileContext, compile_timeline,
)
from core.composition.timeline import Element


# ── Test doubles ─────────────────────────────────────────────────────────────

@dataclass
class FakeComponent:
    """Minimal ComponentInstance-shaped object for compile() tests."""
    kind: str = "fake"
    id: str = "fake-1"
    enabled: bool = True
    emit: Callable[[ClipRange, CompileContext], list[Element]] = (
        field(default=lambda cr, ctx: []))

    def is_enabled(self) -> bool:
        return self.enabled

    def compile(self, clip_range, ctx):
        return self.emit(clip_range, ctx)


def _ctx(duration: float = 60.0) -> CompileContext:
    return CompileContext(
        project=None, material_model=None,
        instance_dir="", duration=duration)


def _range(start: float = 0.0, end: float = 60.0) -> ClipRange:
    return ClipRange(start_sec=start, end_sec=end)


# ── ClipRange / CompileContext basics ────────────────────────────────────────

def test_clip_range_duration():
    assert ClipRange(0.0, 60.0).duration_sec == 60.0
    assert ClipRange(10.0, 25.0).duration_sec == 15.0


def test_compile_context_fields():
    ctx = CompileContext(
        project="p", material_model="m",
        instance_dir="/tmp/x", duration=42.0)
    assert ctx.project == "p"
    assert ctx.material_model == "m"
    assert ctx.instance_dir == "/tmp/x"
    assert ctx.duration == 42.0


# ── compile_timeline() core behavior ─────────────────────────────────────────

def test_compile_empty_components_returns_empty_timeline():
    tl = compile_timeline([], _range(0.0, 30.0), _ctx())
    assert tl.tracks == []
    assert tl.duration_sec == 30.0


def test_compile_duration_passthrough():
    tl = compile_timeline([], _range(5.0, 17.5), _ctx())
    assert tl.duration_sec == 12.5


def test_compile_skips_disabled_components():
    on = FakeComponent(id="a", enabled=True,
                       emit=lambda cr, ctx: [
                           Element(kind="x", start_sec=0.0, end_sec=1.0)])
    off = FakeComponent(id="b", enabled=False,
                        emit=lambda cr, ctx: [
                            Element(kind="y", start_sec=0.0, end_sec=1.0)])
    tl = compile_timeline([on, off, on], _range(), _ctx())
    # Only the two enabled components produced tracks.
    assert [t.id for t in tl.tracks] == ["a", "a"]


def test_compile_assigns_z_base_by_index():
    """z_base = (sidebar_index + 1) * 10; disabled tracks DON'T consume
    an index slot — z_base reflects emitted order, not original order."""
    a = FakeComponent(id="a", enabled=True,
                      emit=lambda cr, ctx: [
                          Element(kind="x", start_sec=0.0, end_sec=1.0)])
    off = FakeComponent(id="b", enabled=False,
                        emit=lambda cr, ctx: [])
    c = FakeComponent(id="c", enabled=True,
                      emit=lambda cr, ctx: [
                          Element(kind="x", start_sec=0.0, end_sec=1.0)])
    tl = compile_timeline([a, off, c], _range(), _ctx())
    # a is at index 0 → z_base 10; off skipped; c is at index 2 → z_base 30
    assert [(t.id, t.z_base) for t in tl.tracks] == [("a", 10), ("c", 30)]


def test_compile_drops_elements_fully_outside_range():
    comp = FakeComponent(emit=lambda cr, ctx: [
        Element(kind="x", start_sec=-5.0, end_sec=-1.0),    # before
        Element(kind="x", start_sec=100.0, end_sec=120.0),  # after
        Element(kind="x", start_sec=10.0, end_sec=20.0),    # in range
    ])
    tl = compile_timeline([comp], _range(0.0, 60.0), _ctx())
    assert len(tl.tracks) == 1
    elements = tl.tracks[0].elements
    assert len(elements) == 1
    assert (elements[0].start_sec, elements[0].end_sec) == (10.0, 20.0)


def test_compile_clamps_partial_overlap():
    comp = FakeComponent(emit=lambda cr, ctx: [
        Element(kind="x", start_sec=-2.0, end_sec=3.0),     # head clipped
        Element(kind="x", start_sec=58.0, end_sec=65.0),    # tail clipped
    ])
    tl = compile_timeline([comp], _range(0.0, 60.0), _ctx())
    elements = tl.tracks[0].elements
    assert (elements[0].start_sec, elements[0].end_sec) == (0.0, 3.0)
    assert (elements[1].start_sec, elements[1].end_sec) == (58.0, 60.0)


def test_compile_preserves_element_style_and_data_on_clamp():
    """Clamped elements must keep their style / data / z_offset / kind."""
    comp = FakeComponent(emit=lambda cr, ctx: [
        Element(kind="hook_text", start_sec=-1.0, end_sec=4.0,
                z_offset=2, style={"font": "Arial"}, data={"text": "hi"}),
    ])
    tl = compile_timeline([comp], _range(0.0, 60.0), _ctx())
    e = tl.tracks[0].elements[0]
    assert e.kind == "hook_text"
    assert e.z_offset == 2
    assert e.style == {"font": "Arial"}
    assert e.data == {"text": "hi"}
    assert (e.start_sec, e.end_sec) == (0.0, 4.0)


def test_compile_track_carries_component_kind_label():
    """component_kind is metadata; it does NOT need to match element.kind."""
    comp = FakeComponent(kind="chapter", id="ch1", emit=lambda cr, ctx: [
        Element(kind="topic_strip", start_sec=0.0, end_sec=5.0),
        Element(kind="chapter_hero_card", start_sec=0.0, end_sec=3.0),
    ])
    tl = compile_timeline([comp], _range(), _ctx())
    assert tl.tracks[0].component_kind == "chapter"
    kinds = [e.kind for e in tl.tracks[0].elements]
    assert kinds == ["topic_strip", "chapter_hero_card"]
