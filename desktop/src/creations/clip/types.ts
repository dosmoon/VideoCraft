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

export type DubbingMode = "replace" | "mix";

/** Dubbing audio track for a clip: a synthesized voiceover (material
 *  `<lang>.dub.mp3`, snapshotted into the instance) laid over the candidate's
 *  cut window. The dub file is aligned to the FULL source timeline, so each
 *  candidate slices its own [start, end] window (mirrors the source audio).
 *  `replace` swaps the original audio; `mix` plays it under at `gain_db` with
 *  the original ducked to `source_gain_db`. */
export interface ClipDubbingConfig {
  kind: "clip_dubbing";
  enabled: boolean;
  /** Snapshot-relative path to the dubbing audio (e.g. "source-dub.en.mp3"). */
  audio_path: string;
  gain_db: number;
  source_gain_db: number;
  offset_sec: number;
  mode: DubbingMode;
}

export type ClipComponentConfig =
  | ClipSubtitleConfig
  | ClipTextWatermarkConfig
  | ClipImageWatermarkConfig
  | ClipCardConfig
  | ClipDubbingConfig;

/** One entry in <lang>.hotclips.json. Times are "HH:MM:SS.mmm" strings. */
export interface HotclipCandidate {
  start: string;
  end: string;
  /** Clip length in seconds (AI-supplied; shown in the candidate row). */
  duration_sec?: number;
  /** Virality score (AI-supplied; drives the row's ⭐ colour). */
  score?: number;
  hook?: string;
  outro?: string;
  suggested_title?: string;
  /** AI-suggested publication hashtags (off-screen metadata). */
  suggested_hashtags?: string[];
  hashtags?: string[];
}

/** Normalized crop window in source-video coords [0..1] (clips_overrides[idx].crop_rect). */
export interface CropRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Per-clip user override (ClipInstanceConfig.clips_overrides[idx]). */
export interface ClipOverride {
  start_sec?: number;
  end_sec?: number;
  hook_text?: string;
  outro_text?: string;
  title?: string;
  hashtags?: string[] | string;
  crop_rect?: CropRect;
}
