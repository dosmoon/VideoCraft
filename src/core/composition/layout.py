"""Single source of truth for layout math.

All visible quantities in component schemas — positions AND sizes — are
expressed as fractions of the frame:

  - position offsets / paddings: fraction of frame height (target_h),
    e.g. `block_margin_pct = 0.09` = 9% of frame height from the
    anchored edge.
  - font sizes / stroke widths: fraction of the SHORT edge (smaller of
    target_w / target_h), e.g. `fontsize_pct = 0.04` = 4% of short
    edge → ~43 px at 1080p short edge. Short-edge baseline makes text
    look the same visual size across 9:16, 16:9, etc.

Two rendering engines consume these:

  - ffmpeg + libass on burn (renders subtitles via `subtitles=` filter
    with `original_size=target_w x target_h` → ASS Fontsize / Outline /
    MarginV in script units map 1:1 to video pixels).
  - HTML5 Canvas in preview (`fontPx = pct * canvas_short_edge`).

Both engines compute pixel quantities by multiplying pct fields by the
appropriate frame dimension. No empirically-calibrated scale constants
sit between them — that was the old `ASS_RENDER_SCALE = 4.7` /
`LIBASS_DEFAULT_PLAY_RES_Y = 230` / `ASS_DESIGN_SCALE = 4.7` family,
all retired.

If preview and burn still disagree visually after applying these
helpers, the discrepancy is in pixel-level font rendering (libass vs.
browser CSS) — NOT in where we positioned the baseline. That's the
contract.
"""

from __future__ import annotations


def libass_margin_v(margin_pct: float, target_h: int) -> int:
    """Convert "fraction of frame height from anchored edge" → ASS
    MarginV value. With `original_size=target_w x target_h` set on the
    subtitle filter, libass' script-pixel space matches target-pixel
    space 1:1, so MarginV is just pct of target_h."""
    return max(0, int(margin_pct * target_h))


def font_size_px(pct: float, short_edge: int) -> int:
    """Convert "fraction of short edge" → pixel font size on a frame of
    the given short edge. Used uniformly for libass Fontsize, drawtext
    fontsize, and canvas-side font px. Short edge keeps text visually
    consistent across 9:16 and 16:9 aspects."""
    return max(1, int(round(pct * short_edge)))


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
