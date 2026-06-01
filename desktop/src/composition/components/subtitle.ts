/**
 * Subtitle component — source-anchored caption cues rippled through the
 * assembly's TimeMap (invariant #6) into one overlay track of subtitle_cue
 * clips, each carrying the instance's inlined style.
 *
 * Unifies creations/clip/components/subtitle.py and
 * creations/news_desk/components/subtitle.py. Divergences resolved:
 *   - block_margin_pct: float fraction everywhere (news_desk's int% dropped).
 *   - bg_opacity: a plain 0..100 field (news_desk's separate bg_enabled flag
 *     folded in — opacity 0 means no background).
 *   - SRT sourcing: the host parses the SRT and passes `ctx.cues` in source
 *     time; the component stays pure (no I/O).
 */

import type { Track } from "../ir.js";
import { deriveOverlayTrack, type SourceAnchoredCue } from "../timemap.js";
import { fitCues } from "../subtitleWrap.js";
import type { CompileContext, VideoComponent } from "./contract.js";
import type { FieldSpec } from "./fieldSpec.js";

export interface SubtitleInstance {
  enabled: boolean;
  /** Optional subtitle-track language code (host-supplied picker). */
  language: string;
  fontsizePct: number; // fraction of target_h
  color: string;
  bold: boolean;
  isChinese: boolean;
  bgColor: string;
  bgOpacity: number; // 0..100
  bgPaddingXPct: number; // fraction of target_h
  strokeColor: string;
  strokePct: number; // fraction of target_h
  position: "top" | "bottom";
  blockMarginPct: number; // fraction of target_h
}

/** Inline the instance into the subtitle_cue primitive's style contract. */
function subtitleStyle(i: SubtitleInstance): Record<string, unknown> {
  return {
    fontsize_pct: i.fontsizePct,
    color: i.color,
    bold: i.bold,
    is_chinese: i.isChinese,
    bg_color: i.bgColor,
    bg_opacity: i.bgOpacity,
    bg_padding_x_pct: i.bgPaddingXPct,
    stroke_color: i.strokeColor,
    stroke_pct: i.strokePct,
    position: i.position,
    block_margin_pct: i.blockMarginPct,
  };
}

export const subtitle: VideoComponent<SubtitleInstance> = {
  kind: "subtitle",

  defaultInstance(): SubtitleInstance {
    return {
      enabled: true,
      language: "",
      fontsizePct: 0.05,
      color: "#FFFFFF",
      bold: false,
      isChinese: false,
      bgColor: "#000000",
      bgOpacity: 0,
      bgPaddingXPct: 0,
      strokeColor: "#000000",
      strokePct: 0.002,
      position: "bottom",
      blockMarginPct: 0.09,
    };
  },

  compile(instance: SubtitleInstance, ctx: CompileContext): Track[] {
    if (!instance.enabled || !ctx.cues || ctx.cues.length === 0) return [];
    const style = subtitleStyle(instance);
    // Fit each cue to one line at the output aspect (split long cues across
    // time) so they never overflow the frame — the one-line invariant. Only
    // when the host supplies the frame aspect; otherwise pass cues through.
    const sourceCues =
      ctx.frameAspect != null ? fitCues(ctx.cues, instance.fontsizePct, ctx.frameAspect) : ctx.cues;
    const cues: SourceAnchoredCue[] = sourceCues.map((c) => ({
      kind: "subtitle_cue",
      sourceStart: c.sourceStart,
      sourceEnd: c.sourceEnd,
      style,
      data: { text: c.text },
    }));
    return [deriveOverlayTrack(cues, ctx.timeMap)];
  },
};

/**
 * Edit-UI fields (wire snake keys). A superset across plugins: clip-only fields
 * (language, bold, bg_padding_x_pct) and news_desk-only (bg_enabled) are simply
 * absent on the other plugin's instance, so the editor skips them. `language`
 * options are host-supplied at render time (enums override).
 */
export const subtitleFields: readonly FieldSpec[] = [
  { key: "name", control: "text", labelKey: "subtitle.name" },
  { key: "language", control: "select", labelKey: "subtitle.language" },
  {
    key: "position",
    control: "select",
    labelKey: "subtitle.position",
    options: ["top", "bottom"],
    optionLabelKeys: { top: "subtitle.position.top", bottom: "subtitle.position.bottom" },
  },
  { key: "block_margin_pct", control: "number", labelKey: "subtitle.block_margin", step: 0.01, min: 0, max: 0.4 },
  { key: "fontsize_pct", control: "number", labelKey: "subtitle.fontsize", step: 0.005, min: 0, max: 0.5 },
  { key: "color", control: "color", labelKey: "subtitle.color" },
  { key: "bold", control: "checkbox", labelKey: "subtitle.bold" },
  { key: "is_chinese", control: "checkbox", labelKey: "subtitle.is_chinese" },
  { key: "stroke_color", control: "color", labelKey: "subtitle.stroke_color" },
  { key: "stroke_pct", control: "number", labelKey: "subtitle.stroke_width", step: 0.001, min: 0, max: 0.02 },
  { key: "bg_enabled", control: "checkbox", labelKey: "subtitle.bg_enabled" },
  { key: "bg_color", control: "color", labelKey: "subtitle.bg_color" },
  { key: "bg_opacity", control: "number", labelKey: "subtitle.bg_opacity", step: 1, min: 0, max: 100 },
  { key: "bg_padding_x_pct", control: "number", labelKey: "subtitle.bg_padding_x", step: 0.005, min: 0, max: 0.2 },
];
