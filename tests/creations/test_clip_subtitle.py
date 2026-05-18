"""ClipSubtitleSpec — Step 5.1 compile parity + seeder behaviour."""

from __future__ import annotations

import os

import pytest

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from creations.clip.components.subtitle import (
    KIND, subtitle_adapters_from_style,
)
from creations.clip.components import spec_for_kind


SRT_BODY = """1
00:00:00,000 --> 00:00:02,000
hello world

2
00:00:03,000 --> 00:00:05,000
second cue

3
00:00:08,000 --> 00:00:10,000
third cue
"""


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "en.srt"
    p.write_text(SRT_BODY, encoding="utf-8")
    return str(p)


def _empty_ctx(duration: float = 10.0) -> CompileContext:
    return CompileContext(project=None, material_model=None,
                           instance_dir="", duration=duration)


# ── compile() basics ───────────────────────────────────────────────────────

def test_compile_missing_srt_returns_empty():
    spec = spec_for_kind(KIND)
    out = spec.compile({"kind": KIND, "srt_path": ""},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_compile_nonexistent_srt_returns_empty(tmp_path):
    spec = spec_for_kind(KIND)
    out = spec.compile({"kind": KIND, "srt_path": str(tmp_path / "no.srt")},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_compile_emits_one_element_per_in_range_cue(srt_file):
    spec = spec_for_kind(KIND)
    out = spec.compile(
        {"kind": KIND, "srt_path": srt_file,
          "fontsize": 24, "color": "#FFFFFF"},
        ClipRange(0.0, 10.0), _empty_ctx())
    assert len(out) == 3
    assert all(e.kind == "subtitle_cue" for e in out)
    assert out[0].data == {"text": "hello world"}


def test_compile_clip_relative_times(srt_file):
    """Cue at [3s, 5s] within source becomes [1s, 3s] for clip [2s, 8s]."""
    spec = spec_for_kind(KIND)
    out = spec.compile(
        {"kind": KIND, "srt_path": srt_file},
        ClipRange(2.0, 8.0), _empty_ctx())
    # Cue #1 [0,2] drops (ends at 2, clip starts at 2)
    # Cue #2 [3,5] keeps → [1, 3]
    # Cue #3 [8,10] drops (starts at 8, clip ends at 8)
    assert len(out) == 1
    assert out[0].start_sec == pytest.approx(1.0)
    assert out[0].end_sec == pytest.approx(3.0)


def test_compile_style_dict_carries_all_required_fields(srt_file):
    spec = spec_for_kind(KIND)
    out = spec.compile({
        "kind": KIND, "srt_path": srt_file,
        "fontsize": 32, "color": "#FF0000", "bold": True, "is_chinese": True,
        "bg_color": "#000000", "bg_opacity": 70, "bg_padding_x_pct": 0.05,
        "stroke_color": "#222222", "stroke_width": 3,
        "position": "top", "block_margin_pct": 0.12, "margin_v": 150,
    }, ClipRange(0.0, 10.0), _empty_ctx())
    s = out[0].style
    assert s["fontsize"] == 32
    assert s["color"] == "#FF0000"
    assert s["bold"] is True
    assert s["is_chinese"] is True
    assert s["bg_color"] == "#000000"
    assert s["bg_opacity"] == 70
    assert s["bg_padding_x_pct"] == pytest.approx(0.05)
    assert s["stroke_color"] == "#222222"
    assert s["stroke_width"] == 3
    assert s["position"] == "top"
    assert s["block_margin_pct"] == pytest.approx(0.12)
    assert s["margin_v"] == 150


# ── Seeder ─────────────────────────────────────────────────────────────────

def test_seeder_emits_no_adapters_when_disabled():
    style = CompositionStyle()
    style.subtitle.sub1.enabled = False
    style.subtitle.sub2.enabled = False
    adapters = subtitle_adapters_from_style(
        style, source_srt="/anything.srt", source_srt_secondary="")
    assert adapters == []


def test_seeder_emits_no_adapters_without_srt_path():
    """sub1 enabled but no srt → no adapter (mirrors legacy behaviour)."""
    style = CompositionStyle()
    style.subtitle.sub1.enabled = True
    adapters = subtitle_adapters_from_style(
        style, source_srt="", source_srt_secondary="")
    assert adapters == []


def test_seeder_emits_one_adapter_for_sub1_only(srt_file):
    style = CompositionStyle()
    style.subtitle.sub1.enabled = True
    style.subtitle.sub2.enabled = False
    adapters = subtitle_adapters_from_style(
        style, source_srt=srt_file, source_srt_secondary="")
    assert len(adapters) == 1
    assert adapters[0].id == "sub1"
    assert adapters[0].instance["srt_path"] == srt_file


def test_seeder_emits_two_adapters_for_dual_track(srt_file, tmp_path):
    srt2 = tmp_path / "zh.srt"
    srt2.write_text(SRT_BODY, encoding="utf-8")
    style = CompositionStyle()
    style.subtitle.sub1.enabled = True
    style.subtitle.sub2.enabled = True
    adapters = subtitle_adapters_from_style(
        style, source_srt=srt_file, source_srt_secondary=str(srt2))
    assert [a.id for a in adapters] == ["sub1", "sub2"]
    # margin_v differs between tracks (dual-track stacking)
    assert (adapters[0].instance["margin_v"]
            != adapters[1].instance["margin_v"])


def test_seeder_propagates_line_and_shared_style(srt_file):
    style = CompositionStyle()
    style.subtitle.sub1.enabled = True
    style.subtitle.sub1.fontsize = 28
    style.subtitle.sub1.color = "#00FF00"
    style.subtitle.position = "top"
    style.subtitle.stroke_color = "#123456"
    adapters = subtitle_adapters_from_style(
        style, source_srt=srt_file, source_srt_secondary="")
    inst = adapters[0].instance
    assert inst["fontsize"] == 28
    assert inst["color"] == "#00FF00"
    assert inst["position"] == "top"
    assert inst["stroke_color"] == "#123456"
