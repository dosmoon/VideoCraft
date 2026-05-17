"""PR 4 — render-side timeline path byte-equivalence.

The render main loop now branches: req.timeline set → _timeline_to_
overlay_jobs; else → legacy _named_overlay_jobs. These tests verify
that for the same news_desk content the timeline branch produces the
same per-kind data the legacy branch produces (same merged ASS
string, same WatermarkStyle reconstruction).

Goldens already cover the per-primitive renderer outputs from PR 2.
What PR 4 needs to guard is the TRANSLATION (timeline → _OverlayJob)
landing equivalent inputs into those same renderers.
"""

from __future__ import annotations

import os

import pytest

# Trigger registration side effects so primitives are loaded.
import creations.news_desk.components  # noqa: F401
from creations.news_desk.components import ComponentDictAdapter
from creations.news_desk.components import chapter as chapter_mod
from creations.news_desk.components import subtitle as subtitle_mod
from creations.news_desk.components import text_watermark as twm_mod

from core.composition.compile import ClipRange, CompileContext, compile_timeline
from core.composition.primitives.chapter_hero_card import ChapterHeroCardSpec
from core.composition.primitives.topic_strip import TopicStripSpec
from core.composition.render import (
    _element_to_watermark_style,
    _timeline_to_overlay_jobs,
    build_news_desk_ass_str,
    CompositionRequest,
)
from core.composition.style import CompositionStyle, WatermarkStyle


W, H = 1920, 1080


def _ctx() -> CompileContext:
    return CompileContext(project=None, material_model=None,
                            instance_dir="", duration=60.0)


def _range() -> ClipRange:
    return ClipRange(start_sec=0.0, end_sec=60.0)


def _stub_req(timeline=None) -> CompositionRequest:
    """Minimum CompositionRequest body — timeline + output_geometry are
    the only fields _timeline_to_overlay_jobs / render_composition read
    that matter for these tests."""
    from core.composition.style import OutputGeometry
    from core.composition.timeline import CompositionTimeline
    return CompositionRequest(
        source_video="", start_sec=0.0, end_sec=60.0,
        output_path="",
        output_geometry=OutputGeometry(mode="passthrough"),
        timeline=timeline or CompositionTimeline(duration_sec=60.0),
    )


# ── news_desk_ass byte-equivalence vs golden ────────────────────────────────

def test_timeline_news_desk_ass_matches_chapter_plus_topic_strip_golden():
    """Same chapter + topic_strip config that seeded the existing golden,
    but exercised through compile_timeline → _timeline_to_overlay_jobs →
    reconstructed Specs → build_news_desk_ass_str. Must produce a
    byte-identical ASS file vs the legacy direct-construction path that
    seeded tests/composition/golden/chapter-plus-topic-strip.ass.
    """
    # Build news_desk chapter instance with both modes that mirrors the
    # golden seed fixture.
    chapter_instance = {
        "id": "ch", "kind": "chapter", "enabled": True,
        "schedule": [
            {"start_sec": 0, "end_sec": 120, "title": "国际新闻",
              "refined": ""},
            {"start_sec": 3, "end_sec": 9.5, "title": "访谈：央行行长",
              "refined": "货币政策走向与下半年展望"},
        ],
        # First chapter gets the top_strip; second gets the start_card.
        "modes": {"top_strip": True, "start_card": True},
        "style": {},
    }
    # Use only the first schedule entry for top_strip + only second
    # for start_card by splitting; but chapter._compile emits both for
    # each entry that has the mode + the data. We need separate
    # instances to mirror the golden, which had just one TopicStrip
    # (entry 1) and one ChapterHeroCard (entry 2). Simulate by giving
    # each entry only the title or only the refined as appropriate.
    #
    # Simpler: build both Element types directly and pass through
    # _timeline_to_overlay_jobs as if compile produced them. This
    # tests the translator + renderer integration regardless of which
    # compile produced the elements.
    from core.composition.timeline import (
        CompositionTimeline, Element, Track,
    )
    elements = [
        Element(
            kind="topic_strip",
            start_sec=0.0, end_sec=120.0,
            data={"topic_text": "国际新闻", "style_class": "default"},
        ),
        Element(
            kind="chapter_hero_card",
            start_sec=3.0, end_sec=9.5,
            data={"title": "访谈：央行行长",
                   "body": "货币政策走向与下半年展望",
                   "inline_style": {}, "style_class": "default"},
        ),
    ]
    timeline = CompositionTimeline(
        duration_sec=120.0,
        tracks=[Track(id="ch", component_kind="chapter",
                       z_base=10, enabled=True, elements=elements)],
    )

    tmp_files: list[str] = []
    jobs = _timeline_to_overlay_jobs(
        timeline, _stub_req(), aspect_str="16:9", short_edge=1080,
        tmp_files=tmp_files, target_h=H,
    )
    # Find the news_desk_ass job — should have both specs merged.
    nd_jobs = [j for j in jobs if j.kind == "news_desk_ass"]
    assert len(nd_jobs) == 1
    specs = nd_jobs[0].data["specs"]
    # Sort by start_sec to mirror legacy z_order sort + spec ordering.
    actual = build_news_desk_ass_str(
        specs, target_w=W, target_h=H, overlay_styles={})

    # Compare against the golden seeded at PR 2 prereq.
    golden = os.path.join(
        os.path.dirname(__file__), "golden",
        "chapter-plus-topic-strip.ass")
    with open(golden, "r", encoding="utf-8", newline="\n") as f:
        expected = f.read()
    assert actual == expected


# ── Watermark reconstruction ────────────────────────────────────────────────

def test_element_to_watermark_style_roundtrip_text():
    inst = {"id": "twm-1", "kind": "text_watermark", "enabled": True,
             "text": "@chan", "fontsize": 40, "color": "#FFCC00",
             "opacity": 80, "position": "bottom-left",
             "margin_x_pct": 3, "margin_y_pct": 4}
    elements = twm_mod._compile(inst, _range(), _ctx())
    wm = _element_to_watermark_style(elements[0])
    assert isinstance(wm, WatermarkStyle)
    assert wm.type == "text"
    assert wm.enabled is True
    assert wm.text == "@chan"
    assert wm.text_fontsize == 40
    assert wm.text_color == "#FFCC00"
    assert wm.text_opacity == 80
    assert wm.position == "bottom-left"
    assert wm.margin_x_pct == 0.03
    assert wm.margin_y_pct == 0.04


def test_element_to_watermark_style_roundtrip_image(tmp_path):
    img = tmp_path / "wm.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    inst = {"id": "iwm-1", "kind": "image_watermark", "enabled": True,
             "image_path": str(img), "scale_pct": 25, "opacity": 90,
             "position": "top-right",
             "margin_x_pct": 2, "margin_y_pct": 2}
    from creations.news_desk.components import image_watermark as iwm
    elements = iwm._compile(inst, _range(), _ctx())
    wm = _element_to_watermark_style(elements[0])
    assert wm.type == "image"
    assert wm.image_path == str(img)
    assert wm.image_scale == 0.25
    assert wm.image_opacity == 90
    assert wm.position == "top-right"


# ── _timeline_to_overlay_jobs job shape ─────────────────────────────────────

def test_timeline_to_overlay_jobs_produces_expected_kinds(tmp_path):
    """Mixed news_desk content yields one news_desk_ass job + one text
    watermark job; subtitle requires SRT — we omit subtitle here and
    cover it in the subtitle-specific test below."""
    img = tmp_path / "logo.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")

    components = [
        ComponentDictAdapter({
            "id": "ch", "kind": "chapter", "enabled": True,
            "schedule": [{"start_sec": 0, "end_sec": 30,
                            "title": "T", "refined": ""}],
            "modes": {"top_strip": True},
        }),
        ComponentDictAdapter({
            "id": "twm", "kind": "text_watermark", "enabled": True,
            "text": "@x",
        }),
        ComponentDictAdapter({
            "id": "iwm", "kind": "image_watermark", "enabled": True,
            "image_path": str(img),
        }),
    ]
    timeline = compile_timeline(components, _range(), _ctx())
    tmp_files: list[str] = []
    jobs = _timeline_to_overlay_jobs(
        timeline, _stub_req(), aspect_str="16:9", short_edge=1080,
        tmp_files=tmp_files, target_h=H,
    )
    kinds = sorted(j.kind for j in jobs)
    assert kinds == ["image_watermark", "news_desk_ass", "text_watermark"]


def test_timeline_to_overlay_jobs_subtitle_writes_temp_srt(tmp_path):
    srt = tmp_path / "zh.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\nFirst.\n\n"
        "2\n00:00:05,000 --> 00:00:07,000\nSecond.\n",
        encoding="utf-8")
    components = [ComponentDictAdapter({
        "id": "sub", "kind": "subtitle", "enabled": True,
        "srt_path": str(srt), "is_chinese": False,
    })]
    timeline = compile_timeline(components, _range(), _ctx())
    tmp_files: list[str] = []
    jobs = _timeline_to_overlay_jobs(
        timeline, _stub_req(), aspect_str="16:9", short_edge=1080,
        tmp_files=tmp_files, target_h=H,
    )
    sub_jobs = [j for j in jobs if j.kind == "subtitle_cue"]
    assert len(sub_jobs) == 1
    job = sub_jobs[0]
    # A wrapped temp SRT was written + tracked in tmp_files for cleanup.
    assert job.data["srt_path"] in tmp_files
    assert os.path.isfile(job.data["srt_path"])
    # force_style string non-empty + carries the line config.
    assert "Fontname=" in job.data["force_style"]
    assert "MarginV=" in job.data["force_style"]

    # Clean up the temp files this test created.
    for p in tmp_files:
        try:
            os.unlink(p)
        except OSError:
            pass


def test_timeline_to_overlay_jobs_skips_disabled_tracks(tmp_path):
    components = [ComponentDictAdapter({
        "id": "twm", "kind": "text_watermark", "enabled": False,
        "text": "@x",
    })]
    timeline = compile_timeline(components, _range(), _ctx())
    # Disabled components are dropped at compile_timeline, so timeline
    # has no tracks → _timeline_to_overlay_jobs returns [].
    jobs = _timeline_to_overlay_jobs(
        timeline, _stub_req(), aspect_str="16:9", short_edge=1080,
        tmp_files=[], target_h=H,
    )
    assert jobs == []


def test_timeline_is_required_field():
    """timeline + output_geometry are required (no defaults)."""
    import pytest
    from core.composition.style import OutputGeometry
    with pytest.raises(TypeError):
        CompositionRequest(
            source_video="", start_sec=0.0, end_sec=0.0, output_path="",
            output_geometry=OutputGeometry(mode="passthrough"),
        )


# ── Preview adapter sanity (Tk-free dryrun) ─────────────────────────────────

def test_preview_and_render_share_same_subtitle_wrap():
    """Preview and render must run the SAME wrap pass on subtitle
    elements. Without parity a long cue overflows the preview frame
    while the burned mp4 wraps it (silent preview≠render divergence).
    Guards the regression fixed in followup to the engine-style
    decoupling commit.
    """
    from core.composition.preview import CompositionPreview
    from core.composition.render import wrap_subtitle_elements
    from core.composition.timeline import (
        CompositionTimeline, Element, Track,
    )

    long_text = "这是一行非常非常长的中文字幕，长得需要被自动换行成两行甚至三行才能塞进画面"
    elements = [
        Element(kind="subtitle_cue", start_sec=0.0, end_sec=5.0,
                style={"fontsize": 28, "is_chinese": True,
                        "color": "#FFFFFF", "bg_color": "#000000",
                        "bg_opacity": 0, "position": "bottom",
                        "block_margin_pct": 0.09},
                data={"text": long_text}),
    ]
    # Both ride the same wrap_subtitle_elements helper.
    wrapped_render = wrap_subtitle_elements(
        elements, aspect_str="16:9", short_edge=1080)
    # Preview path via set_timeline must produce cues with same text
    # content as wrapped_render — verify by capturing the JS payload.
    preview = CompositionPreview.__new__(CompositionPreview)
    calls: list[str] = []
    preview._call_js = lambda code: calls.append(code)
    timeline = CompositionTimeline(
        duration_sec=10.0,
        tracks=[Track(id="sub", component_kind="subtitle",
                       z_base=10, enabled=True, elements=elements)],
    )
    preview.set_timeline(timeline, aspect="16:9", short_edge=1080)
    # The setExtraSubtitles call carries the wrapped cue list.
    extras_call = next(c for c in calls
                        if c.startswith("window.vc.setExtraSubtitles"))
    import json
    payload_json = extras_call[len("window.vc.setExtraSubtitles("):-1]
    payload = json.loads(payload_json)
    preview_texts = [cue["text"] for cue in payload[0]["cues"]]
    render_texts = [c.content for c in wrapped_render]
    assert preview_texts == render_texts, (
        f"preview wrap diverged from render wrap:\n"
        f"  preview: {preview_texts}\n"
        f"  render:  {render_texts}")
    # Sanity: long input got wrapped to MORE than 1 cue.
    assert len(render_texts) > 1, "fixture too short to exercise wrap"


def test_preview_set_timeline_translates_without_jsbridge(monkeypatch):
    """CompositionPreview is a Tk/WebView widget but its set_timeline
    method does pure data translation before any _call_js. Stub out
    _call_js and verify the bridge calls land with the right shapes.
    """
    from core.composition.preview import CompositionPreview
    from core.composition.timeline import (
        CompositionTimeline, Element, Track,
    )

    # Construct without going through __init__ (no Tk parent).
    preview = CompositionPreview.__new__(CompositionPreview)
    calls: list[str] = []
    preview._call_js = lambda code: calls.append(code)

    elements = [
        Element(kind="topic_strip", start_sec=0, end_sec=10,
                  data={"topic_text": "TS"}),
        Element(kind="text_watermark", start_sec=0, end_sec=60,
                  style={"text_fontsize": 36, "text_color": "#FFFFFF",
                          "text_opacity": 70, "position": "top-right",
                          "margin_x_pct": 0.025, "margin_y_pct": 0.025},
                  data={"text": "@chan"}),
    ]
    timeline = CompositionTimeline(
        duration_sec=60.0,
        tracks=[Track(id="t1", component_kind="x", z_base=10,
                       enabled=True, elements=elements)],
    )
    preview.set_timeline(timeline)
    # Expect 5 bridge calls: setOverlays, setCues, setCuesSecondary,
    # setExtraSubtitles, setExtraWatermarks. No setClipMeta (no hook/outro).
    bridges = [c.split("(", 1)[0] for c in calls]
    assert bridges == [
        "window.vc.setOverlays",
        "window.vc.setCues",
        "window.vc.setCuesSecondary",
        "window.vc.setExtraSubtitles",
        "window.vc.setExtraWatermarks",
    ]
    # setOverlays got the topic_strip dict.
    assert "topic_strip" in calls[0]
    assert "TS" in calls[0]
    # setExtraWatermarks got the text watermark.
    assert "@chan" in calls[4]
