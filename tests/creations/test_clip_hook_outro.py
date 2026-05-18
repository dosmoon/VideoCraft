"""Hook + outro card specs — Step 5.3 compile + seeder."""

from __future__ import annotations

import pytest

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from creations.clip.components import spec_for_kind
from creations.clip.components.hook_outro import (
    KIND_HOOK, KIND_OUTRO, template_from_style,
)


def _ctx(duration: float = 30.0) -> CompileContext:
    return CompileContext(project=None, material_model=None,
                           instance_dir="", duration=duration)


# ── Both kinds register ────────────────────────────────────────────────────

def test_both_specs_registered():
    assert spec_for_kind(KIND_HOOK) is not None
    assert spec_for_kind(KIND_OUTRO) is not None


# ── compile — hook ─────────────────────────────────────────────────────────

def test_hook_empty_text_returns_empty():
    spec = spec_for_kind(KIND_HOOK)
    assert spec.compile({"kind": KIND_HOOK, "text": "", "duration_sec": 5.0},
                          ClipRange(0.0, 30.0), _ctx()) == []


def test_hook_zero_duration_returns_empty():
    spec = spec_for_kind(KIND_HOOK)
    assert spec.compile({"kind": KIND_HOOK, "text": "boom",
                          "duration_sec": 0.0},
                          ClipRange(0.0, 30.0), _ctx()) == []


def test_hook_spans_first_n_seconds():
    spec = spec_for_kind(KIND_HOOK)
    out = spec.compile({
        "kind": KIND_HOOK, "text": "boom", "duration_sec": 5.0,
        "font": "Arial", "size": 48, "color": "#FFFFFF",
        "bg_color": "#000000", "bg_opacity": 70,
        "stroke_color": "#000000", "stroke_width": 3, "box_padding": 10,
        "position": "upper-third",
    }, ClipRange(0.0, 30.0), _ctx(30.0))
    assert len(out) == 1
    e = out[0]
    assert e.kind == "hook_text"
    assert e.start_sec == 0.0
    assert e.end_sec == 5.0
    assert e.data["text"] == "boom"


def test_hook_clamps_to_clip_duration():
    """duration_sec=10 but clip is only 3s wide → end clamps to 3."""
    spec = spec_for_kind(KIND_HOOK)
    out = spec.compile({"kind": KIND_HOOK, "text": "boom",
                          "duration_sec": 10.0, "position": "upper-third"},
                         ClipRange(0.0, 3.0), _ctx(3.0))
    assert len(out) == 1
    assert out[0].end_sec == 3.0


def test_hook_style_dict_carries_renderer_fields():
    spec = spec_for_kind(KIND_HOOK)
    out = spec.compile({
        "kind": KIND_HOOK, "text": "x", "duration_sec": 5.0,
        "font": "Arial", "size_pct": 0.056, "color": "#FF0000",
        "bg_color": "#222222", "bg_opacity": 80,
        "stroke_color": "#111111", "stroke_pct": 0.004,
        "box_padding_pct": 0.011, "position": "lower-third",
    }, ClipRange(0.0, 30.0), _ctx(30.0))
    s = out[0].style
    assert s["font"] == "Arial"
    assert s["size_pct"] == pytest.approx(0.056)
    assert s["color"] == "#FF0000"
    assert s["bg_color"] == "#222222"
    assert s["bg_opacity"] == 80
    assert s["stroke_color"] == "#111111"
    assert s["stroke_pct"] == pytest.approx(0.004)
    assert s["box_padding_pct"] == pytest.approx(0.011)
    # Role-specific position: hook stamps hook_position from instance
    assert s["hook_position"] == "lower-third"
    assert s["hook_duration_sec"] == 5.0


# ── compile — outro ────────────────────────────────────────────────────────

def test_outro_empty_text_returns_empty():
    spec = spec_for_kind(KIND_OUTRO)
    assert spec.compile({"kind": KIND_OUTRO, "text": "", "duration_sec": 5.0},
                          ClipRange(0.0, 30.0), _ctx()) == []


def test_outro_spans_last_n_seconds():
    spec = spec_for_kind(KIND_OUTRO)
    out = spec.compile({
        "kind": KIND_OUTRO, "text": "thanks", "duration_sec": 5.0,
        "position": "lower-third",
    }, ClipRange(0.0, 30.0), _ctx(30.0))
    assert len(out) == 1
    assert out[0].kind == "outro_text"
    assert out[0].start_sec == pytest.approx(25.0)
    assert out[0].end_sec == 30.0


def test_outro_clamps_start_to_zero_when_longer_than_clip():
    """duration_sec=10 but clip only 3s → start clamped to 0, full span."""
    spec = spec_for_kind(KIND_OUTRO)
    out = spec.compile({"kind": KIND_OUTRO, "text": "x",
                          "duration_sec": 10.0, "position": "lower-third"},
                         ClipRange(0.0, 3.0), _ctx(3.0))
    assert len(out) == 1
    assert out[0].start_sec == 0.0
    assert out[0].end_sec == 3.0


def test_outro_role_stamps_outro_position():
    spec = spec_for_kind(KIND_OUTRO)
    out = spec.compile({"kind": KIND_OUTRO, "text": "x",
                          "duration_sec": 5.0, "position": "upper-third"},
                         ClipRange(0.0, 30.0), _ctx(30.0))
    s = out[0].style
    assert s["outro_position"] == "upper-third"
    assert s["outro_duration_sec"] == 5.0


# ── template_from_style migration ──────────────────────────────────────────

def test_template_default_emits_both():
    """Default CompositionStyle has hook/outro durations > 0 → both cards
    seeded with text="" (composer fills per candidate)."""
    style = CompositionStyle()
    out = template_from_style(style)
    assert [c["kind"] for c in out] == [KIND_HOOK, KIND_OUTRO]
    assert all(c["text"] == "" for c in out)


def test_template_zero_duration_drops_role():
    style = CompositionStyle()
    style.hook_outro.hook_duration_sec = 0.0
    out = template_from_style(style)
    assert [c["kind"] for c in out] == [KIND_OUTRO]


def test_template_propagates_style_fields():
    style = CompositionStyle()
    style.hook_outro.font = "Custom"
    style.hook_outro.size = 60
    style.hook_outro.color = "#00FF00"
    style.hook_outro.hook_position = "lower-third"
    style.hook_outro.outro_position = "upper-third"
    style.hook_outro.hook_duration_sec = 7.0
    out = template_from_style(style)
    h, o = out[0], out[1]
    assert h["font"] == "Custom"
    # Legacy int-px size migrates to pct via /1080.
    assert h["size_pct"] == pytest.approx(60 / 1080.0)
    assert h["color"] == "#00FF00"
    assert h["position"] == "lower-third"
    assert h["duration_sec"] == 7.0
    assert o["position"] == "upper-third"
