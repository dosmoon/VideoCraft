/**
 * Canvas-2D overlay renderer — rasterises a text/card/subtitle overlay Clip
 * onto a 2D context (transparent background), to be uploaded as a GPU texture
 * and composited over the video.
 *
 * This is the path Phase independently chose for its subtitle layer
 * (dosmoon-phase docs/design/02-architecture.md: "Canvas 2D OffscreenCanvas
 * 文本栅格化 → createImageBitmap → 上传纹理"). It keeps subtitles fully inside
 * the single compositor (preview≡render + export), unlike libass/jassub which
 * renders display-only in a worker (Spike B finding). Full ASS-tag fidelity
 * (karaoke etc.) would still need a bitmap-emitting libass path — out of scope.
 *
 * pct fields follow the engine convention: size/stroke/padding/margin are
 * fractions of target_h.
 */

import type { Clip } from "@composition/ir.js";

const TEXT_OVERLAY_KINDS = new Set<string>([
  "subtitle_cue",
  "hook_text",
  "outro_text",
  "chapter_hero_card",
  "text_watermark",
  "topic_strip",
]);

/** Whether this overlay kind is handled by the canvas2D path. */
export function isCanvas2dOverlay(kind: string): boolean {
  return TEXT_OVERLAY_KINDS.has(kind);
}

type Ctx2D = OffscreenCanvasRenderingContext2D | CanvasRenderingContext2D;

function str(style: Record<string, unknown>, key: string, def: string): string {
  const v = style[key];
  return typeof v === "string" ? v : def;
}
function num(style: Record<string, unknown>, key: string, def: number): number {
  const v = style[key];
  return typeof v === "number" ? v : def;
}
function bool(style: Record<string, unknown>, key: string, def: boolean): boolean {
  const v = style[key];
  return typeof v === "boolean" ? v : def;
}

/** "#RRGGBB" + 0..1 alpha → "rgba(r,g,b,a)". Falls back to the hex as-is. */
function rgba(hex: string, alpha: number): string {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return hex;
  const n = parseInt(m[1]!, 16);
  return `rgba(${(n >> 16) & 0xff},${(n >> 8) & 0xff},${n & 0xff},${alpha})`;
}

/** Vertical centre (px) for the text, by kind + style. */
function resolveY(clip: Clip, fontPx: number, h: number): number {
  const style = clip.style;
  if (clip.kind === "subtitle_cue") {
    const margin = num(style, "block_margin_pct", 0.09) * h;
    const pos = str(style, "position", "bottom");
    return pos === "top" ? margin + fontPx / 2 : h - margin - fontPx / 2;
  }
  const pos =
    str(style, "hook_position", "") ||
    str(style, "outro_position", "") ||
    str(style, "position", "center");
  if (pos === "upper-third") return h * 0.25;
  if (pos === "lower-third") return h * 0.78;
  return h * 0.5;
}

/**
 * Render one overlay clip into a 2D context sized w×h (caller clears it first).
 * Returns false (no-op) for unhandled kinds or empty text.
 */
export function drawOverlayClip(ctx: Ctx2D, clip: Clip, w: number, h: number): boolean {
  if (!isCanvas2dOverlay(clip.kind)) return false;
  const text = typeof clip.data["text"] === "string" ? (clip.data["text"] as string) : "";
  if (text.trim() === "") return false;

  const style = clip.style;
  const isSub = clip.kind === "subtitle_cue";

  const fontPx = Math.max(8, num(style, isSub ? "fontsize_pct" : "size_pct", 0.05) * h);
  const bold = bool(style, "bold", false);
  const fontName = isSub
    ? bool(style, "is_chinese", false)
      ? "Microsoft YaHei"
      : "Arial"
    : str(style, "font", "Microsoft YaHei");
  const color = str(style, "color", "#FFFFFF");
  const strokeColor = str(style, "stroke_color", "#000000");
  const strokeW = num(style, "stroke_pct", isSub ? 0.002 : 0.003) * h;
  const bgColor = str(style, "bg_color", "#000000");
  const bgOpacity = num(style, "bg_opacity", 0) / 100;
  const padPx = num(style, isSub ? "bg_padding_x_pct" : "box_padding_pct", 0.012) * h;

  ctx.font = `${bold ? "bold " : ""}${fontPx}px "${fontName}", sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";

  const cx = w / 2;
  const cy = resolveY(clip, fontPx, h);
  const textW = ctx.measureText(text).width;

  if (bgOpacity > 0) {
    ctx.fillStyle = rgba(bgColor, bgOpacity);
    ctx.fillRect(cx - textW / 2 - padPx, cy - fontPx / 2 - padPx, textW + padPx * 2, fontPx + padPx * 2);
  }
  if (strokeW > 0) {
    ctx.lineWidth = strokeW;
    ctx.strokeStyle = strokeColor;
    ctx.lineJoin = "round";
    ctx.strokeText(text, cx, cy);
  }
  ctx.fillStyle = color;
  ctx.fillText(text, cx, cy);
  return true;
}
