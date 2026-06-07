/**
 * Reframe crop geometry — pure, faithful port of the Tk clip's crop model so
 * the new GPU crop editor reproduces it exactly (no invention).
 *
 *   - centerCropRect ≡ core/composition/render.py::_center_crop_rect
 *     (also the HTML preview's fitRectToAspect): the largest centered crop at
 *     the output aspect that fits the source.
 *   - clampCropRect ≡ composition_preview.html::clampRect: a dragged box keeps
 *     the output aspect (height derived from width) and stays inside the source.
 *
 * crop_rect is {x,y,w,h} normalized to source-video coords [0..1] — the same
 * shape stored in config.clips_overrides[idx].crop_rect and consumed by render.
 */

export interface CropRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Output framing modes:
 *   - reframe    : crop a (draggable, output-aspect) window of the source — cover.
 *   - letterbox  : keep the WHOLE source, centered in the output frame with bars
 *                  (contain). For landscape content that can't be cropped to
 *                  portrait (e.g. side-by-side speakers).
 *   - passthrough: export the source frame verbatim; aspect/short-edge ignored.
 */
export type ClipMode = "reframe" | "letterbox" | "passthrough";

/** Normalize a stored output_mode string to a known ClipMode (reframe default). */
export function parseClipMode(v: unknown): ClipMode {
  return v === "passthrough" ? "passthrough" : v === "letterbox" ? "letterbox" : "reframe";
}

/**
 * Output (w,h) at a 1080-class short edge, even dims for the encoder — faithful
 * port of render.py::_target_dims_for_aspect. The crop editor sizes its canvas
 * to the SOURCE (so the whole frame shows), but export crops the box and scales
 * it to these dims; kept here as the geometry home for the Inc5 export tab.
 */
export function targetDimsForAspect(aspect: string, shortEdge: number): { width: number; height: number } {
  const { aw, ah } = parseAspect(aspect);
  let w: number;
  let h: number;
  if (aw < ah) {
    w = shortEdge;
    h = Math.round((shortEdge * ah) / aw);
  } else {
    h = shortEdge;
    w = Math.round((shortEdge * aw) / ah);
  }
  const even = (n: number) => ((n + 1) >> 1) << 1;
  return { width: even(w), height: even(h) };
}

/** "9:16" → {aw:9, ah:16}; bad input falls back to 9:16 (the clip default). */
export function parseAspect(aspect: string): { aw: number; ah: number } {
  const m = /^(\d+):(\d+)$/.exec(aspect);
  if (!m) return { aw: 9, ah: 16 };
  const aw = Number(m[1]);
  const ah = Number(m[2]);
  return aw > 0 && ah > 0 ? { aw, ah } : { aw: 9, ah: 16 };
}

/** Largest centered crop at `aw:ah` that fits a srcW×srcH source. */
export function centerCropRect(srcW: number, srcH: number, aw: number, ah: number): CropRect {
  if (srcW <= 0 || srcH <= 0) return { x: 0, y: 0, w: 1, h: 1 };
  const targetAr = Math.max(0.001, aw / ah);
  const curAr = srcW / srcH;
  if (curAr > targetAr) {
    const newW = srcH * targetAr;
    const x = (srcW - newW) / 2;
    return { x: x / srcW, y: 0, w: newW / srcW, h: 1 };
  }
  const newH = srcW / targetAr;
  const y = (srcH - newH) / 2;
  return { x: 0, y: y / srcH, w: 1, h: newH / srcH };
}

/**
 * Re-derive height from width at the output aspect, then clamp the box inside
 * [0,1]². Keeps `w` and the (x,y) anchor the caller set (a drag), but forces
 * the aspect — so the box is always a faithful output-aspect window.
 */
export function clampCropRect(
  rect: CropRect,
  srcW: number,
  srcH: number,
  aw: number,
  ah: number,
): CropRect {
  if (srcW <= 0 || srcH <= 0) return rect;
  const aspectRatio = Math.max(0.001, aw / ah);
  let w = rect.w;
  let h = (w * srcW) / aspectRatio / srcH;
  if (h > 1) {
    h = 1;
    w = (h * srcH * aspectRatio) / srcW;
  }
  const x = Math.max(0, Math.min(1 - w, rect.x));
  const y = Math.max(0, Math.min(1 - h, rect.y));
  return { x, y, w, h };
}
