"""PR 2 safety net — byte-equivalence goldens for render-input strings.

PR 2 splits 491 lines of news_desk libass code + the typed-overlay
hierarchy into per-primitive files. The only check that the move
preserved behavior is "same fixture inputs → same render-input strings"
across the refactor.

Two artifact classes:
- **A** (full ASS): build_news_desk_ass_str() — what libass renders.
  Three scenarios (chapter only / topic_strip only / mixed).
- **B** (ffmpeg filter / force_style snippets): the per-primitive
  string functions that today live in render.py. Five scenarios
  (subtitle force_style x2 / text wm / image wm / hook+outro).

Generate goldens from a known-good HEAD before starting PR 2:
    UPDATE_GOLDENS=1 myenv/Scripts/python.exe -m pytest tests/composition/test_render_string_golden.py

Then commit `tests/composition/golden/`. After PR 2, run without the
env var — any mismatch fails the test with a diff.

Snippets that reference temp files (drawtext textfile=...) embed an
unstable os.getpid() + id() in the path; we normalize those before
comparison so the goldens stay byte-stable across runs.
"""

from __future__ import annotations

import os
import re

import pytest

from core.composition.news_desk_overlays import build_news_desk_ass_str
from core.composition.overlays import (
    ChapterHeroCardOverlay, TopicStripOverlay,
)
from core.composition.render import (
    _build_image_watermark_chain,
    _build_subtitle_force_style,
    _build_text_watermark_drawtext,
    _drawtext_filter,
    _track_margins,
)
from core.composition.style import (
    ChapterHeroCardStyle, HookOutroStyle, SubtitleLineStyle,
    SubtitleStyle, TopicStripStyle, WatermarkStyle,
)


GOLDEN_DIR = os.path.join(
    os.path.dirname(__file__), "golden")
UPDATE = os.environ.get("UPDATE_GOLDENS") == "1"


# ── Helpers ─────────────────────────────────────────────────────────────────

def _check_golden(actual: str, filename: str) -> None:
    """Compare `actual` against tests/composition/golden/<filename>.

    Set env UPDATE_GOLDENS=1 to overwrite the golden with `actual` —
    used once on a known-good HEAD to seed the baseline, never as a
    routine "test failed, just update it" reflex.
    """
    path = os.path.join(GOLDEN_DIR, filename)
    if UPDATE:
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(actual)
        return
    assert os.path.exists(path), (
        f"Golden missing: {path}. "
        f"Run with UPDATE_GOLDENS=1 to seed.")
    with open(path, "r", encoding="utf-8", newline="\n") as f:
        expected = f.read()
    assert actual == expected, f"Golden mismatch vs {filename}"


# Drawtext snippets reference `composition-<role>-<pid>-<id>.txt` temp
# files. The pid/id parts shift every run; normalize to `PID-ID` so the
# golden stays stable while the snippet structure stays verifiable.
_TMP_NORMALIZE = re.compile(r"composition-([\w-]+?)-(\d+)-(\d+)\.txt")


def _normalize_tmp_paths(s: str) -> str:
    return _TMP_NORMALIZE.sub(r"composition-\1-PID-ID.txt", s)


def _run_with_tmp_cleanup(fn):
    """Helper for the impure drawtext functions that take a tmp_files
    list and append paths to it. Calls fn(tmp_files=[]), then deletes
    whatever it wrote so the test doesn't litter %TEMP%.
    """
    tmp_files: list[str] = []
    try:
        result = fn(tmp_files)
    finally:
        pass
    for p in tmp_files:
        try:
            os.unlink(p)
        except OSError:
            pass
    return result


# ── A. News-desk ASS goldens ────────────────────────────────────────────────

# Standard target dimensions for fixtures — 1920x1080 is the common
# news_desk preview/output geometry; both PlayResX/Y and pixel math
# derive from it.
W, H = 1920, 1080


def test_golden_chapter_hero_card_only():
    specs = [
        ChapterHeroCardOverlay(
            title="第一章 开场",
            body="本章节介绍新闻背景与主要人物",
            start_sec=2.5, end_sec=8.0,
            style_class="default",
        ),
    ]
    actual = build_news_desk_ass_str(
        specs, target_w=W, target_h=H, overlay_styles={})
    assert actual is not None
    _check_golden(actual, "chapter-hero-card-only.ass")


def test_golden_topic_strip_only():
    specs = [
        TopicStripOverlay(
            topic_text="经济观察 · 第三季度",
            start_sec=0.0, end_sec=300.0,
            style_class="default",
        ),
    ]
    actual = build_news_desk_ass_str(
        specs, target_w=W, target_h=H, overlay_styles={})
    assert actual is not None
    _check_golden(actual, "topic-strip-only.ass")


def test_golden_chapter_plus_topic_strip():
    """Mixed scene — topic_strip persists the whole window, chapter card
    overlays during the intro. Exercises both libass dialogue builders
    in one ASS file."""
    specs = [
        TopicStripOverlay(
            topic_text="国际新闻",
            start_sec=0.0, end_sec=120.0,
            style_class="default",
        ),
        ChapterHeroCardOverlay(
            title="访谈：央行行长",
            body="货币政策走向与下半年展望",
            start_sec=3.0, end_sec=9.5,
            style_class="default",
        ),
    ]
    actual = build_news_desk_ass_str(
        specs, target_w=W, target_h=H, overlay_styles={})
    assert actual is not None
    _check_golden(actual, "chapter-plus-topic-strip.ass")


# ── B. Subtitle force_style goldens ─────────────────────────────────────────

def _default_subtitle_style() -> SubtitleStyle:
    return SubtitleStyle()    # all dataclass defaults


def test_golden_subtitle_sub1_force_style():
    sub = _default_subtitle_style()
    margin_v1, _ = _track_margins(sub)
    actual = _build_subtitle_force_style(
        sub.sub1, sub, margin_v=margin_v1, target_h=H)
    _check_golden(actual, "subtitle-sub1-force-style.txt")


def test_golden_subtitle_sub1_sub2_force_styles():
    """Bilingual: sub1 (CJK primary) and sub2 (Latin secondary), both
    enabled. Goldens both force_style strings separated by a sentinel
    so a single file covers the two-track case.
    """
    sub = _default_subtitle_style()
    sub.sub2.enabled = True   # bilingual mode
    margin_v1, margin_v2 = _track_margins(sub)
    s1 = _build_subtitle_force_style(
        sub.sub1, sub, margin_v=margin_v1, target_h=H)
    s2 = _build_subtitle_force_style(
        sub.sub2, sub, margin_v=margin_v2, target_h=H)
    actual = f"# sub1\n{s1}\n\n# sub2\n{s2}\n"
    _check_golden(actual, "subtitle-sub1-sub2-force-styles.txt")


# ── B. Watermark + hook/outro drawtext goldens ──────────────────────────────

def test_golden_text_watermark_drawtext():
    wm = WatermarkStyle(
        enabled=True, type="text",
        text="@my_channel",
        text_fontsize=36, text_color="#FFFFFF", text_opacity=70,
        position="top-right",
        margin_x_pct=0.025, margin_y_pct=0.025,
    )
    snippet = _run_with_tmp_cleanup(
        lambda tmp: _build_text_watermark_drawtext(wm, W, H, tmp))
    actual = _normalize_tmp_paths(snippet)
    _check_golden(actual, "text-watermark-drawtext.txt")


def test_golden_image_watermark_chain(tmp_path):
    """Image watermark needs the file to actually exist on disk — the
    function early-returns if not. Use a pytest tmp_path stub.
    """
    img = tmp_path / "wm.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")    # PNG magic, content irrelevant
    wm = WatermarkStyle(
        enabled=True, type="image",
        image_path=str(img),
        image_scale=0.15, image_opacity=100,
        position="bottom-right",
        margin_x_pct=0.03, margin_y_pct=0.03,
    )
    nodes, out_label = _build_image_watermark_chain(
        wm, W, H,
        prev_label="[v0]", src_label="[wm]", out_label="[v1]")
    # Normalize the input path — it's a pytest tmp dir, varies per run.
    rendered = "\n".join(nodes)
    rendered = rendered.replace(
        str(img).replace("\\", "/").replace(":", "\\:"),
        "<IMG>")
    actual = f"# out_label: {out_label}\n{rendered}\n"
    _check_golden(actual, "image-watermark-chain.txt")


def test_golden_hook_outro_drawtext():
    """Both hook and outro snippets — same primitive (drawtext + textfile),
    different role/position/enable expression.
    """
    ho = HookOutroStyle()    # defaults
    hook_snippet = _run_with_tmp_cleanup(lambda tmp: _drawtext_filter(
        "下集预告：他们这次去了哪里？",
        role="hook", ho=ho, duration=60.0,
        aspect_ratio=(16, 9), tmp_files=tmp, short_edge=1080))
    outro_snippet = _run_with_tmp_cleanup(lambda tmp: _drawtext_filter(
        "感谢观看，下集再见",
        role="outro", ho=ho, duration=60.0,
        aspect_ratio=(16, 9), tmp_files=tmp, short_edge=1080))
    actual = (
        f"# hook\n{_normalize_tmp_paths(hook_snippet)}\n\n"
        f"# outro\n{_normalize_tmp_paths(outro_snippet)}\n"
    )
    _check_golden(actual, "hook-outro-drawtext.txt")
