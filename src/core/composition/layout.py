"""Single source of truth for layout math.

CompositionStyle carries normalized [0, 1] frame coordinates
(`block_margin_pct`, `track_gap_pct`, `margin_x_pct`, `margin_y_pct`).
Two completely independent rendering engines — ffmpeg + libass on the
burn side, HTML5 Canvas + CSS on the WebView preview side — consume
those normalized values via the helpers in this module. The engines
still differ in font metrics, anti-aliasing, hinting, etc., but the
*position math* is now a shared semantic instead of two engines'
hand-tuned magic numbers drifting against each other.

If preview and burn still disagree visually after applying these
helpers, the discrepancy is in pixel-level font rendering (libass vs.
browser CSS) — NOT in where we positioned the baseline. That's the
contract.
"""

from __future__ import annotations


# Empirical libass default PlayResY when neither PlayResX nor PlayResY
# are set in the ASS script. libass scales script-pixels by
# (video_h / PlayResY) at render time, so MarginV is independent of
# output_h as long as PlayResY is constant — which it is for libass'
# unset-default codepath.
#
# Calibrated against the existing `ASS_RENDER_SCALE = 4.7` constant in
# core/composition/style.py:compute_subtitle_max_chars (1080 / 4.7 ≈ 230).
# If a different libass build defaults to a different PlayResY, retune
# here once and both `compute_subtitle_max_chars` and `libass_margin_v`
# stay in sync.
LIBASS_DEFAULT_PLAY_RES_Y = 230


def libass_margin_v(margin_pct: float) -> int:
    """Convert "fraction of frame height from anchored edge" → ASS
    MarginV (script-pixel space).

    Output-resolution-independent: same MarginV produces the same %-of-
    frame position whether the video is 720p, 1080p, or 4K, because both
    the desired output-pixel offset and libass' script-px→output-px scale
    grow linearly with video_h.
    """
    return max(0, int(margin_pct * LIBASS_DEFAULT_PLAY_RES_Y))


def pixel_offset(margin_pct: float, frame_dim_px: int,
                  min_px: int = 8) -> int:
    """Convert "fraction of frame dimension" → pixel offset on a frame
    of the given dimension. Used for watermark margins (both libass-side
    overlay and JS preview canvas) and any other position that needs
    direct pixel coordinates.

    `min_px` floors the result so tiny pct values still keep the overlay
    off the absolute edge (where descenders / drop shadows would clip)."""
    return max(min_px, int(margin_pct * frame_dim_px))


def subtitle_baseline_y_from_canvas_top(
    block_margin_pct: float,
    track_gap_pct: float,
    canvas_h: int,
    is_inner_track: bool,
    anchor: str,
) -> float:
    """JS canvas y coordinate (pixels from canvas TOP) for a subtitle
    baseline. `is_inner_track`=True for the track closer to frame
    center (sub1 at bottom anchor, sub2 at top anchor); False for the
    outer track (closer to the anchored edge).

    Mirrors `libass_margin_v` semantically: the outer track sits at
    block_margin_pct from the anchored edge, the inner track one
    track_gap_pct further toward the center.
    """
    extra = track_gap_pct if is_inner_track else 0.0
    pct_from_edge = block_margin_pct + extra
    if anchor == "top":
        return canvas_h * pct_from_edge
    # default = bottom anchor
    return canvas_h * (1.0 - pct_from_edge)
