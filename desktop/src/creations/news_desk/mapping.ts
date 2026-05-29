/**
 * News-desk mapping — adapt news_desk's config onto the shared canonical
 * component instances. This is the counterpart to creations/clip/mapping.ts:
 * same target components, a different adapter. Together they prove the shared
 * library covers more than one plugin (foundation doc §4.5).
 *
 * news_desk's conventions diverge from canonical and are normalised here,
 * exactly mirroring the legacy compile() conversions:
 *   - block_margin_pct / margin_*_pct / scale_pct: integer percent → fraction.
 *   - margins clamp to [0, 0.20]; image scale clamps to [0.02, 0.50].
 *   - bg_enabled flag folds into bg_opacity (disabled → 0).
 *   - canonical-only fields news_desk doesn't expose (bold, bgPaddingXPct,
 *     subtitle language) take neutral defaults.
 */

import type {
  ChapterInstance,
  ImageWatermarkInstance,
  SubtitleInstance,
  TextWatermarkInstance,
} from "../../composition/components/index.js";
import type {
  NewsDeskChapterConfig,
  NewsDeskImageWatermarkConfig,
  NewsDeskSubtitleConfig,
  NewsDeskTextWatermarkConfig,
} from "./types.js";

const clamp = (v: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, v));
const clampOpacity = (v: number): number => clamp(Math.trunc(v), 0, 100);

export function newsDeskSubtitleToInstance(c: NewsDeskSubtitleConfig): SubtitleInstance {
  return {
    enabled: c.enabled,
    language: "", // news_desk binds a single SRT per instance, no language picker
    fontsizePct: c.fontsize_pct,
    color: c.color,
    bold: false, // not exposed by news_desk
    isChinese: c.is_chinese,
    bgColor: c.bg_color,
    bgOpacity: c.bg_enabled ? clampOpacity(c.bg_opacity) : 0,
    bgPaddingXPct: 0, // not exposed by news_desk
    strokeColor: c.stroke_color,
    strokePct: c.stroke_pct,
    position: c.position,
    blockMarginPct: c.block_margin_pct / 100,
  };
}

export function newsDeskTextWatermarkToInstance(
  c: NewsDeskTextWatermarkConfig,
): TextWatermarkInstance {
  return {
    enabled: c.enabled,
    text: c.text,
    textFontsizePct: c.fontsize_pct,
    textColor: c.color,
    textOpacity: clampOpacity(c.opacity),
    position: c.position,
    marginXPct: clamp(c.margin_x_pct / 100, 0, 0.2),
    marginYPct: clamp(c.margin_y_pct / 100, 0, 0.2),
  };
}

export function newsDeskImageWatermarkToInstance(
  c: NewsDeskImageWatermarkConfig,
): ImageWatermarkInstance {
  return {
    enabled: c.enabled,
    imagePath: c.image_path,
    imageScale: clamp(c.scale_pct / 100, 0.02, 0.5),
    imageOpacity: clampOpacity(c.opacity),
    position: c.position,
    marginXPct: clamp(c.margin_x_pct / 100, 0, 0.2),
    marginYPct: clamp(c.margin_y_pct / 100, 0, 0.2),
  };
}

export function newsDeskChapterToInstance(c: NewsDeskChapterConfig): ChapterInstance {
  const top = c.style.top_strip;
  const card = c.style.start_card;
  return {
    enabled: c.enabled,
    modes: { topStrip: c.modes.top_strip, startCard: c.modes.start_card },
    style: {
      topStrip: { bgColor: top.bg_color, textColor: top.text_color, fontsize: top.fontsize },
      startCard: {
        titleColor: card.title_color,
        titleFontsize: card.title_fontsize,
        bodyColor: card.body_color,
        bodyFontsize: card.body_fontsize,
        bgColor: card.bg_color,
        bgOpacity: card.bg_opacity,
        accentColor: card.accent_color,
        durationSec: card.duration_sec,
      },
    },
    schedule: c.schedule.map((row) => ({
      startSec: row.start_sec,
      endSec: row.end_sec,
      title: row.title,
      refined: row.refined,
      keyPoints: row.key_points,
    })),
  };
}
