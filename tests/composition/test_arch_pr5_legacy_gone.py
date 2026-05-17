"""PR 5 architecture guards — verifies the legacy 5-channel path has
been deleted cleanly, not just unused.

After PR 5 the engine speaks timeline IR only. CompositionRequest is
slim, render.py has no _named_overlay_jobs, and CompositionPreview no
longer carries the news_desk-only Python bridges. If any of these come
back (merge conflict, AI-suggested 'restoration', whatever) these tests
catch it loud.
"""

from __future__ import annotations

from dataclasses import fields

from core.composition.preview import CompositionPreview
from core.composition.render import CompositionRequest


# ── CompositionRequest field set ────────────────────────────────────────────

EXPECTED_REQ_FIELDS = {
    "source_video", "start_sec", "end_sec", "output_path",
    "style", "timeline", "crop_rect",
}

# Legacy fields the PR 5 cleanup removed. Any reappearance fails this test.
FORBIDDEN_REQ_FIELDS = {
    "source_srt", "source_srt_secondary",
    "hook_text", "outro_text",
    "overlays", "extra_subtitles", "extra_watermarks",
}


def test_composition_request_field_set_exact():
    actual = {f.name for f in fields(CompositionRequest)}
    assert actual == EXPECTED_REQ_FIELDS, (
        f"CompositionRequest fields drifted: extra {actual - EXPECTED_REQ_FIELDS}, "
        f"missing {EXPECTED_REQ_FIELDS - actual}")


def test_composition_request_no_legacy_fields():
    actual = {f.name for f in fields(CompositionRequest)}
    leaked = actual & FORBIDDEN_REQ_FIELDS
    assert not leaked, (
        f"Legacy CompositionRequest fields reappeared: {leaked}. "
        f"PR 5 deleted them — use req.timeline instead.")


# ── render.py: no legacy helpers ────────────────────────────────────────────

def test_render_module_has_no_named_overlay_jobs():
    """The _named_overlay_jobs legacy dispatch helper was deleted in PR 5
    when CompositionRequest dropped its 5-channel inputs. _timeline_to_
    overlay_jobs is the only path now."""
    from core.composition import render
    assert not hasattr(render, "_named_overlay_jobs"), (
        "_named_overlay_jobs was deleted in PR 5; do not reintroduce. "
        "Add timeline-side translation logic to "
        "_timeline_to_overlay_jobs instead.")


def test_render_module_has_no_extra_spec_dataclasses():
    from core.composition import render
    for name in ("ExtraSubtitleSpec", "ExtraWatermarkSpec"):
        assert not hasattr(render, name), (
            f"{name} was deleted in PR 5; subtitle/watermark are now "
            f"timeline Element kinds — see primitives/.")


def test_render_module_has_no_prepare_track_srt():
    """The render-side _prepare_track_srt was deleted; subtitle wrap
    lives in _subtitle_elements_to_temp_srt which the timeline path
    uses, and prepare_subtitle_cues (preview/import helper) still
    consumes a path through _slice_and_wrap_cues."""
    from core.composition import render
    assert not hasattr(render, "_prepare_track_srt")


# ── CompositionPreview: news_desk-only bridges gone ─────────────────────────

FORBIDDEN_PREVIEW_METHODS = {
    "set_overlays",            # news_desk typed overlay push — replaced by set_timeline
    "set_extra_subtitles",     # news_desk N-track subtitle push — replaced by set_timeline
    "set_extra_watermarks",    # news_desk N-watermark push — replaced by set_timeline
}


def test_preview_has_no_news_desk_legacy_bridges():
    for name in FORBIDDEN_PREVIEW_METHODS:
        assert not hasattr(CompositionPreview, name), (
            f"CompositionPreview.{name} was deleted in PR 5; "
            f"news_desk-shaped pushes ride preview.set_timeline now.")


def test_preview_has_set_timeline_bridge():
    """set_timeline is THE preview push path for timeline-IR consumers."""
    assert hasattr(CompositionPreview, "set_timeline")
