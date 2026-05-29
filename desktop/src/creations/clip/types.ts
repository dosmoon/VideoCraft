/**
 * Clip creation — wire shapes.
 *
 * TypeScript mirrors of the real Python data the clip plugin produces, so the
 * mapping layer consumes the actual artifacts (not invented shapes):
 *   - component config dicts: creations/clip/components/*.py default_instance
 *   - hotclip candidates: <lang>.hotclips.json entries (creations/clip/clip_tool.py)
 *   - per-clip overrides: ClipInstanceConfig.clips_overrides (config.py)
 *
 * These arrive over IPC from the Python sidecar later; for now they're the
 * fixtures the assembler is tested against.
 */

export type SubtitlePosition = "top" | "bottom";
export type WatermarkCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right";
export type CardPosition = "upper-third" | "center" | "lower-third";

export interface ClipSubtitleConfig {
  kind: "clip_subtitle";
  enabled: boolean;
  language: string;
  fontsize_pct: number;
  color: string;
  bold: boolean;
  is_chinese: boolean;
  bg_color: string;
  bg_opacity: number;
  bg_padding_x_pct: number;
  stroke_color: string;
  stroke_pct: number;
  position: SubtitlePosition;
  block_margin_pct: number;
}

export interface ClipTextWatermarkConfig {
  kind: "clip_text_watermark";
  enabled: boolean;
  text: string;
  text_fontsize_pct: number;
  text_color: string;
  text_opacity: number;
  position: WatermarkCorner;
  margin_x_pct: number;
  margin_y_pct: number;
}

export interface ClipImageWatermarkConfig {
  kind: "clip_image_watermark";
  enabled: boolean;
  image_path: string;
  image_scale: number;
  image_opacity: number;
  position: WatermarkCorner;
  margin_x_pct: number;
  margin_y_pct: number;
}

export interface ClipCardConfig {
  kind: "clip_hook_card" | "clip_outro_card";
  enabled: boolean;
  text: string;
  font: string;
  size_pct: number;
  color: string;
  bg_color: string;
  bg_opacity: number;
  stroke_color: string;
  stroke_pct: number;
  box_padding_pct: number;
  position: CardPosition;
  duration_sec: number;
}

export type ClipComponentConfig =
  | ClipSubtitleConfig
  | ClipTextWatermarkConfig
  | ClipImageWatermarkConfig
  | ClipCardConfig;

/** One entry in <lang>.hotclips.json. Times are "HH:MM:SS.mmm" strings. */
export interface HotclipCandidate {
  start: string;
  end: string;
  hook?: string;
  outro?: string;
  suggested_title?: string;
  hashtags?: string[];
}

/** Per-clip user override (ClipInstanceConfig.clips_overrides[idx]). */
export interface ClipOverride {
  start_sec?: number;
  end_sec?: number;
  hook_text?: string;
  outro_text?: string;
  title?: string;
  hashtags?: string[] | string;
}
