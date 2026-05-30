/**
 * Clip mapping — adapt the clip plugin's config/analysis shapes onto the shared
 * canonical component instances (foundation doc §6: per-plugin keeps "pick
 * components + analysis→config mapping + preset + workbench"; the components and
 * their compile→OTIO are shared).
 *
 * clip's field convention already matches the canonical schema (the canonical
 * components were normalised against it), so most adapters are a snake_case →
 * camelCase rename. The genuinely clip-specific orchestration is here too:
 * timestamp parsing, candidate start/end resolution, hook/outro text fill, and
 * subtitle margin stacking (ports composer.py::expand_for_candidate).
 */

import type {
  CardInstance,
  ImageWatermarkInstance,
  SubtitleInstance,
  TextWatermarkInstance,
} from "../../composition/components/index.js";
import type {
  ClipCardConfig,
  ClipImageWatermarkConfig,
  ClipOverride,
  ClipSubtitleConfig,
  ClipTextWatermarkConfig,
  CropRect,
  HotclipCandidate,
} from "./types.js";

// ── Timestamp + candidate window ────────────────────────────────────────────

// Mirrors clip_tool.py::_TS_RE — "[HH:]MM:SS[.mmm]".
const TS_RE = /^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d+))?$/;

/** Parse an "[HH:]MM:SS[.mmm]" timestamp to seconds (0 on malformed input). */
export function parseTimestamp(s: string): number {
  const m = TS_RE.exec((s ?? "").trim());
  if (!m) return 0;
  const h = m[1] ? parseInt(m[1], 10) : 0;
  const mn = parseInt(m[2]!, 10);
  const sec = parseInt(m[3]!, 10);
  let base = h * 3600 + mn * 60 + sec;
  if (m[4]) base += parseInt(m[4].slice(0, 3).padEnd(3, "0"), 10) / 1000;
  return base;
}

/** Format seconds as "HH:MM:SS.mmm" — inverse of parseTimestamp (clip_editor._format_ts). */
export function formatTimestamp(seconds: number): string {
  const s = Math.max(0, seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = (s % 60).toFixed(3); // SS.mmm
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${rest.padStart(6, "0")}`;
}

/** Resolve the candidate's [start, end] window, override winning per field. */
export function resolveStartEnd(
  candidate: HotclipCandidate,
  override?: ClipOverride,
): [number, number] {
  const start = override?.start_sec ?? parseTimestamp(candidate.start);
  const end = override?.end_sec ?? parseTimestamp(candidate.end);
  return [start, end];
}

/** Hook text: override wins, else the candidate's AI hook line. */
export function resolveHookText(candidate: HotclipCandidate, override?: ClipOverride): string {
  return (override?.hook_text ?? candidate.hook ?? "").trim();
}

/** Outro text: override wins, else the candidate's AI closing CTA. */
export function resolveOutroText(candidate: HotclipCandidate, override?: ClipOverride): string {
  return (override?.outro_text ?? candidate.outro ?? "").trim();
}

/**
 * Effective title: override wins, else the candidate's AI suggested title.
 * Mirrors clip_tool.py::_effective_title — "title" key presence wins; absence
 * (the panel deletes the key on empty input) falls back to the AI value.
 */
export function resolveTitle(candidate: HotclipCandidate, override?: ClipOverride): string {
  if (override?.title !== undefined) return String(override.title);
  return (candidate.suggested_title ?? "").trim();
}

/**
 * Effective hashtags: override wins, else AI `suggested_hashtags`/`hashtags`.
 * Mirrors clip_tool.py::_effective_tags — an override string is whitespace-split
 * into a list; a list is taken as-is; anything else yields [].
 */
export function resolveTags(candidate: HotclipCandidate, override?: ClipOverride): string[] {
  if (override?.hashtags !== undefined) {
    const t = override.hashtags;
    if (Array.isArray(t)) return t.map(String);
    if (typeof t === "string") return t.split(/\s+/).filter((s) => s.length > 0);
    return [];
  }
  const t = candidate.suggested_hashtags ?? candidate.hashtags;
  return Array.isArray(t) ? t.map(String) : [];
}

/**
 * Effective crop: the candidate's own crop_rect override, or null (= center
 * default at render time). Mirrors clip_tool.py::_effective_crop — the Style
 * tab's staging rect is NOT a fallback; users push it onto candidates
 * explicitly via "apply crop to all".
 */
export function resolveCrop(override?: ClipOverride): CropRect | null {
  return override?.crop_rect ?? null;
}

// ── Config → canonical instance ──────────────────────────────────────────────

export function clipSubtitleToInstance(c: ClipSubtitleConfig): SubtitleInstance {
  return {
    enabled: c.enabled,
    language: c.language,
    fontsizePct: c.fontsize_pct,
    color: c.color,
    bold: c.bold,
    isChinese: c.is_chinese,
    bgColor: c.bg_color,
    bgOpacity: c.bg_opacity,
    bgPaddingXPct: c.bg_padding_x_pct,
    strokeColor: c.stroke_color,
    strokePct: c.stroke_pct,
    position: c.position,
    blockMarginPct: c.block_margin_pct,
  };
}

export function clipTextWatermarkToInstance(c: ClipTextWatermarkConfig): TextWatermarkInstance {
  return {
    enabled: c.enabled,
    text: c.text,
    textFontsizePct: c.text_fontsize_pct,
    textColor: c.text_color,
    textOpacity: c.text_opacity,
    position: c.position,
    marginXPct: c.margin_x_pct,
    marginYPct: c.margin_y_pct,
  };
}

export function clipImageWatermarkToInstance(c: ClipImageWatermarkConfig): ImageWatermarkInstance {
  return {
    enabled: c.enabled,
    imagePath: c.image_path,
    imageScale: c.image_scale,
    imageOpacity: c.image_opacity,
    position: c.position,
    marginXPct: c.margin_x_pct,
    marginYPct: c.margin_y_pct,
  };
}

export function clipCardToInstance(c: ClipCardConfig, text: string): CardInstance {
  return {
    enabled: c.enabled,
    text,
    font: c.font,
    sizePct: c.size_pct,
    color: c.color,
    bgColor: c.bg_color,
    bgOpacity: c.bg_opacity,
    strokeColor: c.stroke_color,
    strokePct: c.stroke_pct,
    boxPaddingPct: c.box_padding_pct,
    position: c.position,
    durationSec: c.duration_sec,
  };
}

// ── Subtitle margin stacking (ports composer.py::_stamp_subtitle_margin_v) ────

/** Gap between two subtitles sharing an anchor edge. Constant, not user-tunable. */
const STACK_GAP_PCT = 0.04;

/**
 * Stack subtitles that share a position: the earlier one in list order (higher
 * z) sits at its base margin, the next at base + gap, etc. Mutates each
 * instance's `blockMarginPct` in place to the effective stacked value. Only
 * subtitles that will actually render (enabled + cues present) participate.
 *
 * Collapses the legacy `effective_block_margin_pct` dual field — the canonical
 * SubtitleInstance carries a single blockMarginPct (pre-alpha, no legacy).
 */
export function stackSubtitleMargins(
  subtitles: readonly { instance: SubtitleInstance; hasCues: boolean }[],
): void {
  const byPosition = new Map<string, SubtitleInstance[]>();
  for (const { instance, hasCues } of subtitles) {
    if (!instance.enabled || !hasCues) continue;
    const group = byPosition.get(instance.position) ?? [];
    group.push(instance);
    byPosition.set(instance.position, group);
  }
  for (const group of byPosition.values()) {
    group.forEach((instance, i) => {
      instance.blockMarginPct = instance.blockMarginPct + i * STACK_GAP_PCT;
    });
  }
}
