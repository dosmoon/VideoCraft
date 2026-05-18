"""ClipWatermarkSpec — Step 5.2 compile parity + seeder behaviour."""

from __future__ import annotations

import pytest

from core.composition.compile import ClipRange, CompileContext
from core.composition.style import CompositionStyle
from creations.clip.components import spec_for_kind
from creations.clip.components.watermark import (
    KIND_IMAGE, KIND_TEXT, template_from_style,
)


def _empty_ctx(duration: float = 10.0) -> CompileContext:
    return CompileContext(project=None, material_model=None,
                           instance_dir="", duration=duration)


# ── Both kinds register ────────────────────────────────────────────────────

def test_both_watermark_specs_registered():
    assert spec_for_kind(KIND_TEXT) is not None
    assert spec_for_kind(KIND_IMAGE) is not None


# ── compile() — text watermark ─────────────────────────────────────────────

def test_text_compile_empty_text_returns_empty():
    spec = spec_for_kind(KIND_TEXT)
    out = spec.compile({"kind": KIND_TEXT, "text": ""},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_text_compile_whitespace_only_returns_empty():
    spec = spec_for_kind(KIND_TEXT)
    out = spec.compile({"kind": KIND_TEXT, "text": "   "},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_text_compile_emits_one_element_spanning_full_range():
    spec = spec_for_kind(KIND_TEXT)
    out = spec.compile({
        "kind": KIND_TEXT, "text": "@channel",
        "text_fontsize_pct": 0.033,
        "text_color": "#FFFFFF", "text_opacity": 70,
        "position": "top-right",
        "margin_x_pct": 0.025, "margin_y_pct": 0.025,
        "image_scale": 0.15, "image_opacity": 100,
    }, ClipRange(0.0, 7.5), _empty_ctx(7.5))
    assert len(out) == 1
    e = out[0]
    assert e.kind == "text_watermark"
    assert e.start_sec == 0.0
    assert e.end_sec == 7.5
    assert e.data == {"text": "@channel", "image_path": ""}
    assert e.style["text_fontsize_pct"] == pytest.approx(0.033)
    assert e.style["position"] == "top-right"
    assert e.style["margin_x_pct"] == pytest.approx(0.025)


# ── compile() — image watermark ────────────────────────────────────────────

def test_image_compile_empty_path_returns_empty():
    spec = spec_for_kind(KIND_IMAGE)
    out = spec.compile({"kind": KIND_IMAGE, "image_path": ""},
                        ClipRange(0.0, 10.0), _empty_ctx())
    assert out == []


def test_image_compile_emits_one_element_spanning_full_range():
    spec = spec_for_kind(KIND_IMAGE)
    out = spec.compile({
        "kind": KIND_IMAGE, "image_path": "C:/wm/logo.png",
        "image_scale": 0.2, "image_opacity": 80,
        "position": "bottom-right",
        "margin_x_pct": 0.03, "margin_y_pct": 0.04,
        "text_fontsize": 36, "text_color": "#FFFFFF", "text_opacity": 70,
    }, ClipRange(0.0, 5.0), _empty_ctx(5.0))
    assert len(out) == 1
    e = out[0]
    assert e.kind == "image_watermark"
    assert e.start_sec == 0.0
    assert e.end_sec == 5.0
    assert e.data == {"text": "", "image_path": "C:/wm/logo.png"}
    assert e.style["image_scale"] == pytest.approx(0.2)
    assert e.style["image_opacity"] == 80


# ── template_from_style migration ──────────────────────────────────────────

def test_template_empty_when_disabled():
    style = CompositionStyle()
    style.watermark.enabled = False
    assert template_from_style(style) == []


def test_template_picks_text_kind():
    style = CompositionStyle()
    style.watermark.enabled = True
    style.watermark.type = "text"
    style.watermark.text = "hello"
    out = template_from_style(style)
    assert len(out) == 1
    assert out[0]["kind"] == KIND_TEXT


def test_template_picks_image_kind():
    style = CompositionStyle()
    style.watermark.enabled = True
    style.watermark.type = "image"
    style.watermark.image_path = "C:/wm/logo.png"
    out = template_from_style(style)
    assert len(out) == 1
    assert out[0]["kind"] == KIND_IMAGE


def test_template_propagates_all_fields():
    style = CompositionStyle()
    style.watermark.enabled = True
    style.watermark.type = "text"
    style.watermark.text = "@chan"
    style.watermark.text_fontsize = 48
    style.watermark.text_color = "#FF0000"
    style.watermark.text_opacity = 90
    style.watermark.position = "bottom-left"
    style.watermark.margin_x_pct = 0.04
    style.watermark.margin_y_pct = 0.05
    inst = template_from_style(style)[0]
    assert inst["text"] == "@chan"
    assert inst["text_fontsize_pct"] == pytest.approx(48 / 1080.0)
    assert inst["text_color"] == "#FF0000"
    assert inst["text_opacity"] == 90
    assert inst["position"] == "bottom-left"
    assert inst["margin_x_pct"] == pytest.approx(0.04)
    assert inst["margin_y_pct"] == pytest.approx(0.05)
