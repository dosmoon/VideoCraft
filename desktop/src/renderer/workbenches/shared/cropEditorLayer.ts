/**
 * Shared reframe crop-EDITOR layer — the on-screen affordance, not a render path.
 *
 * Both the clip CropPreview and the news_desk preview show the WHOLE source and
 * mark the export region with a draggable output-aspect box: outside is dimmed,
 * the box is outlined, and overlays are drawn INSIDE the box (box dims act as the
 * output frame, using the same drawOverlayClip the export uses → the box matches
 * render). The actual pixel crop happens at export via Clip.crop; this is the
 * editing UI. Kept here so every creation that reframes paints an identical box.
 *
 * These live in renderer-shared (not composition/) because paintEditorLayer
 * needs the renderer-only canvas2D overlay painter; canvasDimsFor rides along as
 * its sizing companion.
 */

import type { Clip } from "@composition/ir.js";
import type { ClipMode, CropRect } from "@composition/crop.js";
import { drawOverlayClip } from "../../engine/overlay/canvas2d";

/** Cap the working preview canvas resolution; the relevant aspect is preserved. */
export const MAX_CANVAS = 1280;

/**
 * Preview canvas size for a mode. letterbox previews the OUTPUT frame (target
 * aspect, source contained with bars), so its canvas takes the target aspect;
 * reframe/passthrough preview the whole SOURCE (source aspect — the crop box /
 * full frame marks the export region).
 */
export function canvasDimsFor(
  mode: ClipMode,
  srcW: number,
  srcH: number,
  aw: number,
  ah: number,
): { w: number; h: number } {
  if (mode === "letterbox" && aw > 0 && ah > 0) {
    const w = aw >= ah ? MAX_CANVAS : Math.round((MAX_CANVAS * aw) / ah);
    const h = aw >= ah ? Math.round((MAX_CANVAS * ah) / aw) : MAX_CANVAS;
    return { w: Math.max(2, w), h: Math.max(2, h) };
  }
  const scale = Math.min(1, MAX_CANVAS / Math.max(srcW, srcH));
  return { w: Math.max(2, Math.round(srcW * scale)), h: Math.max(2, Math.round(srcH * scale)) };
}

/**
 * Paint the composited editor layer: dim the frame, clear+outline the crop box,
 * then the overlays drawn inside the box. In letterbox/passthrough the box is the
 * whole canvas (the canvas IS the output frame) and dim/outline are skipped.
 */
export function paintEditorLayer(
  ctx: OffscreenCanvasRenderingContext2D,
  canvasW: number,
  canvasH: number,
  rect: CropRect,
  mode: ClipMode,
  overlayClips: Clip[],
): void {
  ctx.clearRect(0, 0, canvasW, canvasH);

  const box =
    mode === "reframe"
      ? {
          ox: rect.x * canvasW,
          oy: rect.y * canvasH,
          bw: rect.w * canvasW,
          bh: rect.h * canvasH,
        }
      : { ox: 0, oy: 0, bw: canvasW, bh: canvasH };

  if (mode === "reframe") {
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(0, 0, canvasW, canvasH);
    ctx.clearRect(box.ox, box.oy, box.bw, box.bh);
    ctx.strokeStyle = "#00ff88";
    ctx.lineWidth = Math.max(2, canvasW / 480);
    ctx.strokeRect(box.ox, box.oy, box.bw, box.bh);
  }

  for (const clip of overlayClips) {
    ctx.save();
    ctx.translate(box.ox, box.oy);
    ctx.beginPath();
    ctx.rect(0, 0, box.bw, box.bh);
    ctx.clip();
    drawOverlayClip(ctx, clip, box.bw, box.bh);
    ctx.restore();
  }
}
