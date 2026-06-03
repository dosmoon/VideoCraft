/**
 * Export settings — engine + output params, persisted per-creation in config.json
 * (clip + news_desk owners). Pure value object + normalizers + resolution/engine
 * mappers (no Fs/window), so the logic is trivially unit-testable and shared by
 * both config owners and the export tabs.
 *
 * Resolution is asymmetric by design: clip already owns `output_short_edge`
 * (reframe geometry), so the clip resolution control writes THAT (single source);
 * news_desk is full-source so it gets its own `export_resolution` downscale preset.
 */

/** "" = auto (resolve from ffmpeg availability); explicit choice always wins. */
export type ExportEngineChoice = "" | "chromium" | "ffmpeg";
export type BitrateMode = "auto" | "mbps";

export interface ExportSettings {
  engine: ExportEngineChoice;
  /** Resolution preset token ("source" | a short-edge px string like "1080"). */
  resolution: string;
  fps: number;
  bitrateMode: BitrateMode;
  bitrateMbps: number;
}

export const FPS_PRESETS = [24, 25, 30, 50, 60] as const;
/** clip: short-edge px (clip reframes to aspect × shortEdge; no "source"). */
export const CLIP_RESOLUTIONS = ["2160", "1440", "1080", "720", "480"] as const;
/** news_desk: downscale-from-source short-edge cap (+ "source" = no scale). */
export const FULL_RESOLUTIONS = ["source", "2160", "1440", "1080", "720", "480"] as const;

export const DEFAULT_EXPORT_SETTINGS: ExportSettings = {
  engine: "",
  resolution: "source",
  fps: 30,
  bitrateMode: "auto",
  bitrateMbps: 12,
};

export function normalizeEngine(v: unknown): ExportEngineChoice {
  return v === "chromium" || v === "ffmpeg" ? v : "";
}
export function normalizeFps(v: unknown): number {
  const n = Math.round(Number(v));
  return Number.isFinite(n) && n >= 1 && n <= 120 ? n : 30;
}
export function normalizeBitrateMode(v: unknown): BitrateMode {
  return v === "mbps" ? "mbps" : "auto";
}
export function normalizeMbps(v: unknown): number {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? Math.min(200, Math.max(1, Math.round(n))) : 12;
}
export function normalizeResolution(v: unknown): string {
  const s = String(v ?? "source");
  return s === "source" || /^\d{3,4}$/.test(s) ? s : "source";
}

export interface FfmpegProbe {
  ffmpeg: boolean;
  nvenc: boolean;
}

/** Engine to use when the user left the choice on auto (""). */
export function defaultEngine(probe: FfmpegProbe | null): "chromium" | "ffmpeg" {
  return probe?.ffmpeg && probe.nvenc ? "ffmpeg" : "chromium";
}
/** Resolve the actual engine: an explicit choice wins, but a requested ffmpeg
 *  with no ffmpeg available falls back to chromium (config authored elsewhere). */
export function effectiveEngine(
  choice: ExportEngineChoice,
  probe: FfmpegProbe | null,
): "chromium" | "ffmpeg" {
  if (choice === "ffmpeg") return probe?.ffmpeg ? "ffmpeg" : "chromium";
  if (choice === "chromium") return "chromium";
  return defaultEngine(probe);
}

export function evenDim(n: number): number {
  return Math.max(2, Math.floor(n / 2) * 2);
}

/**
 * Scale (srcW,srcH) so the SHORT edge ≤ preset px, preserving aspect; never
 * upscale. "source"/non-numeric → source dims. Both dims forced even (encoders).
 */
export function downscaleToShortEdge(
  srcW: number,
  srcH: number,
  preset: string,
): { width: number; height: number } {
  const target = Number(preset);
  if (!Number.isFinite(target) || target <= 0) return { width: evenDim(srcW), height: evenDim(srcH) };
  const short = Math.min(srcW, srcH);
  if (target >= short) return { width: evenDim(srcW), height: evenDim(srcH) };
  const scale = target / short;
  return { width: evenDim(srcW * scale), height: evenDim(srcH * scale) };
}

/** Clip resolution preset → short-edge px. */
export function presetToShortEdge(preset: string, fallback = 1080): number {
  const n = Number(preset);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : fallback;
}

/** Read the common (engine/fps/bitrate) export fields from a config dict.
 *  Resolution is filled per-creation by the tab (clip↔output_short_edge,
 *  news_desk↔export_resolution). */
export function exportSettingsFromConfig(
  cfg: Record<string, unknown> | null | undefined,
): ExportSettings {
  if (!cfg) return { ...DEFAULT_EXPORT_SETTINGS };
  return {
    engine: normalizeEngine(cfg["export_engine"]),
    resolution: normalizeResolution(cfg["export_resolution"]),
    fps: normalizeFps(cfg["export_fps"] ?? 30),
    bitrateMode: normalizeBitrateMode(cfg["export_bitrate_mode"]),
    bitrateMbps: normalizeMbps(cfg["export_bitrate_mbps"]),
  };
}
