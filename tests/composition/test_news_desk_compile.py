"""PR 3 — news_desk component compile() + compile_timeline integration.

Each of the 4 news_desk components (chapter / subtitle / text_watermark /
image_watermark) gained a `compile(instance, clip_range, ctx) →
list[Element]` method that mirrors `to_overlays()` semantics in
timeline-IR shape. Plus a ComponentDictAdapter that lets the dict-based
instance pipeline feed engine `compile_timeline()` via the
ComponentInstance protocol.

These tests cover:
- Each component's compile() output shape (kind / start / end / data
  / style fields). Per-instance edge cases (disabled, empty, partial
  data).
- ComponentDictAdapter wraps a dict, satisfies ComponentInstance.
- compile_timeline() consumes mixed news_desk components.
- KNOWN_KINDS validation rejects typos.
"""

from __future__ import annotations

import os

import pytest

# Trigger components.register() side effects.
import creations.news_desk.components  # noqa: F401
from creations.news_desk.components import (
    ComponentDictAdapter, spec_for_kind,
)
from creations.news_desk.components import chapter as chapter_mod
from creations.news_desk.components import subtitle as subtitle_mod
from creations.news_desk.components import text_watermark as twm_mod
from creations.news_desk.components import image_watermark as iwm_mod

from core.composition.compile import (
    ClipRange, CompileContext, compile_timeline,
)
from core.composition.timeline import Element


# ── Fixtures / helpers ──────────────────────────────────────────────────────

def _ctx(instance_dir: str = "", duration: float = 60.0) -> CompileContext:
    return CompileContext(
        project=None, material_model=None,
        instance_dir=instance_dir, duration=duration)


def _range(start: float = 0.0, end: float = 60.0) -> ClipRange:
    return ClipRange(start_sec=start, end_sec=end)


# ── chapter.compile ─────────────────────────────────────────────────────────

def _chapter_instance(*, enabled=True, schedule=None, modes=None,
                       style=None) -> dict:
    return {
        "id": "ch-1", "kind": "chapter",
        "enabled": enabled,
        "schedule": schedule or [],
        "modes": modes or {},
        "style": style or {},
    }


def test_chapter_compile_disabled_returns_empty():
    inst = _chapter_instance(
        enabled=False,
        schedule=[{"start_sec": 0, "end_sec": 5, "title": "A", "refined": "..."}],
        modes={"top_strip": True, "start_card": True},
    )
    assert chapter_mod._compile(inst, _range(), _ctx()) == []


def test_chapter_compile_empty_schedule_returns_empty():
    inst = _chapter_instance(modes={"top_strip": True})
    assert chapter_mod._compile(inst, _range(), _ctx()) == []


def test_chapter_compile_top_strip_only():
    inst = _chapter_instance(
        schedule=[
            {"start_sec": 0, "end_sec": 10, "title": "Intro", "refined": ""},
            {"start_sec": 10, "end_sec": 25, "title": "Body", "refined": ""},
        ],
        modes={"top_strip": True, "start_card": False},
    )
    elements = chapter_mod._compile(inst, _range(), _ctx())
    assert [e.kind for e in elements] == ["topic_strip", "topic_strip"]
    assert [e.data["topic_text"] for e in elements] == ["Intro", "Body"]
    assert (elements[0].start_sec, elements[0].end_sec) == (0.0, 10.0)
    assert (elements[1].start_sec, elements[1].end_sec) == (10.0, 25.0)


def test_chapter_compile_start_card_with_inline_style():
    inst = _chapter_instance(
        schedule=[{"start_sec": 5, "end_sec": 30,
                    "title": "Big news", "refined": "context body"}],
        modes={"start_card": True},
        style={"start_card": {
            "duration_sec": 4,
            "title_color": "#FFCC00",
            "title_fontsize": 64,
        }},
    )
    elements = chapter_mod._compile(inst, _range(), _ctx())
    assert len(elements) == 1
    e = elements[0]
    assert e.kind == "chapter_hero_card"
    assert (e.start_sec, e.end_sec) == (5.0, 9.0)    # min(30, 5+4)
    assert e.data["title"] == "Big news"
    assert e.data["body"] == "context body"
    # duration_sec stripped; other fields ride in inline_style.
    assert "duration_sec" not in e.data["inline_style"]
    assert e.data["inline_style"]["title_color"] == "#FFCC00"
    assert e.data["inline_style"]["title_fontsize"] == 64


def test_chapter_compile_both_modes_emit_two_elements_per_chapter():
    inst = _chapter_instance(
        schedule=[{"start_sec": 0, "end_sec": 30,
                    "title": "Chapter 1", "refined": "summary"}],
        modes={"top_strip": True, "start_card": True},
    )
    elements = chapter_mod._compile(inst, _range(), _ctx())
    kinds = [e.kind for e in elements]
    assert kinds == ["topic_strip", "chapter_hero_card"]


def test_chapter_compile_clip_relative_when_range_offset():
    inst = _chapter_instance(
        schedule=[{"start_sec": 20, "end_sec": 30,
                    "title": "T", "refined": ""}],
        modes={"top_strip": True},
    )
    # Clip range [15, 35] → chapter at source 20..30 → clip-relative 5..15.
    elements = chapter_mod._compile(inst, _range(15.0, 35.0), _ctx())
    assert (elements[0].start_sec, elements[0].end_sec) == (5.0, 15.0)


# ── subtitle.compile ────────────────────────────────────────────────────────

_SRT_FIXTURE = """1
00:00:01,000 --> 00:00:03,000
First cue.

2
00:00:04,500 --> 00:00:07,200
Second cue with more text.

3
00:00:10,000 --> 00:00:12,000
Third.
"""


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "zh.srt"
    p.write_text(_SRT_FIXTURE, encoding="utf-8")
    return str(p)


def _subtitle_instance(*, enabled=True, srt_path: str = "",
                        is_chinese=True, fontsize=24,
                        position="bottom") -> dict:
    return {
        "id": "sub-zh", "kind": "subtitle",
        "enabled": enabled,
        "srt_path": srt_path,
        "is_chinese": is_chinese,
        "fontsize": fontsize,
        "position": position,
    }


def test_subtitle_compile_disabled_returns_empty():
    inst = _subtitle_instance(enabled=False, srt_path="/anywhere.srt")
    assert subtitle_mod._compile(inst, _range(), _ctx()) == []


def test_subtitle_compile_no_srt_path_returns_empty():
    inst = _subtitle_instance(srt_path="")
    assert subtitle_mod._compile(inst, _range(), _ctx()) == []


def test_subtitle_compile_missing_file_returns_empty():
    inst = _subtitle_instance(srt_path="/this/does/not/exist.srt")
    assert subtitle_mod._compile(inst, _range(), _ctx()) == []


def test_subtitle_compile_emits_one_element_per_cue(srt_file):
    inst = _subtitle_instance(srt_path=srt_file)
    elements = subtitle_mod._compile(inst, _range(0.0, 60.0), _ctx())
    assert len(elements) == 3
    assert all(e.kind == "subtitle_cue" for e in elements)
    assert [(e.start_sec, e.end_sec) for e in elements] == [
        (1.0, 3.0), (4.5, 7.2), (10.0, 12.0),
    ]
    assert elements[0].data["text"] == "First cue."
    # Style dict shared across all cues for one track.
    assert elements[0].style is elements[1].style


def test_subtitle_compile_style_dict_carries_track_fields(srt_file):
    inst = _subtitle_instance(
        srt_path=srt_file, fontsize=32, position="top", is_chinese=False)
    elements = subtitle_mod._compile(inst, _range(), _ctx())
    style = elements[0].style
    assert style["fontsize"] == 32
    assert style["position"] == "top"
    assert style["is_chinese"] is False
    assert style["color"] == "#FFFFFF"


def test_subtitle_compile_clip_relative_when_range_offset(srt_file):
    inst = _subtitle_instance(srt_path=srt_file)
    # Clip range [4, 20] — cues at source 1, 4.5, 10 → clip-relative
    # -3, 0.5, 6. First gets dropped only by compile_timeline's
    # _clip_to_range (this unit test exercises compile() raw output).
    elements = subtitle_mod._compile(inst, _range(4.0, 20.0), _ctx())
    assert [(e.start_sec, e.end_sec) for e in elements] == [
        (-3.0, -1.0), (0.5, 3.2), (6.0, 8.0),
    ]


# ── text_watermark.compile ──────────────────────────────────────────────────

def test_text_watermark_compile_disabled_returns_empty():
    inst = {"id": "twm-1", "kind": "text_watermark",
             "enabled": False, "text": "@channel"}
    assert twm_mod._compile(inst, _range(), _ctx()) == []


def test_text_watermark_compile_empty_text_returns_empty():
    inst = {"id": "twm-1", "kind": "text_watermark",
             "enabled": True, "text": "   "}
    assert twm_mod._compile(inst, _range(), _ctx()) == []


def test_text_watermark_compile_emits_full_duration_element():
    inst = {"id": "twm-1", "kind": "text_watermark", "enabled": True,
             "text": "@channel", "fontsize": 40, "color": "#FFCC00",
             "position": "bottom-left",
             "margin_x_pct": 3, "margin_y_pct": 4, "opacity": 80}
    elements = twm_mod._compile(inst, _range(0.0, 120.0), _ctx())
    assert len(elements) == 1
    e = elements[0]
    assert e.kind == "text_watermark"
    assert (e.start_sec, e.end_sec) == (0.0, 120.0)
    assert e.data["text"] == "@channel"
    assert e.style["text_fontsize"] == 40
    assert e.style["text_color"] == "#FFCC00"
    assert e.style["text_opacity"] == 80
    assert e.style["position"] == "bottom-left"
    assert e.style["margin_x_pct"] == 0.03
    assert e.style["margin_y_pct"] == 0.04


# ── image_watermark.compile ─────────────────────────────────────────────────

def test_image_watermark_compile_empty_path_returns_empty():
    inst = {"id": "iwm-1", "kind": "image_watermark",
             "enabled": True, "image_path": ""}
    assert iwm_mod._compile(inst, _range(), _ctx()) == []


def test_image_watermark_compile_emits_full_duration_element(tmp_path):
    img = tmp_path / "logo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    inst = {"id": "iwm-1", "kind": "image_watermark", "enabled": True,
             "image_path": str(img), "scale_pct": 20, "opacity": 90,
             "position": "top-right",
             "margin_x_pct": 2, "margin_y_pct": 2}
    elements = iwm_mod._compile(inst, _range(0.0, 90.0), _ctx())
    assert len(elements) == 1
    e = elements[0]
    assert e.kind == "image_watermark"
    assert (e.start_sec, e.end_sec) == (0.0, 90.0)
    assert e.data["image_path"] == str(img)
    assert e.style["image_scale"] == 0.20
    assert e.style["image_opacity"] == 90


# ── ComponentDictAdapter ────────────────────────────────────────────────────

def test_adapter_satisfies_component_instance_protocol():
    inst = {"id": "twm-1", "kind": "text_watermark", "enabled": True,
             "text": "@x"}
    ad = ComponentDictAdapter(inst)
    assert ad.kind == "text_watermark"
    assert ad.id == "twm-1"
    assert ad.is_enabled() is True
    elements = ad.compile(_range(), _ctx())
    assert len(elements) == 1
    assert elements[0].kind == "text_watermark"


def test_adapter_unknown_kind_compile_returns_empty():
    inst = {"id": "??-1", "kind": "nonexistent", "enabled": True}
    ad = ComponentDictAdapter(inst)
    assert ad.compile(_range(), _ctx()) == []


# ── compile_timeline integration ────────────────────────────────────────────

def test_compile_timeline_with_news_desk_components(srt_file):
    components = [
        ComponentDictAdapter({
            "id": "sub", "kind": "subtitle", "enabled": True,
            "srt_path": srt_file,
        }),
        ComponentDictAdapter({
            "id": "twm", "kind": "text_watermark", "enabled": True,
            "text": "@channel",
        }),
        ComponentDictAdapter({
            "id": "ch", "kind": "chapter", "enabled": True,
            "schedule": [{"start_sec": 0, "end_sec": 30,
                           "title": "Intro", "refined": ""}],
            "modes": {"top_strip": True},
        }),
    ]
    timeline = compile_timeline(components, _range(0.0, 60.0), _ctx(duration=60.0))
    assert timeline.duration_sec == 60.0
    assert [t.id for t in timeline.tracks] == ["sub", "twm", "ch"]
    assert [t.component_kind for t in timeline.tracks] == [
        "subtitle", "text_watermark", "chapter",
    ]
    # z_base from sidebar index → (i+1)*10
    assert [t.z_base for t in timeline.tracks] == [10, 20, 30]
    # subtitle → 3 cue elements; twm → 1 wm element; chapter → 1 topic_strip
    assert [len(t.elements) for t in timeline.tracks] == [3, 1, 1]


def test_compile_timeline_disabled_components_dropped(srt_file):
    components = [
        ComponentDictAdapter({
            "id": "sub", "kind": "subtitle", "enabled": False,
            "srt_path": srt_file,
        }),
        ComponentDictAdapter({
            "id": "twm", "kind": "text_watermark", "enabled": True,
            "text": "@x",
        }),
    ]
    timeline = compile_timeline(components, _range(), _ctx())
    assert [t.id for t in timeline.tracks] == ["twm"]


def test_compile_timeline_unknown_kind_raises():
    """A buggy component that emits an Element with a kind outside the
    primitive catalog must fail at compile time, not silently."""
    from core.composition.timeline import Element

    class BadComp:
        kind = "buggy"
        id = "b-1"
        def is_enabled(self): return True
        def compile(self, cr, ctx):
            return [Element(kind="not_a_real_kind",
                              start_sec=0.0, end_sec=1.0)]

    with pytest.raises(ValueError, match="unknown kind 'not_a_real_kind'"):
        compile_timeline([BadComp()], _range(), _ctx())


# ── ComponentSpec wiring ────────────────────────────────────────────────────

def test_all_4_components_register_compile_fn():
    """Each of the 4 news_desk components must have its compile callable
    set on the ComponentSpec. Catches accidental register() arg drops."""
    for kind in ("chapter", "subtitle", "text_watermark", "image_watermark"):
        spec = spec_for_kind(kind)
        assert spec is not None, f"{kind} not registered"
        assert spec.compile is not None, f"{kind} missing compile()"
        assert callable(spec.compile)
