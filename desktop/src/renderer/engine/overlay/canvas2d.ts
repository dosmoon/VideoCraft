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

const OVERLAY_KINDS = new Set<string>([
  "subtitle_cue",
  "hook_text",
  "outro_text",
  "chapter_hero_card",
  "text_watermark",
  "topic_strip",
  "image_watermark", // image, not text — handled by drawImageWatermark below
]);

/** Whether this overlay kind is handled by the canvas2D path. */
export function isCanvas2dOverlay(kind: string): boolean {
  return OVERLAY_KINDS.has(kind);
}

// Decoded watermark images, keyed by the clip's image_path. Filled by
// preloadImageOverlay (async) before a frame is drawn, so drawOverlayClip stays
// synchronous. Module-level: shared across preview + export.
const imageCache = new Map<string, ImageBitmap>();

/** Decode + cache a watermark image so the sync draw path can use it. Idempotent. */
export async function preloadImageOverlay(imagePath: string, url: string): Promise<void> {
  if (!imagePath || imageCache.has(imagePath)) return;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`image fetch ${resp.status} for ${imagePath}`);
  const bitmap = await createImageBitmap(await resp.blob());
  imageCache.set(imagePath, bitmap);
}

/** Draw an image watermark at its corner + scale. Skips if not yet preloaded. */
function drawImageWatermark(ctx: Ctx2D, clip: Clip, w: number, h: number): boolean {
  const path = typeof clip.data["image_path"] === "string" ? (clip.data["image_path"] as string) : "";
  const img = path ? imageCache.get(path) : undefined;
  if (!img) return false;
  const style = clip.style;
  const scale = num(style, "image_scale", 0.15);
  const opacity = num(style, "image_opacity", 100) / 100;
  const pos = str(style, "position", "top-right");
  const mx = num(style, "margin_x_pct", 0.025) * w;
  const my = num(style, "margin_y_pct", 0.025) * h;
  const drawW = Math.max(1, scale * w);
  const drawH = drawW * (img.height / Math.max(1, img.width));
  const x = pos.endsWith("right") ? w - mx - drawW : mx;
  const y = pos.startsWith("top") ? my : h - my - drawH;
  const prevAlpha = ctx.globalAlpha;
  ctx.globalAlpha = Math.max(0, Math.min(1, opacity));
  ctx.drawImage(img, x, y, drawW, drawH);
  ctx.globalAlpha = prevAlpha;
  return true;
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
 * Text anchor + alignment. Watermarks sit in a corner (position + margins);
 * everything else is horizontally centred at its resolveY line.
 */
function placement(
  clip: Clip,
  fontPx: number,
  w: number,
  h: number,
): { align: CanvasTextAlign; x: number; y: number } {
  if (clip.kind === "text_watermark") {
    const style = clip.style;
    const pos = str(style, "position", "top-right");
    const mx = num(style, "margin_x_pct", 0.025) * w;
    const my = num(style, "margin_y_pct", 0.025) * h;
    const isRight = pos.endsWith("right");
    const isTop = pos.startsWith("top");
    return {
      align: isRight ? "right" : "left",
      x: isRight ? w - mx : mx,
      y: isTop ? my + fontPx / 2 : h - my - fontPx / 2,
    };
  }
  return { align: "center", x: w / 2, y: resolveY(clip, fontPx, h) };
}

// Chapter overlays carry their own data keys (topic_text / title+body) and a
// dedicated geometry (top band / sidebar panel), not the generic centered-text
// path — so they get their own draw routines. Geometry mirrors
// core/composition/primitives/{topic_strip,chapter_hero_card}.py.
const CHAPTER_BASELINE_H = 1080; // chapter fontsizes are absolute px at 1080
const STRIP_H_PCT = 0.055; // topic-strip band height (TopicStripStyle.height_pct)
const STRIP_PAD_X_PCT = 0.025; // strip text left inset (text_padding_pct)
const STRIP_OPACITY = 0.9; // strip band alpha (TopicStripStyle.bg_opacity 90)
const CARD_W_PCT = 0.3; // hero-card panel width (width_pct)
const CARD_MARGIN_X_PCT = 0.025; // hero-card offset from edge (margin_x_pct)
const CARD_PAD_X_PCT = 0.025; // hero-card inner x padding (padding_x_pct)
const CARD_PAD_Y_PCT = 0.03; // hero-card inner y padding (padding_y_pct)
const CARD_ACCENT_W_PCT = 0.005; // accent stripe width (accent_width_pct)
const CARD_GAP_PCT = 0.02; // title↕body gap (title_body_gap_pct)

/** Greedy char-wrap to a max pixel width (CJK-safe; honors explicit \n).
 *  ctx.font must be set by the caller. */
function wrapToWidth(ctx: Ctx2D, text: string, maxW: number): string[] {
  const lines: string[] = [];
  let cur = "";
  for (const ch of text) {
    if (ch === "\n") {
      lines.push(cur);
      cur = "";
    } else if (cur !== "" && ctx.measureText(cur + ch).width > maxW) {
      lines.push(cur);
      cur = ch;
    } else {
      cur += ch;
    }
  }
  if (cur) lines.push(cur);
  return lines;
}

/** Top full-width band with the chapter title, left-inset + vertically centered. */
function drawTopicStrip(ctx: Ctx2D, clip: Clip, w: number, h: number): boolean {
  const title = typeof clip.data["topic_text"] === "string" ? (clip.data["topic_text"] as string) : "";
  if (title.trim() === "") return false;
  const style = clip.style;
  const bandH = STRIP_H_PCT * h;
  ctx.fillStyle = rgba(str(style, "bg_color", "#1E40AF"), STRIP_OPACITY);
  ctx.fillRect(0, 0, w, bandH);

  const fontPx = Math.max(8, (num(style, "fontsize", 26) / CHAPTER_BASELINE_H) * h);
  ctx.font = `bold ${fontPx}px "${str(style, "font", "Microsoft YaHei")}", sans-serif`;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  ctx.fillStyle = str(style, "text_color", "#FFFFFF");
  ctx.fillText(title, STRIP_PAD_X_PCT * w, bandH / 2);
  return true;
}

/** Left-anchored translucent sidebar panel: accent stripe + title + body. */
function drawHeroCard(ctx: Ctx2D, clip: Clip, w: number, h: number): boolean {
  const title = typeof clip.data["title"] === "string" ? (clip.data["title"] as string) : "";
  const body = typeof clip.data["body"] === "string" ? (clip.data["body"] as string) : "";
  if (title.trim() === "" && body.trim() === "") return false;
  const style = clip.style;

  const cardW = CARD_W_PCT * w;
  const marginX = CARD_MARGIN_X_PCT * w;
  const padX = CARD_PAD_X_PCT * w;
  const padY = CARD_PAD_Y_PCT * h;
  const accentW = CARD_ACCENT_W_PCT * w;
  const gap = CARD_GAP_PCT * h;
  const textX = marginX + accentW + padX;
  const innerW = cardW - accentW - padX * 2;

  const titlePx = Math.max(8, (num(style, "title_fontsize", 40) / CHAPTER_BASELINE_H) * h);
  const bodyPx = Math.max(8, (num(style, "body_fontsize", 22) / CHAPTER_BASELINE_H) * h);
  const titleLH = titlePx * 1.25;
  const bodyLH = bodyPx * 1.3;

  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  ctx.font = `bold ${titlePx}px "${str(style, "font", "Microsoft YaHei")}", sans-serif`;
  const titleLines = title.trim() ? wrapToWidth(ctx, title.trim(), innerW) : [];
  ctx.font = `${bodyPx}px "${str(style, "font", "Microsoft YaHei")}", sans-serif`;
  const bodyLines = body.trim() ? wrapToWidth(ctx, body.trim(), innerW) : [];

  const contentH =
    titleLines.length * titleLH +
    (titleLines.length && bodyLines.length ? gap : 0) +
    bodyLines.length * bodyLH;
  const cardH = contentH + padY * 2;
  const cardY = Math.max(0, (h - cardH) / 2);

  // Backdrop + screen-edge accent stripe.
  ctx.fillStyle = rgba(str(style, "bg_color", "#0F1B2C"), num(style, "bg_opacity", 55) / 100);
  ctx.fillRect(marginX, cardY, cardW, cardH);
  if (accentW > 0) {
    ctx.fillStyle = str(style, "accent_color", "#DC2626");
    ctx.fillRect(marginX, cardY, accentW, cardH);
  }

  let y = cardY + padY;
  ctx.font = `bold ${titlePx}px "${str(style, "font", "Microsoft YaHei")}", sans-serif`;
  ctx.fillStyle = str(style, "title_color", "#FFFFFF");
  for (const line of titleLines) {
    ctx.fillText(line, textX, y);
    y += titleLH;
  }
  if (titleLines.length && bodyLines.length) y += gap;
  ctx.font = `${bodyPx}px "${str(style, "font", "Microsoft YaHei")}", sans-serif`;
  ctx.fillStyle = str(style, "body_color", "#E5E7EB");
  for (const line of bodyLines) {
    ctx.fillText(line, textX, y);
    y += bodyLH;
  }
  return true;
}

/**
 * Render one overlay clip into a 2D context sized w×h (caller clears it first).
 * Returns false (no-op) for unhandled kinds or empty text.
 */
export function drawOverlayClip(ctx: Ctx2D, clip: Clip, w: number, h: number): boolean {
  if (clip.kind === "image_watermark") return drawImageWatermark(ctx, clip, w, h);
  if (clip.kind === "topic_strip") return drawTopicStrip(ctx, clip, w, h);
  if (clip.kind === "chapter_hero_card") return drawHeroCard(ctx, clip, w, h);
  if (!isCanvas2dOverlay(clip.kind)) return false;
  const text = typeof clip.data["text"] === "string" ? (clip.data["text"] as string) : "";
  if (text.trim() === "") return false;

  const style = clip.style;
  const isSub = clip.kind === "subtitle_cue";
  // The text watermark emits its own style keys (text_color / text_fontsize_pct
  // / text_opacity) and no stroke/bg — distinct from the card keys (size_pct /
  // color / box_padding_pct) used by hook_text / outro_text. Pick per kind so
  // the watermark's colour, size and opacity actually take effect.
  const isTextWm = clip.kind === "text_watermark";

  const sizeKey = isSub ? "fontsize_pct" : isTextWm ? "text_fontsize_pct" : "size_pct";
  const fontPx = Math.max(8, num(style, sizeKey, 0.05) * h);
  const bold = bool(style, "bold", false);
  const fontName = isSub
    ? bool(style, "is_chinese", false)
      ? "Microsoft YaHei"
      : "Arial"
    : str(style, "font", "Microsoft YaHei");
  const color = str(style, isTextWm ? "text_color" : "color", "#FFFFFF");
  const textAlpha = isTextWm ? num(style, "text_opacity", 100) / 100 : 1;
  const strokeColor = str(style, "stroke_color", "#000000");
  // Text watermark carries no stroke; cards/subtitles do.
  const strokeW = isTextWm ? 0 : num(style, "stroke_pct", isSub ? 0.002 : 0.003) * h;
  const bgColor = str(style, "bg_color", "#000000");
  const bgOpacity = num(style, "bg_opacity", 0) / 100;
  const padPx = num(style, isSub ? "bg_padding_x_pct" : "box_padding_pct", 0.012) * h;

  ctx.font = `${bold ? "bold " : ""}${fontPx}px "${fontName}", sans-serif`;
  ctx.textBaseline = "middle";

  const place = placement(clip, fontPx, w, h);
  ctx.textAlign = place.align;
  const { x, y: centerY } = place;

  // Hook / outro cards wrap to the frame width (multi-line, vertically centered
  // on the placement line). Subtitle cues stay one line (the one-line invariant —
  // cues are pre-split on the timeline); watermarks stay one corner line.
  const wraps = clip.kind === "hook_text" || clip.kind === "outro_text";
  const lines = wraps ? wrapToWidth(ctx, text, w * 0.9) : [text];
  const lineH = fontPx * 1.3;
  const firstY = centerY - ((lines.length - 1) / 2) * lineH;

  lines.forEach((line, i) => {
    const ly = firstY + i * lineH;
    const lineW = ctx.measureText(line).width;
    // Background box's left edge depends on the text alignment.
    const boxLeft =
      place.align === "right"
        ? x - lineW - padPx
        : place.align === "left"
          ? x - padPx
          : x - lineW / 2 - padPx;
    if (bgOpacity > 0) {
      ctx.fillStyle = rgba(bgColor, bgOpacity);
      ctx.fillRect(boxLeft, ly - fontPx / 2 - padPx, lineW + padPx * 2, fontPx + padPx * 2);
    }
    if (strokeW > 0) {
      ctx.lineWidth = strokeW;
      ctx.strokeStyle = strokeColor;
      ctx.lineJoin = "round";
      ctx.strokeText(line, x, ly);
    }
    ctx.fillStyle = textAlpha < 1 ? rgba(color, textAlpha) : color;
    ctx.fillText(line, x, ly);
  });
  return true;
}
