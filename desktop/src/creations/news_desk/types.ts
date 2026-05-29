/**
 * News-desk creation — wire shapes.
 *
 * TypeScript mirrors of the real Python config the news_desk plugin produces
 * (creations/news_desk/components/*.py default_instance + config.py). These
 * deliberately differ from clip's shapes — different field names and unit
 * conventions (int% vs float fraction, bg_enabled flag) — which is exactly what
 * the per-plugin mapping layer absorbs so the *shared* components stay shared.
 */

export type SubtitlePosition = "top" | "bottom";
export type WatermarkCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

export interface NewsDeskSubtitleConfig {
  kind: "subtitle";
  enabled: boolean;
  /** Snapshot-relative SRT path; the cue source key. */
  srt_path: string;
  position: SubtitlePosition;
  block_margin_pct: number; // INTEGER percent (e.g. 9), not a fraction
  fontsize_pct: number; // float fraction
  color: string;
  is_chinese: boolean;
  stroke_color: string;
  stroke_pct: number; // float fraction
  bg_enabled: boolean;
  bg_color: string;
  bg_opacity: number; // 0..100
}

export interface NewsDeskTextWatermarkConfig {
  kind: "text_watermark";
  enabled: boolean;
  text: string;
  fontsize_pct: number; // float fraction (note: not text_fontsize_pct)
  color: string;
  opacity: number; // 0..100 (note: not text_opacity)
  position: WatermarkCorner;
  margin_x_pct: number; // INTEGER percent
  margin_y_pct: number; // INTEGER percent
}

export interface NewsDeskImageWatermarkConfig {
  kind: "image_watermark";
  enabled: boolean;
  image_path: string;
  scale_pct: number; // INTEGER percent (note: not image_scale)
  opacity: number; // 0..100
  position: WatermarkCorner;
  margin_x_pct: number; // INTEGER percent
  margin_y_pct: number; // INTEGER percent
}

export interface NewsDeskChapterRow {
  start_sec: number; // source time (seconds)
  end_sec: number;
  title: string;
  refined: string;
  key_points: string[];
}

export interface NewsDeskTopStripStyle {
  bg_color: string;
  text_color: string;
  fontsize: number;
}

export interface NewsDeskStartCardStyle {
  title_color: string;
  title_fontsize: number;
  body_color: string;
  body_fontsize: number;
  bg_color: string;
  bg_opacity: number;
  accent_color: string;
  duration_sec: number;
}

export interface NewsDeskChapterConfig {
  kind: "chapter";
  enabled: boolean;
  modes: { top_strip: boolean; start_card: boolean };
  style: { top_strip: NewsDeskTopStripStyle; start_card: NewsDeskStartCardStyle };
  schedule: NewsDeskChapterRow[];
}

export type NewsDeskComponentConfig =
  | NewsDeskSubtitleConfig
  | NewsDeskTextWatermarkConfig
  | NewsDeskImageWatermarkConfig
  | NewsDeskChapterConfig;
