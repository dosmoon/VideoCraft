/**
 * News-desk creation — wire shapes.
 *
 * TypeScript mirrors of the real Python config the news_desk plugin produces
 * (creations/news_desk/component_defs.py + config.py). Post-normalisation these
 * use the SAME canonical wire shape as clip (float-fraction *_pct, canonical
 * field names), so the one shared FieldSpec/ComponentEditor + mapping serves
 * both plugins. The only news_desk-specific wire fields left are `bg_enabled`
 * (subtitle) and the chapter nesting; the mapping absorbs those.
 */

export type SubtitlePosition = "top" | "bottom";
export type WatermarkCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

export interface NewsDeskSubtitleConfig {
  kind: "subtitle";
  enabled: boolean;
  /** Snapshot-relative SRT path; the cue source key. */
  srt_path: string;
  position: SubtitlePosition;
  block_margin_pct: number; // float fraction of target_h (e.g. 0.09)
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
  text_fontsize_pct: number; // float fraction of target_h
  text_color: string;
  text_opacity: number; // 0..100
  position: WatermarkCorner;
  margin_x_pct: number; // float fraction of target_w
  margin_y_pct: number; // float fraction of target_h
}

export interface NewsDeskImageWatermarkConfig {
  kind: "image_watermark";
  enabled: boolean;
  image_path: string;
  image_scale: number; // float fraction of target_w
  image_opacity: number; // 0..100
  position: WatermarkCorner;
  margin_x_pct: number; // float fraction of target_w
  margin_y_pct: number; // float fraction of target_h
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
